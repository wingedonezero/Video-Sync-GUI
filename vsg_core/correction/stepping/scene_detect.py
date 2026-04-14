# vsg_core/correction/stepping/scene_detect.py
"""
Video scene detection for stepping correction boundary refinement.

Opens Source 2 video via VapourSynth + FFMS2 and compares adjacent
frame Y histograms to find scene cuts and black-frame zones.

**Gate:** Only runs on progressive H.264/H.265 content.  MPEG-2 and
interlaced video is skipped with a log warning (deinterlace support
requires additional testing — future enhancement).  When skipped, the
boundary refiner falls back to audio-only analysis.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import numpy as np

from .types import BlackZone, SceneCut, SceneDetectResult

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Content gate
# ---------------------------------------------------------------------------

# Codecs that are safe for raw frame comparison (progressive only)
_PROGRESSIVE_CODECS = frozenset({"h264", "hevc", "h265", "av1", "vp9"})

# Codecs that need deinterlace (gated off for now)
_INTERLACED_CODECS = frozenset({"mpeg2video", "mpeg1video"})


def _probe_video_stream(
    video_path: str,
    runner: object | None = None,
) -> dict[str, str]:
    """Return codec_name and field_order for the first video stream."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,field_order",
        "-of",
        "json",
        video_path,
    ]
    try:
        if runner is not None and hasattr(runner, "run"):
            out = runner.run(cmd, {})  # type: ignore[arg-type]
            if out:
                data = json.loads(out)
            else:
                return {}
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

        streams = data.get("streams", [])
        if streams:
            return {
                "codec_name": streams[0].get("codec_name", "unknown"),
                "field_order": streams[0].get("field_order", "unknown"),
            }
    except Exception:
        pass
    return {}


def can_detect_scenes(video_path: str, runner: object | None = None) -> bool:
    """Return True if *video_path* is suitable for video scene detection.

    Currently only progressive H.264 / H.265 / AV1 / VP9 content passes.
    MPEG-2 and interlaced content is gated off until deinterlace support
    is properly tested.
    """
    props = _probe_video_stream(video_path, runner)
    codec = props.get("codec_name", "unknown")
    field_order = props.get("field_order", "unknown")

    if codec in _INTERLACED_CODECS:
        return False
    if field_order not in ("progressive", "unknown"):
        return False
    return codec in _PROGRESSIVE_CODECS


# ---------------------------------------------------------------------------
# Scene detection
# ---------------------------------------------------------------------------


def detect_scenes(
    video_path: str,
    scan_start_s: float,
    scan_end_s: float,
    log: Callable[[str], None] | None = None,
    cut_threshold: float = 0.15,
    black_threshold: float = 20.0,
) -> SceneDetectResult:
    """Detect scene cuts and black-frame zones via VapourSynth.

    Parameters
    ----------
    video_path:
        Path to the video file (Source 2).
    scan_start_s, scan_end_s:
        Time range to scan (seconds, Source 2 timeline).
    log:
        Logging callable.
    cut_threshold:
        Minimum histogram difference (0–1) for a scene cut.
    black_threshold:
        Maximum mean Y value to classify a frame as black.

    Returns
    -------
    SceneDetectResult
        Contains scene cuts and black-frame zones found in the range.
    """
    try:
        import vapoursynth as vs
    except ImportError:
        if log:
            log("[Scene Detect] VapourSynth not available — skipping video")
        return SceneDetectResult(cuts=[], black_zones=[])

    core = vs.core

    try:
        clip = core.ffms2.Source(source=video_path, threads=1)
    except Exception as exc:
        if log:
            log(f"[Scene Detect] Failed to open video: {exc}")
        return SceneDetectResult(cuts=[], black_zones=[])

    if clip.format is not None and clip.format.color_family != vs.YUV:
        clip = core.resize.Bicubic(clip, format=vs.YUV420P8, matrix_s="709")
    elif clip.format is None:
        # Unknown format — try converting anyway
        try:
            clip = core.resize.Bicubic(
                clip, format=vs.YUV420P8, matrix_s="709"
            )
        except Exception:
            if log:
                log("[Scene Detect] Cannot convert clip format — skipping")
            return SceneDetectResult(cuts=[], black_zones=[])

    fps = clip.fps.numerator / clip.fps.denominator
    if fps <= 0:
        if log:
            log("[Scene Detect] Invalid FPS — skipping")
        return SceneDetectResult(cuts=[], black_zones=[])

    start_frame = max(1, int(scan_start_s * fps))
    end_frame = min(int(scan_end_s * fps), clip.num_frames - 1)

    cuts: list[SceneCut] = []
    black_zones: list[BlackZone] = []
    in_black = False
    black_start_frame = 0
    prev_hist: np.ndarray | None = None

    for fn in range(start_frame, end_frame):
        try:
            frame = clip.get_frame(fn)
        except Exception:
            continue

        y = np.asarray(frame[0])
        hist = np.histogram(y, bins=256, range=(0, 256))[0].astype(np.float64)
        mean = float(y.mean())

        # Scene cut detection: histogram difference
        if prev_hist is not None:
            total = np.sum(hist) + np.sum(prev_hist)
            if total > 0:
                diff = float(np.sum(np.abs(hist - prev_hist))) / total
            else:
                diff = 0.0

            if diff > cut_threshold:
                cut_type = "BLACK" if mean < black_threshold else "HARD_CUT"
                cuts.append(
                    SceneCut(
                        time_s=fn / fps,
                        frame=fn,
                        diff=diff,
                        mean=mean,
                        cut_type=cut_type,
                    )
                )

        # Black frame tracking
        if mean < black_threshold and not in_black:
            black_start_frame = fn
            in_black = True
        elif mean >= black_threshold and in_black:
            dur_ms = (fn - black_start_frame) / fps * 1000
            if dur_ms > 10:  # Ignore single-frame flickers
                black_zones.append(
                    BlackZone(
                        start_s=black_start_frame / fps,
                        end_s=fn / fps,
                        dur_ms=dur_ms,
                    )
                )
            in_black = False

        prev_hist = hist

    # Close trailing black zone
    if in_black:
        dur_ms = (end_frame - black_start_frame) / fps * 1000
        if dur_ms > 10:
            black_zones.append(
                BlackZone(
                    start_s=black_start_frame / fps,
                    end_s=end_frame / fps,
                    dur_ms=dur_ms,
                )
            )

    return SceneDetectResult(cuts=cuts, black_zones=black_zones)
