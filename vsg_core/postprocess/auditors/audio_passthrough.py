# vsg_core/postprocess/auditors/audio_passthrough.py
"""Checks the tracks the app cut in their own codec, on the final MKV's blocks.

For every passthrough track the muxed frames must be exactly the file the app
wrote, in order: same count (byte codecs: one block frame per unit), every
frame byte-identical (adler32 over the same bytes of the cut file), the first
frame at exactly the residual ``--sync``, a TrueHD start flagged as a key
frame, and every frame within half a ms of its exact time. This is
packet-level on purpose: a strict decode passes every bad start this exists
to catch (TrueHD off a major sync, a DTS ramp-in).
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

from vsg_core.audio_processing.frames import parse_file
from vsg_core.audio_processing.ogg_opus import read_ogg_opus
from vsg_core.audio_processing.passthrough import frame_family, read_wav_layout
from vsg_core.orchestrator.steps.audio_processing_step import item_label

from .base import BaseAuditor

if TYPE_CHECKING:
    from pathlib import Path

    from vsg_core.audio_processing.passthrough import PassthroughCut
    from vsg_core.models.jobs import PlanItem

_FRAME_LINE = re.compile(
    r"^(?P<kind>\w) frame, track (?P<track>\d+), timestamp (?P<h>\d+):(?P<m>\d+):"
    r"(?P<s>\d+)\.(?P<ns>\d{9})(?:, duration [^,]+)?, size (?P<size>\d+), "
    r"adler 0x(?P<adler>[0-9a-f]+)"
)
_NS = 1_000_000_000
_HALF_MS_NS = 500_000


@dataclass(frozen=True, slots=True)
class _Frame:
    ts_ns: int
    size: int
    adler: int
    key: bool


class AudioPassthroughAuditor(BaseAuditor):
    """Verifies passthrough cuts frame by frame against the muxed file."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        for entry in self.ctx.passthrough_cut_failures:
            self._report(f"Not cut by the app (mkvmerge --sync as before): {entry}")
        for entry in self.ctx.passthrough_warnings:
            self._report(entry)

        results = {
            r.label: r
            for r in self.ctx.audio_processing_results
            if r.route == "passthrough" and r.ok and r.cut is not None
        }
        if not results:
            self.log("No tracks were cut in their codec.")
            return len(self.issues)

        audio_items = [
            item
            for item in (self.ctx.extracted_items or [])
            if item.track.type == "audio"
        ]
        audio_tracks = [
            t for t in final_mkvmerge_data.get("tracks", []) if t.get("type") == "audio"
        ]
        if len(audio_items) != len(audio_tracks):
            self._report(
                f"Audio track count mismatch ({len(audio_items)} planned, "
                f"{len(audio_tracks)} in the file); passthrough check skipped"
            )
            return len(self.issues)

        frames_by_track = self._read_frames(final_mkv_path)
        for item, track in zip(audio_items, audio_tracks, strict=True):
            result = results.get(item_label(item))
            if result is None or result.cut is None:
                continue
            number = int((track.get("properties") or {}).get("number") or 0)
            self._check_track(item, result.cut, frames_by_track.get(number, []))

        if not self.issues:
            self.log("✅ Every passthrough cut is in the file exactly as written.")
        return len(self.issues)

    def _read_frames(self, mkv: Path) -> dict[int, list[_Frame]]:
        out = self.runner.run(["mkvinfo", "-s", str(mkv)], self.tool_paths)
        frames: dict[int, list[_Frame]] = {}
        for line in (out if isinstance(out, str) else "").splitlines():
            m = _FRAME_LINE.match(line.strip())
            if not m:
                continue
            ts = (int(m["h"]) * 3600 + int(m["m"]) * 60 + int(m["s"])) * _NS + int(
                m["ns"]
            )
            frames.setdefault(int(m["track"]), []).append(
                _Frame(ts, int(m["size"]), int(m["adler"], 16), m["kind"] == "I")
            )
        return frames

    def _check_track(
        self, item: PlanItem, cut: PassthroughCut, frames: list[_Frame]
    ) -> None:
        name = (
            f"{item.track.props.name or f'Track {item.track.id}'} ({item.track.source})"
        )
        path = item.extracted_path
        if path is None or not path.exists():
            self.log(f"  ⓘ {name}: muxed file no longer on disk; check skipped")
            return
        if not frames:
            self._report(f"{name}: no frames found in the final file")
            return

        problems = self._compare_bytes(path, cut, frames)
        if frames[0].ts_ns != cut.sync_ms * 1_000_000:
            problems.append(
                f"first frame at {frames[0].ts_ns / 1e6:.3f} ms, expected {cut.sync_ms} ms"
            )
        if cut.kind == "truehd" and not frames[0].key:
            problems.append("first TrueHD access unit is not flagged as a key frame")
        if cut.kind not in ("pcm", "opus"):
            problems += self._check_times(path, cut, frames)

        if problems:
            for p in problems:
                self._report(f"{name}: {p}")
        else:
            self.log(
                f"  ✓ {name}: {len(frames)} frames identical to the cut file, first at "
                f"{cut.sync_ms} ms, times exact to the ms"
            )

    def _compare_bytes(
        self, path: Path, cut: PassthroughCut, frames: list[_Frame]
    ) -> list[str]:
        """Slice the muxed source file by the frames' sizes; every adler must match."""
        if cut.kind == "opus":
            packets = read_ogg_opus(path).packets
            if len(packets) != len(frames):
                return [
                    f"{len(frames)} frames in the file, {len(packets)} Opus packets written"
                ]
            for i, (p, f) in enumerate(zip(packets, frames, strict=True)):
                if len(p) != f.size or (zlib.adler32(p) & 0xFFFFFFFF) != f.adler:
                    return [f"frame {i} differs from the written Opus packet"]
            return []
        if cut.kind == "pcm":
            layout = read_wav_layout(path)
            start, total = layout.data_offset, layout.data_bytes
        else:
            fmap = parse_file(frame_family(cut.kind), path)
            if len(fmap) != len(frames):
                return [f"{len(frames)} frames in the file, {len(fmap)} units written"]
            if any(fmap.size[i] != f.size for i, f in enumerate(frames)):
                return ["frame sizes differ from the written units"]
            start, total = 0, fmap.end
        if sum(f.size for f in frames) != total:
            return ["the frames do not add up to the written file"]
        with path.open("rb") as fh:
            fh.seek(start)
            for i, f in enumerate(frames):
                if (zlib.adler32(fh.read(f.size)) & 0xFFFFFFFF) != f.adler:
                    return [f"frame {i} is not byte-identical to the written file"]
        return []

    @staticmethod
    def _check_times(
        path: Path, cut: PassthroughCut, frames: list[_Frame]
    ) -> list[str]:
        """Frames sharing a stored time form a lace (or share a ms); the first
        frame of each run must be within half a ms of its exact time."""
        fmap = parse_file(frame_family(cut.kind), path)
        base = Fraction(cut.sync_ms, 1000)
        offset = 0
        prev_ts: int | None = None
        for i, f in enumerate(frames):
            if f.ts_ns != prev_ts:
                exact_ns = (base + Fraction(offset, fmap.rate)) * _NS
                if abs(f.ts_ns - exact_ns) > _HALF_MS_NS:
                    return [
                        f"frame {i} stored at {f.ts_ns / 1e6:.3f} ms, exact time "
                        f"{float(exact_ns) / 1e6:.3f} ms"
                    ]
                prev_ts = f.ts_ns
            offset += fmap.samples[i]
        return []
