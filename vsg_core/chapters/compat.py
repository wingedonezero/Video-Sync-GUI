# vsg_core/chapters/compat.py
"""
Chapter donor compatibility probe.

Determines whether a non-Source-1 source can safely donate chapters to
Source 1 in the final mux. The gate is intentionally tight for v1: both
sides must be modern progressive video at matching frame rates. This is
the case where a single integer-ms time offset (from audio correlation)
lands chapters exactly on the right scenes.

Anything more exotic (MPEG-2 / DVD, interlaced, telecine, FPS mismatch)
falls back to Source 1's own chapters with a warning. Detecting those
cases reliably needs the L1/L2/L3 classifier subsystem and is out of
scope here — dropping back to Source 1 is the safe default.

Results are cached per absolute path so the manual selection dialog
and the runtime ChaptersStep don't probe the same file twice.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Codecs that DVD-Video can carry. We treat both as MPEG-2-class for the
# purpose of this gate.
_MPEG2_CODECS = frozenset({"mpeg2video", "mpeg1video"})

# Cache keyed by absolute path string. Probe results don't change while
# the app is running; safe to memoize for the process lifetime.
@dataclass(frozen=True, slots=True)
class ChapterProbe:
    """Minimal video properties needed for the donor compatibility gate."""

    codec_name: str
    fps_num: int
    fps_den: int
    field_order: str  # "progressive", "tt", "tb", "bb", "bt", "unknown"
    width: int
    height: int
    ok: bool  # False = ffprobe failed; treat as incompatible

    @property
    def is_mpeg2(self) -> bool:
        return self.codec_name in _MPEG2_CODECS

    @property
    def is_progressive(self) -> bool:
        return self.field_order == "progressive"

    @property
    def is_dvd_resolution(self) -> bool:
        # Standard NTSC/PAL DVD resolutions paired with MPEG-class codec
        if not self.is_mpeg2:
            return False
        if self.width not in (720, 704):
            return False
        return self.height in (480, 486, 576, 578)


# Cache keyed by absolute path string. Probe results don't change while
# the app is running; safe to memoize for the process lifetime.
_PROBE_CACHE: dict[str, ChapterProbe] = {}


def quick_probe(path: str) -> ChapterProbe:
    """
    Fast ffprobe call returning just the fields needed for the gate.

    Cached per path. ~50ms cold, instant warm. Returns ok=False on probe
    failure — the caller treats that as incompatible.
    """
    abs_path = str(Path(path).resolve())
    cached = _PROBE_CACHE.get(abs_path)
    if cached is not None:
        return cached

    probe = _run_ffprobe(abs_path)
    _PROBE_CACHE[abs_path] = probe
    return probe


def _run_ffprobe(path: str) -> ChapterProbe:
    fail = ChapterProbe(
        codec_name="",
        fps_num=0,
        fps_den=1,
        field_order="unknown",
        width=0,
        height=0,
        ok=False,
    )

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,r_frame_rate,field_order,width,height",
        "-of",
        "json",
        path,
    ]

    try:
        # GPU env wrapper lives in vsg_core.system.gpu_env; not strictly
        # required for ffprobe but matches the rest of the codebase.
        try:
            from vsg_core.system.gpu_env import get_subprocess_environment

            env = get_subprocess_environment()
        except ImportError:
            import os

            env = os.environ.copy()

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, env=env
        )
        if result.returncode != 0:
            return fail

        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return fail
        s = streams[0]

        codec = str(s.get("codec_name") or "")
        rfr = str(s.get("r_frame_rate") or "0/1")
        if "/" in rfr:
            num_s, den_s = rfr.split("/", 1)
            try:
                num = int(num_s)
                den = int(den_s) or 1
            except ValueError:
                num, den = 0, 1
        else:
            try:
                num = int(round(float(rfr) * 1000))
                den = 1000
            except ValueError:
                num, den = 0, 1

        field_order = str(s.get("field_order") or "unknown").lower()
        width = int(s.get("width") or 0)
        height = int(s.get("height") or 0)

        return ChapterProbe(
            codec_name=codec,
            fps_num=num,
            fps_den=den,
            field_order=field_order,
            width=width,
            height=height,
            ok=True,
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return fail


def is_donor_compatible(
    source1: ChapterProbe, donor: ChapterProbe
) -> tuple[bool, str | None]:
    """
    Check whether `donor` can safely contribute chapters to `source1`.

    Returns (True, None) on pass, (False, reason) on fail. Reasons are
    short user-facing strings suitable for tooltips and log lines.
    """
    if not source1.ok:
        return False, "Source 1 video probe failed"
    if not donor.ok:
        return False, "donor video probe failed"

    if donor.is_mpeg2 or donor.is_dvd_resolution:
        return False, "donor is MPEG-2/DVD"
    if source1.is_mpeg2 or source1.is_dvd_resolution:
        return False, "Source 1 is MPEG-2/DVD"

    if not donor.is_progressive:
        return False, f"donor is {donor.field_order} (not progressive)"
    if not source1.is_progressive:
        return False, f"Source 1 is {source1.field_order} (not progressive)"

    if (source1.fps_num, source1.fps_den) != (donor.fps_num, donor.fps_den):
        s1_fps = source1.fps_num / source1.fps_den if source1.fps_den else 0
        dn_fps = donor.fps_num / donor.fps_den if donor.fps_den else 0
        return False, f"fps mismatch ({s1_fps:.3f} vs {dn_fps:.3f})"

    return True, None


def clear_cache() -> None:
    """Drop cached probes. Used by tests; not called from production."""
    _PROBE_CACHE.clear()
