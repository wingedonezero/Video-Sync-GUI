# vsg_core/postprocess/auditors/audio_passthrough.py
"""Checks the tracks the app cut in their own codec, against the final MKV.

mkvextract writes every passthrough track back out of the final file, with
each frame's time (``timestamps_v2``, laced frames included). The extracted
track must be exactly the file the app wrote (byte for byte; AAC payloads,
since mkvextract rebuilds the ADTS headers), the first frame must sit at
exactly the residual ``--sync``, and every frame of a byte-cut codec within
half a ms of its exact time. This is packet-level on purpose: a strict
decode passes every bad start this exists to catch (TrueHD off a major sync,
a DTS ramp-in). One mkvextract pass reads the file once, about 45 s for a
47 GB UHD, and keeps nothing large in memory.
"""

from __future__ import annotations

import hashlib
import shutil
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

_HALF_MS = Fraction(1, 2)
_CHUNK = 8 * 1024 * 1024


def _sha256(path: Path, start: int = 0, length: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        f.seek(start)
        left = length
        while left is None or left > 0:
            chunk = f.read(_CHUNK if left is None else min(_CHUNK, left))
            if not chunk:
                break
            h.update(chunk)
            if left is not None:
                left -= len(chunk)
    return h.hexdigest()


def _aac_payload_hash(path: Path) -> tuple[int, str]:
    """(frame count, hash of the payloads without their ADTS headers)."""
    fmap = parse_file("aac", path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        for i in range(len(fmap)):
            f.seek(fmap.pos[i])
            frame = f.read(fmap.size[i])
            h.update(frame[7 if frame[1] & 1 else 9 :])
    return len(fmap), h.hexdigest()


def _read_times(path: Path) -> list[Fraction]:
    """Frame start times in ms from a timestamps_v2 file (the last line is the
    end of the last frame and is dropped)."""
    times = [
        Fraction(line.strip())
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return times[:-1]


class AudioPassthroughAuditor(BaseAuditor):
    """Verifies passthrough cuts against the tracks extracted from the final MKV."""

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

        jobs: list[tuple[PlanItem, PassthroughCut, int]] = []
        for item, track in zip(audio_items, audio_tracks, strict=True):
            result = results.get(item_label(item))
            if result is not None and result.cut is not None:
                jobs.append((item, result.cut, int(track.get("id", -1))))
        if not jobs:
            return len(self.issues)

        work = self.ctx.temp_dir / "passthrough_audit"
        work.mkdir(parents=True, exist_ok=True)
        try:
            cmd = ["mkvextract", str(final_mkv_path), "tracks"]
            cmd += [f"{tid}:{work / f'{tid}.track'}" for _, _, tid in jobs]
            cmd += ["timestamps_v2"]
            cmd += [f"{tid}:{work / f'{tid}.times'}" for _, _, tid in jobs]
            self.runner.run(cmd, self.tool_paths)
            for item, cut, tid in jobs:
                self._check_track(
                    item, cut, work / f"{tid}.track", work / f"{tid}.times"
                )
        finally:
            shutil.rmtree(work, ignore_errors=True)

        if not self.issues:
            self.log("✅ Every passthrough cut is in the file exactly as written.")
        return len(self.issues)

    def _check_track(
        self, item: PlanItem, cut: PassthroughCut, extracted: Path, times_path: Path
    ) -> None:
        name = (
            f"{item.track.props.name or f'Track {item.track.id}'} ({item.track.source})"
        )
        written = item.extracted_path
        if written is None or not written.exists():
            self.log(f"  ⓘ {name}: muxed file no longer on disk; check skipped")
            return
        if not extracted.exists() or not times_path.exists():
            self._report(f"{name}: could not extract it from the final file")
            return

        times = _read_times(times_path)
        problems = self._compare(cut, written, extracted, len(times))
        if not times or times[0] != cut.sync_ms:
            first = f"{float(times[0]):.3f} ms" if times else "nothing"
            problems.append(f"first frame at {first}, expected {cut.sync_ms} ms")
        elif cut.kind not in ("pcm", "opus"):
            problems += self._check_times(cut, written, times)

        if problems:
            for p in problems:
                self._report(f"{name}: {p}")
        else:
            self.log(
                f"  ✓ {name}: {len(times)} frames identical to the cut file, first at "
                f"{cut.sync_ms} ms, every frame within half a ms of its exact time"
            )

    @staticmethod
    def _compare(
        cut: PassthroughCut, written: Path, extracted: Path, frames: int
    ) -> list[str]:
        """The extracted track must be what the app wrote."""
        if cut.kind == "opus":
            ours, theirs = read_ogg_opus(written), read_ogg_opus(extracted)
            if ours.packets != theirs.packets:
                return ["Opus packets differ from the written file"]
            return []
        if cut.kind == "pcm":
            a, b = read_wav_layout(written), read_wav_layout(extracted)
            if a.data_bytes != b.data_bytes or _sha256(
                written, a.data_offset, a.data_bytes
            ) != _sha256(extracted, b.data_offset, b.data_bytes):
                return ["PCM samples differ from the written file"]
            return []
        if cut.kind == "aac":
            if _aac_payload_hash(written) != _aac_payload_hash(extracted):
                return ["AAC frames differ from the written file"]
            return []
        if _sha256(written) != _sha256(extracted):
            return ["the track is not byte-identical to the written file"]
        units = len(parse_file(frame_family(cut.kind), written))
        if units != frames:
            return [f"{frames} frames in the file, {units} units written"]
        return []

    @staticmethod
    def _check_times(
        cut: PassthroughCut, written: Path, times: list[Fraction]
    ) -> list[str]:
        fmap = parse_file(frame_family(cut.kind), written)
        offset = 0
        for i, t in enumerate(times):
            exact = cut.sync_ms + Fraction(offset * 1000, fmap.rate)
            if abs(t - exact) > _HALF_MS:
                return [
                    f"frame {i} at {float(t):.3f} ms, exact time {float(exact):.3f} ms"
                ]
            offset += fmap.samples[i]
        return []
