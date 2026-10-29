# vsg_core/postprocess/auditors/subtitle_bars.py
"""Rescaled subtitles vs black bars: two read-only checks.

Runs only for subtitle tracks whose rescale added black bars of at least one
whole pixel (``PlanItem.rescale_picture``): the subtitles' own video and
Source 1 have different picture shapes. That happens when the subtitles come
from a release that cropped away bars Source 1 still has (a 4:3 crop vs a
pillarboxed Blu-ray), or from a release that frames the picture differently
(a 4:3 pan-and-scan DVD vs a 16:9 one). Nothing here changes the output.

1. Bars: are Source 1's pixels really black where the rescale put the bars,
   and does its picture reach the edges the rescale assumed? Keyframes are
   decoded and streamed; the brightest value of each column / row across all
   of them is kept, so a dark scene can't fake a bar (one bright frame proves
   a column is picture). If the bars aren't there, the two releases frame the
   picture differently and sign positions will be off.
2. Overflow (only once the bars are confirmed): does any subtitle land in the
   bars? The muxed track is rendered with libass on a black canvas of Source
   1's size, and only the bar strips are read. Signs a typesetter let run
   past the old frame edge were hidden by that edge; in the bars they show.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .base import BaseAuditor

if TYPE_CHECKING:
    from vsg_core.models.jobs import PlanItem

# 8-bit luma at or below this is "black". Video black is 16 (limited range);
# bars on discs sit at 16 with a little noise. Real picture in a column goes
# well above it in at least one keyframe of an episode.
_BLACK_LUMA = 40
# A measured picture edge within this many pixels of the expected one counts
# as matching: real discs often have a soft 1-2 px edge where bar meets
# picture. The measured values are always logged.
_EDGE_SLACK_PX = 2
_MAX_MOMENTS_LISTED = 10


@dataclass(frozen=True, slots=True)
class _Strips:
    """Bar strips of a frame: (x0, x1) column ranges or (y0, y1) row ranges."""

    columns: tuple[tuple[int, int], ...]
    rows: tuple[tuple[int, int], ...]


class SubtitleBarsAuditor(BaseAuditor):
    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        items = [
            item
            for item in (self.ctx.extracted_items or [])
            if item.track.type == "subtitles" and item.rescale_picture is not None
        ]
        if not items:
            self.log("✅ No rescale added black bars; nothing to check.")
            return 0

        source1 = self.ctx.sources.get("Source 1")
        video = _video_stream(final_ffprobe_data)
        if not source1 or video is None:
            self._report("Black-bar checks skipped: Source 1 video not readable")
            return len(self.issues)

        width, height = int(video["width"]), int(video["height"])
        fonts = None
        for item in items:
            assert item.rescale_picture is not None
            name = item.custom_name or item.track.props.name or f"track {item.track.id}"
            label = f"'{name}' ({item.track.source})"
            picture = tuple(round(v) for v in item.rescale_picture)
            confirmed = self._check_bars(label, Path(source1), picture, width, height)
            if not confirmed:
                continue
            if fonts is None:
                fonts = self._extract_fonts(final_mkv_path, final_mkvmerge_data)
            self._check_overflow(label, item, picture, width, height, video, fonts)
        return len(self.issues)

    # ------------------------------------------------------------------
    # 1. Are the bars there?
    # ------------------------------------------------------------------

    def _check_bars(
        self,
        label: str,
        source1: Path,
        picture: tuple[int, ...],
        width: int,
        height: int,
    ) -> bool:
        x0, y0, x1, y1 = picture
        col_max = np.zeros(width, np.uint8)
        row_max = np.zeros(height, np.uint8)
        frames = 0
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error", "-skip_frame", "nokey",
            "-i", str(source1), "-map", "0:v:0", "-fps_mode", "passthrough",
            "-vf", "format=gray", "-f", "rawvideo", "-",
        ]  # fmt: skip
        try:
            for frame in _frames(
                self.runner.stream_binary(cmd, self.tool_paths), width * height
            ):
                img = np.frombuffer(frame, np.uint8).reshape(height, width)
                np.maximum(col_max, img.max(axis=0), out=col_max)
                np.maximum(row_max, img.max(axis=1), out=row_max)
                frames += 1
        except RuntimeError as e:
            self._report(
                f"{label}: could not read Source 1 to check its black bars: {e}"
            )
            return False
        if frames == 0:
            self._report(f"{label}: no Source 1 frames decoded; black bars not checked")
            return False

        bright_cols = np.nonzero(col_max > _BLACK_LUMA)[0]
        bright_rows = np.nonzero(row_max > _BLACK_LUMA)[0]
        if not len(bright_cols) or not len(bright_rows):
            self._report(
                f"{label}: Source 1 looked black in all {frames} keyframes; bars not checked"
            )
            return False
        mx0, mx1 = int(bright_cols[0]), int(bright_cols[-1]) + 1
        my0, my1 = int(bright_rows[0]), int(bright_rows[-1]) + 1
        measured = f"x {mx0}-{mx1}, y {my0}-{my1}"
        expected = f"x {x0}-{x1}, y {y0}-{y1}"
        self.log(
            f"  {label}: Source 1 picture measured {measured} over {frames} "
            f"keyframes; the rescale placed it at {expected}"
        )
        edges = (mx0 - x0, my0 - y0, mx1 - x1, my1 - y1)
        if all(abs(d) <= _EDGE_SLACK_PX for d in edges):
            self.log(f"  ✓ {label}: Source 1 has black bars where the rescale put them")
            return True
        if (
            mx0 < x0 - _EDGE_SLACK_PX
            or mx1 > x1 + _EDGE_SLACK_PX
            or (my0 < y0 - _EDGE_SLACK_PX or my1 > y1 + _EDGE_SLACK_PX)
        ):
            self._report(
                f"{label}: Source 1 has picture where the rescale put black bars "
                f"(picture {measured}, rescale assumed {expected}). The two "
                "releases frame the picture differently (crop / pan-and-scan), "
                "so sign positions will be off - check this track."
            )
        else:
            self._report(
                f"{label}: Source 1's picture is smaller than the rescale assumed "
                f"(picture {measured}, rescale assumed {expected}); its bars are "
                "wider, so sign positions will be off - check this track."
            )
        return False

    # ------------------------------------------------------------------
    # 2. Does anything land in the bars?
    # ------------------------------------------------------------------

    def _check_overflow(
        self,
        label: str,
        item: PlanItem,
        picture: tuple[int, ...],
        width: int,
        height: int,
        video: dict,
        fonts: Path | None,
    ) -> None:
        if item.extracted_path is None or item.extracted_path.suffix.lower() not in (
            ".ass",
            ".ssa",
        ):
            return
        work = self.ctx.temp_dir / "bars_check"
        work.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.extracted_path, work / "subs.ass")

        x0, y0, x1, y1 = picture
        strips = _bar_strips(x0, y0, x1, y1, width, height)
        rate = _rate(video)
        duration = float(video.get("duration") or 0) or self._format_duration()
        if rate is None or not duration:
            self._report(
                f"{label}: frame rate / duration unknown; bar overflow not checked"
            )
            return

        # Bars sit on one axis: two side strips (stacked side by side) or
        # two top/bottom strips (stacked vertically).
        if strips.columns:
            crops = [f"crop={b - a}:{height}:{a}:0" for a, b in strips.columns]
            stack, strip_px = "hstack", sum((b - a) * height for a, b in strips.columns)
        else:
            crops = [f"crop={width}:{b - a}:0:{a}" for a, b in strips.rows]
            stack, strip_px = "vstack", sum((b - a) * width for a, b in strips.rows)
        fonts_opt = f":fontsdir={fonts.name}" if fonts else ""
        head = f"[0]ass=subs.ass{fonts_opt},format=gray"
        if len(crops) == 1:
            graph = f"{head},{crops[0]}[out]"
        else:
            graph = (
                f"{head},split=2[a][b];[a]{crops[0]}[p];[b]{crops[1]}[q];"
                f"[p][q]{stack}=inputs=2[out]"
            )
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
            "-i", f"color=black:s={width}x{height}:r={rate}:d={duration:.3f}",
            "-filter_complex", graph, "-map", "[out]",
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ]  # fmt: skip
        hits: list[int] = []
        try:
            frames = _frames(
                self.runner.stream_binary(cmd, self.tool_paths, cwd=work), strip_px
            )
            for idx, frame in enumerate(frames):
                if any(frame):
                    hits.append(idx)
        except RuntimeError as e:
            self._report(f"{label}: could not render subtitles to check the bars: {e}")
            return

        if not hits:
            self.log(f"  ✓ {label}: no subtitle pixels land in the black bars")
            return
        fps = float(Fraction(rate))
        moments = _runs(hits)
        listed = ", ".join(
            f"{_ts(a / fps)}-{_ts((b + 1) / fps)}"
            for a, b in moments[:_MAX_MOMENTS_LISTED]
        )
        more = (
            f" (+{len(moments) - _MAX_MOMENTS_LISTED} more)"
            if len(moments) > _MAX_MOMENTS_LISTED
            else ""
        )
        self._report(
            f"{label}: subtitles land in Source 1's black bars in {len(hits)} "
            f"frame(s), {len(moments)} moment(s): {listed}{more}. These are "
            "signs that ran past the subtitle source's frame edge, which hid "
            "them; on Source 1 the bars show them."
        )

    # ------------------------------------------------------------------

    def _extract_fonts(self, mkv: Path, mkvmerge_data: dict) -> Path | None:
        """The output's attached fonts, for libass (the player gets the same)."""
        atts = mkvmerge_data.get("attachments", [])
        if not atts:
            return None
        out = self.ctx.temp_dir / "bars_check" / "fonts"
        out.mkdir(parents=True, exist_ok=True)
        specs = [
            f"{a['id']}:{out / Path(a.get('file_name') or str(a['id'])).name}"
            for a in atts
        ]
        self.runner.run(
            ["mkvextract", str(mkv), "attachments", *specs], self.tool_paths
        )
        return out

    def _format_duration(self) -> float:
        data = self._get_metadata(str(self.ctx.sources.get("Source 1", "")), "ffprobe")
        try:
            return float((data or {}).get("format", {}).get("duration") or 0)
        except (TypeError, ValueError):
            return 0.0


def _video_stream(ffprobe_data: dict | None) -> dict | None:
    for s in (ffprobe_data or {}).get("streams", []):
        if s.get("codec_type") == "video" and s.get("width") and s.get("height"):
            return s
    return None


def _rate(video: dict) -> str | None:
    for key in ("r_frame_rate", "avg_frame_rate"):
        value = str(video.get(key) or "")
        num, _, den = value.partition("/")
        if num.isdigit() and den.isdigit() and int(num) > 0 and int(den) > 0:
            return f"{int(num)}/{int(den)}"
    return None


def _bar_strips(x0: int, y0: int, x1: int, y1: int, width: int, height: int) -> _Strips:
    cols = tuple(r for r in ((0, x0), (x1, width)) if r[1] > r[0])
    rows = tuple(r for r in ((0, y0), (y1, height)) if r[1] > r[0])
    return _Strips(columns=cols, rows=rows)


def _frames(chunks, size: int):
    """Re-cut a byte stream into whole frames of ``size`` bytes."""
    buf = bytearray()
    for chunk in chunks:
        buf += chunk
        while len(buf) >= size:
            yield bytes(buf[:size])
            del buf[:size]


def _runs(indices: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for i in indices:
        if runs and i == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def _ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:05.2f}"


__all__ = ["SubtitleBarsAuditor"]
