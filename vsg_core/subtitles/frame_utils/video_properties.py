# vsg_core/subtitles/frame_utils/video_properties.py
"""
Video property detection functions for subtitle synchronization.

Contains:
- FPS detection (ffprobe)
- MediaInfo-based detection (MPEG-2 picture header analysis)
- Multi-source cross-validated video property detection
- Video property comparison for sync strategy selection
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "compare_video_properties",
    "detect_video_fps",
    "detect_video_properties",
    "get_video_duration_ms",
    "get_video_properties",
]


def _detect_mediainfo_properties(video_path: str, runner) -> dict[str, Any]:
    """
    Detect video properties using MediaInfo.

    MediaInfo reads MPEG-2 picture coding extension headers (progressive_frame,
    repeat_first_field) to determine scan type and pulldown patterns.  This is
    the same data DGIndex analyses, but MediaInfo does it as a fast metadata
    scan rather than a full decode.

    Returns a dict with the fields MediaInfo could determine, or an empty dict
    if mediainfo is not installed / fails.

    Keys that may be present:
        mi_fps          – float frame rate
        mi_fps_mode     – "CFR" | "VFR"
        mi_scan_type    – "Progressive" | "Interlaced" | "MBAFF" | ...
        mi_scan_order   – "TFF" | "BFF" | "2:3 Pulldown" | ...
        mi_original_fps – float (FrameRate_Original, set for soft-TC)
        mi_codec        – e.g. "MPEG Video" | "AVC" | "HEVC"
    """
    if not shutil.which("mediainfo"):
        if runner:
            runner._log_message("[MediaInfo] mediainfo not found – skipping")
        return {}

    try:
        from vsg_core.system.gpu_env import get_subprocess_environment
        env = get_subprocess_environment()
    except ImportError:
        import os
        env = os.environ.copy()

    inform = (
        "Video;"
        "mi_fps=%FrameRate%\\n"
        "mi_fps_mode=%FrameRate_Mode%\\n"
        "mi_scan_type=%ScanType%\\n"
        "mi_scan_order=%ScanOrder%\\n"
        "mi_original_fps=%FrameRate_Original%\\n"
        "mi_codec=%Format%\\n"
    )

    cmd = ["mediainfo", f"--Inform={inform}", str(video_path)]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, env=env,
        )
        if result.returncode != 0:
            if runner:
                runner._log_message("[MediaInfo] WARNING: mediainfo returned non-zero")
            return {}

        props: dict[str, Any] = {}
        for line in result.stdout.strip().splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not value:
                continue
            if key in ("mi_fps", "mi_original_fps"):
                try:
                    props[key] = float(value)
                except ValueError:
                    pass
            else:
                props[key] = value

        return props

    except Exception as exc:
        if runner:
            runner._log_message(f"[MediaInfo] WARNING: detection failed: {exc}")
        return {}


def _classify_content_type(
    ffprobe_props: dict[str, Any],
    mi_props: dict[str, Any],
    runner,
) -> tuple[str, str]:
    """
    Classify content type by cross-validating ffprobe and MediaInfo results.

    Uses a decision tree based on multiple signals:
    - Codec (MPEG-2 = DVD source)
    - MediaInfo fps_mode (CFR vs VFR – reads MPEG-2 repeat_first_field flags)
    - MediaInfo scan_order (TFF/BFF vs 2:3 Pulldown)
    - ffprobe field_order (tt/bb/progressive)

    Returns:
        (content_type, confidence)

        content_type is one of:
            "progressive"    – Normal progressive content (CFR path)
            "interlaced"     – Pure interlaced 29.970 CFR
            "soft_telecine"  – Soft telecine (VFR container, 2:3 pulldown removed)
            "unknown"        – Could not determine with confidence

        confidence is one of:
            "high"    – ffprobe and MediaInfo agree
            "medium"  – Only one source available or minor disagreement
            "low"     – Conflicting signals
    """
    def log(msg: str):
        if runner:
            runner._log_message(msg)

    codec = ffprobe_props.get("codec_name", "")
    is_mpeg2 = codec in ("mpeg2video", "mpeg1video")
    is_dvd = ffprobe_props.get("is_dvd", False)

    # ffprobe signals
    fp_interlaced = ffprobe_props.get("interlaced", False)
    fp_field_order = ffprobe_props.get("field_order", "unknown")
    fp_fps = ffprobe_props.get("fps", 0.0)
    fp_is_vfr = ffprobe_props.get("is_vfr", False)

    # MediaInfo signals
    mi_fps_mode = mi_props.get("mi_fps_mode", "")
    mi_scan_type = mi_props.get("mi_scan_type", "")
    mi_scan_order = mi_props.get("mi_scan_order", "")
    mi_original_fps = mi_props.get("mi_original_fps")
    has_mediainfo = bool(mi_props)

    # ──────────────────────────────────────────────────────────────
    # 1. Non-MPEG2: progressive encode (the normal/current path)
    # ──────────────────────────────────────────────────────────────
    if not is_mpeg2:
        if fp_interlaced:
            # H.264 interlaced (rare for anime, but possible)
            log("[ContentType] Non-MPEG2 interlaced (H.264/HEVC interlaced encode)")
            return "interlaced", "medium"
        log("[ContentType] Progressive encode (non-MPEG2)")
        return "progressive", "high"

    # ──────────────────────────────────────────────────────────────
    # 2. MPEG-2 with MediaInfo available: use MPEG-2 flag analysis
    # ──────────────────────────────────────────────────────────────
    if has_mediainfo:
        is_mi_vfr = mi_fps_mode.upper() == "VFR"
        is_mi_pulldown = "pulldown" in mi_scan_order.lower()
        is_mi_interlaced = mi_scan_type.lower() == "interlaced"

        # Soft telecine: MediaInfo reads repeat_first_field flags,
        # sees variable pattern → reports VFR + 2:3 Pulldown
        if is_mi_vfr and is_mi_pulldown:
            # Cross-validate: ffprobe should also see VFR or progressive field_order
            if fp_is_vfr or fp_field_order == "progressive":
                confidence = "high"
            else:
                # MediaInfo says VFR pulldown but ffprobe says interlaced CFR
                # Trust MediaInfo – it reads deeper MPEG-2 flags
                confidence = "medium"
                log("[ContentType] NOTE: MediaInfo=VFR+Pulldown but ffprobe=interlaced – trusting MediaInfo")
            log(f"[ContentType] Soft telecine detected (MediaInfo: {mi_fps_mode}, {mi_scan_order})")
            return "soft_telecine", confidence

        if is_mi_vfr and not is_mi_pulldown:
            # VFR but not standard pulldown — unusual, treat as soft TC variant
            log(f"[ContentType] VFR MPEG-2 without standard pulldown (ScanOrder: {mi_scan_order})")
            return "soft_telecine", "medium"

        # Pure interlaced: MediaInfo says CFR + Interlaced
        if not is_mi_vfr and is_mi_interlaced:
            # Cross-validate with ffprobe
            if fp_interlaced:
                confidence = "high"
            else:
                confidence = "medium"
                log("[ContentType] NOTE: MediaInfo=Interlaced but ffprobe=progressive – trusting MediaInfo")
            log(f"[ContentType] Pure interlaced (MediaInfo: {mi_fps_mode}, {mi_scan_type})")
            return "interlaced", confidence

        # MediaInfo says CFR + Progressive MPEG-2 (unusual but possible)
        if not is_mi_vfr and not is_mi_interlaced:
            log(f"[ContentType] Progressive MPEG-2 (MediaInfo: {mi_fps_mode}, {mi_scan_type})")
            return "progressive", "medium"

    # ──────────────────────────────────────────────────────────────
    # 3. MPEG-2 without MediaInfo: ffprobe-only fallback
    # ──────────────────────────────────────────────────────────────
    log("[ContentType] WARNING: MediaInfo unavailable – using ffprobe only (less reliable for MPEG-2)")

    if fp_is_vfr:
        # ffprobe detected VFR from r_frame_rate vs avg_frame_rate difference
        log("[ContentType] Likely soft telecine (ffprobe VFR detected)")
        return "soft_telecine", "low"

    if fp_interlaced and is_dvd:
        # MPEG-2 DVD at 29.970 interlaced — could be pure interlaced OR hard telecine
        # Without MediaInfo we can't distinguish, but for sync both are 29.970 CFR
        log("[ContentType] MPEG-2 DVD interlaced (could be pure interlaced or hard telecine)")
        return "interlaced", "low"

    if fp_interlaced:
        return "interlaced", "low"

    return "unknown", "low"


def detect_video_fps(video_path: str, runner) -> float:
    """
    Detect frame rate from video file using ffprobe.

    Args:
        video_path: Path to video file
        runner: CommandRunner for executing ffprobe

    Returns:
        Frame rate as float (e.g., 23.976), or 23.976 as fallback
    """
    runner._log_message(f"[FPS Detection] Detecting FPS from: {Path(video_path).name}")

    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "json",
            str(video_path),
        ]

        # Import GPU environment support
        try:
            from vsg_core.system.gpu_env import get_subprocess_environment

            env = get_subprocess_environment()
        except ImportError:
            import os

            env = os.environ.copy()

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, env=env
        )

        if result.returncode != 0:
            runner._log_message(
                "[FPS Detection] WARNING: ffprobe failed, using default 23.976 fps"
            )
            return 23.976

        data = json.loads(result.stdout)
        r_frame_rate = data["streams"][0]["r_frame_rate"]

        # Parse fraction (e.g., "24000/1001" -> 23.976)
        if "/" in r_frame_rate:
            num, denom = r_frame_rate.split("/")
            fps = float(num) / float(denom)
        else:
            fps = float(r_frame_rate)

        runner._log_message(f"[FPS Detection] Detected FPS: {fps:.3f} ({r_frame_rate})")
        return fps

    except Exception as e:
        runner._log_message(f"[FPS Detection] WARNING: FPS detection failed: {e}")
        runner._log_message("[FPS Detection] Using default: 23.976 fps")
        return 23.976


def detect_video_properties(video_path: str, runner) -> dict[str, Any]:
    """
    Detect comprehensive video properties for sync strategy selection.

    Detects FPS, interlacing, field order, telecine, duration, frame count,
    and resolution (width/height).
    Used to determine if special handling is needed (deinterlace, scaling, etc.)

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        Dict with:
            - fps: float (e.g., 23.976)
            - fps_fraction: tuple (num, denom) e.g., (24000, 1001)
            - interlaced: bool
            - field_order: str ('progressive', 'tff', 'bff', 'unknown')
            - scan_type: str ('progressive', 'interlaced', 'telecine', 'unknown')
            - duration_ms: float
            - frame_count: int (estimated)
            - width: int (video width in pixels)
            - height: int (video height in pixels)
            - detection_source: str (what method was used)
    """
    runner._log_message(
        f"[VideoProps] Detecting properties for: {Path(video_path).name}"
    )

    # Default/fallback values
    props = {
        "fps": 23.976,
        "fps_fraction": (24000, 1001),
        "original_fps": None,  # Original frame rate for VFR soft-telecine content
        "original_fps_fraction": None,  # Original as fraction (num, denom)
        "is_vfr": False,  # True if variable frame rate detected
        "is_soft_telecine": False,  # True if VFR from soft-telecine removal
        "interlaced": False,
        "field_order": "progressive",
        "scan_type": "progressive",
        "content_type": "progressive",  # 'progressive', 'interlaced', 'telecine', 'unknown'
        "is_sd": False,  # True if SD content (height <= 576)
        "is_dvd": False,  # True if likely DVD content
        "duration_ms": 0.0,
        "frame_count": 0,
        "width": 1920,
        "height": 1080,
        "detection_source": "fallback",
    }

    try:
        # Use ffprobe to get comprehensive stream info
        # Note: We query both stream AND format for duration since MKV often
        # only has duration at format level, not stream level
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate,avg_frame_rate,field_order,nb_frames,duration,codec_name,width,height",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream_side_data=",
            "-of",
            "json",
            str(video_path),
        ]

        # Import GPU environment support
        try:
            from vsg_core.system.gpu_env import get_subprocess_environment

            env = get_subprocess_environment()
        except ImportError:
            import os

            env = os.environ.copy()

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env
        )

        if result.returncode != 0:
            runner._log_message("[VideoProps] WARNING: ffprobe failed, using defaults")
            return props

        data = json.loads(result.stdout)

        if not data.get("streams"):
            runner._log_message("[VideoProps] WARNING: No video streams found")
            return props

        stream = data["streams"][0]
        props["detection_source"] = "ffprobe"

        # Parse FPS from r_frame_rate (stream's "real" frame rate)
        # and avg_frame_rate (container's calculated average)
        r_frame_rate = stream.get("r_frame_rate", "24000/1001")
        avg_frame_rate = stream.get("avg_frame_rate", r_frame_rate)

        # Parse r_frame_rate (original/real frame rate)
        if "/" in r_frame_rate:
            r_num, r_denom = r_frame_rate.split("/")
            r_num, r_denom = int(r_num), int(r_denom)
            r_fps = r_num / r_denom if r_denom != 0 else 23.976
            r_fps_fraction = (r_num, r_denom)
        else:
            r_fps = float(r_frame_rate) if r_frame_rate else 23.976
            r_fps_fraction = (int(r_fps * 1000), 1000)

        # Parse avg_frame_rate (container average)
        if "/" in avg_frame_rate:
            a_num, a_denom = avg_frame_rate.split("/")
            a_num, a_denom = int(a_num), int(a_denom)
            a_fps = a_num / a_denom if a_denom != 0 else r_fps
        else:
            a_fps = float(avg_frame_rate) if avg_frame_rate else r_fps

        # Detect VFR: significant difference between r_frame_rate and avg_frame_rate
        # This happens when MakeMKV/mkvmerge removes soft-telecine pulldown
        fps_diff_pct = abs(r_fps - a_fps) / r_fps * 100 if r_fps > 0 else 0

        if fps_diff_pct > 1.0:
            # Significant difference indicates VFR container
            props["is_vfr"] = True
            props["fps"] = a_fps  # Container reports this fps
            props["fps_fraction"] = (int(a_fps * 1000), 1000)
            props["original_fps"] = r_fps  # The original stream fps
            props["original_fps_fraction"] = r_fps_fraction

            # Check if this is soft-telecine removal (original ~23.976fps, container ~24.x fps)
            # This happens when MakeMKV removes 2:3 pulldown flags from DVD
            if abs(r_fps - 23.976) < 0.1 and 24.0 < a_fps < 25.0:
                props["is_soft_telecine"] = True
        else:
            # CFR or very close rates
            props["fps"] = r_fps
            props["fps_fraction"] = r_fps_fraction

        # Parse resolution
        props["width"] = stream.get("width", 1920)
        props["height"] = stream.get("height", 1080)

        # Parse field_order for interlacing detection
        field_order = stream.get("field_order", "progressive")

        if field_order in ("tt", "tb"):
            props["interlaced"] = True
            props["field_order"] = "tff"  # Top Field First
            props["scan_type"] = "interlaced"
        elif field_order in ("bb", "bt"):
            props["interlaced"] = True
            props["field_order"] = "bff"  # Bottom Field First
            props["scan_type"] = "interlaced"
        elif field_order == "progressive":
            props["interlaced"] = False
            props["field_order"] = "progressive"
            props["scan_type"] = "progressive"
        else:
            # Unknown - might need deeper analysis
            props["field_order"] = "unknown"

        # Parse duration - try stream first, then format (MKV often only has format duration)
        duration_str = stream.get("duration")
        if duration_str and duration_str != "N/A":
            props["duration_ms"] = float(duration_str) * 1000.0
        else:
            # Try format-level duration (common for MKV files)
            format_info = data.get("format", {})
            format_duration = format_info.get("duration")
            if format_duration and format_duration != "N/A":
                props["duration_ms"] = float(format_duration) * 1000.0

        # Parse frame count (if available)
        nb_frames = stream.get("nb_frames")
        if nb_frames and nb_frames != "N/A":
            props["frame_count"] = int(nb_frames)
        elif props["duration_ms"] > 0 and props["fps"] > 0:
            # Estimate frame count from duration
            props["frame_count"] = int(props["duration_ms"] * props["fps"] / 1000.0)

        # Detect SD content and DVD characteristics
        height = props["height"]
        props["is_sd"] = height <= 576  # 480i, 480p, 576i, 576p

        # DVD detection: MPEG-2 codec + DVD-Video standard resolutions
        # DVD-Video spec only allows MPEG-2 (and rare MPEG-1).
        # This prevents false positives on H.264/H.265 480p encodes.
        codec = stream.get("codec_name", "")
        is_dvd_codec = codec in ("mpeg2video", "mpeg1video")

        # NTSC DVD: 720x480 or 704x480 (also 352x480, 352x240 but rare)
        # PAL DVD: 720x576 or 704x576
        is_ntsc_dvd = (
            is_dvd_codec
            and height in (480, 486)
            and props["width"]
            in (
                720,
                704,
            )
        )
        is_pal_dvd = (
            is_dvd_codec
            and height in (576, 578)
            and props["width"]
            in (
                720,
                704,
            )
        )
        props["is_dvd"] = is_ntsc_dvd or is_pal_dvd
        props["codec_name"] = codec

        # ── MediaInfo detection (MPEG-2 picture header analysis) ──────
        mi_props = _detect_mediainfo_properties(video_path, runner)
        if mi_props:
            props["detection_source"] = "ffprobe+mediainfo"
            # Store raw MediaInfo results for debugging / pair comparison
            props["mediainfo"] = mi_props

            # Use MediaInfo original_fps when available (more reliable for soft TC)
            mi_orig = mi_props.get("mi_original_fps")
            if mi_orig and mi_orig > 0:
                props["original_fps"] = mi_orig
                # Build fraction for common original rates
                if abs(mi_orig - 23.976) < 0.01:
                    props["original_fps_fraction"] = (24000, 1001)
                elif abs(mi_orig - 29.970) < 0.01:
                    props["original_fps_fraction"] = (30000, 1001)
                elif abs(mi_orig - 25.0) < 0.01:
                    props["original_fps_fraction"] = (25, 1)
                else:
                    props["original_fps_fraction"] = (int(mi_orig * 1000), 1000)

            # Override VFR / soft-telecine from MediaInfo (more reliable than
            # ffprobe r_frame_rate vs avg_frame_rate comparison for MPEG-2)
            mi_fps_mode = mi_props.get("mi_fps_mode", "")
            if mi_fps_mode.upper() == "VFR":
                props["is_vfr"] = True
                mi_scan_order = mi_props.get("mi_scan_order", "")
                if "pulldown" in mi_scan_order.lower():
                    props["is_soft_telecine"] = True

        # ── Cross-validated content type classification ───────────────
        content_type, detection_confidence = _classify_content_type(
            props, mi_props, runner,
        )
        props["content_type"] = content_type
        props["detection_confidence"] = detection_confidence

        # ── Logging ──────────────────────────────────────────────────
        if props["is_vfr"]:
            orig = props.get("original_fps")
            orig_frac = props.get("original_fps_fraction")
            if orig and orig_frac:
                runner._log_message(
                    f"[VideoProps] FPS: {props['fps']:.3f} (VFR avg), "
                    f"Original: {orig:.3f} ({orig_frac[0]}/{orig_frac[1]})"
                )
            else:
                runner._log_message(
                    f"[VideoProps] FPS: {props['fps']:.3f} (VFR)"
                )
        else:
            runner._log_message(
                f"[VideoProps] FPS: {props['fps']:.3f} ({props['fps_fraction'][0]}/{props['fps_fraction'][1]})"
            )
        runner._log_message(
            f"[VideoProps] Resolution: {props['width']}x{props['height']}"
        )
        runner._log_message(
            f"[VideoProps] Scan: {props['scan_type']}, Field order: {props['field_order']}"
        )
        runner._log_message(
            f"[VideoProps] Duration: {props['duration_ms']:.0f}ms, Frames: ~{props['frame_count']}"
        )

        # Content type summary
        dvd_note = " (DVD)" if props["is_dvd"] else ""
        sd_note = " (SD)" if props["is_sd"] and not props["is_dvd"] else ""
        runner._log_message(
            f"[VideoProps] Content type: {content_type}{dvd_note}{sd_note} "
            f"[confidence: {detection_confidence}]"
        )
        runner._log_message(
            f"[VideoProps] Detection source: {props['detection_source']}"
        )

        return props

    except Exception as e:
        runner._log_message(f"[VideoProps] WARNING: Detection failed: {e}")
        return props


def get_video_properties(
    video_path: str, runner, tool_paths: dict | None = None
) -> dict[str, Any]:
    """
    Get video properties including resolution.

    This is a convenience wrapper around detect_video_properties that accepts
    an optional tool_paths parameter for compatibility with different calling conventions.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging
        tool_paths: Optional dict of tool paths (currently unused, for API compatibility)

    Returns:
        Dict with video properties including 'width', 'height', 'fps', etc.
    """
    return detect_video_properties(video_path, runner)


def get_video_duration_ms(video_path: str, runner) -> float:
    """
    Get video duration in milliseconds.

    Convenience function that extracts just the duration from video properties.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        Duration in milliseconds, or 0.0 on failure
    """
    props = detect_video_properties(video_path, runner)
    return props.get("duration_ms", 0.0)


def compare_video_properties(
    source_props: dict[str, Any], target_props: dict[str, Any], runner
) -> dict[str, Any]:
    """
    Compare video properties between source and target to determine sync strategy.

    Pair classification (source × target content types):

    Progressive × Progressive  → frame-based (current CFR path, no changes)
    Progressive × Interlaced   → cross-fps (29.970↔23.976, not yet implemented)
    Progressive × Soft TC      → cross-fps + VFR timestamps (not yet implemented)
    Interlaced  × Interlaced   → frame-based (same 29.970 CFR)
    Interlaced  × Soft TC      → cross-fps + VFR timestamps (not yet implemented)
    Soft TC     × Soft TC      → frame-based with VFR timestamps (not yet implemented)

    Currently only the frame-based (CFR) path is active.  Other pair types are
    detected and logged but fall through to the correlation-only fallback.

    Args:
        source_props: Properties dict from detect_video_properties() for source
        target_props: Properties dict from detect_video_properties() for target
        runner: CommandRunner for logging

    Returns:
        Dict with:
            - strategy: str ('frame-based', 'cross-fps', 'timestamp-based', 'scale')
            - pair_type: str (e.g. 'progressive+progressive', 'interlaced+progressive')
            - fps_match: bool
            - fps_ratio: float (source_fps / target_fps)
            - content_type_match: bool (both sources same content type)
            - needs_scaling: bool
            - scale_factor: float (for PAL speedup etc.)
            - warnings: list of warning strings
    """
    runner._log_message("[VideoProps] ─────────────────────────────────────────")
    runner._log_message("[VideoProps] Comparing source vs target properties...")

    src_type = source_props.get("content_type", "unknown")
    tgt_type = target_props.get("content_type", "unknown")
    pair_type = f"{src_type}+{tgt_type}"

    result: dict[str, Any] = {
        "strategy": "frame-based",
        "pair_type": pair_type,
        "fps_match": True,
        "fps_ratio": 1.0,
        "content_type_match": src_type == tgt_type,
        "needs_scaling": False,
        "scale_factor": 1.0,
        "warnings": [],
    }

    source_fps = source_props["fps"]
    target_fps = target_props["fps"]

    runner._log_message(
        f"[VideoProps] Source: {src_type} @ {source_fps:.3f}fps "
        f"({'DVD' if source_props.get('is_dvd') else source_props.get('codec_name', '?')})"
    )
    runner._log_message(
        f"[VideoProps] Target: {tgt_type} @ {target_fps:.3f}fps "
        f"({'DVD' if target_props.get('is_dvd') else target_props.get('codec_name', '?')})"
    )

    # ── FPS comparison ───────────────────────────────────────────
    if target_fps > 0:
        fps_diff_pct = abs(source_fps - target_fps) / target_fps * 100
    else:
        fps_diff_pct = 0
    result["fps_ratio"] = source_fps / target_fps if target_fps > 0 else 1.0

    if fps_diff_pct < 0.1:
        result["fps_match"] = True
        runner._log_message(
            f"[VideoProps] FPS: MATCH ({source_fps:.3f} ≈ {target_fps:.3f})"
        )
    else:
        result["fps_match"] = False
        runner._log_message(
            f"[VideoProps] FPS: MISMATCH ({source_fps:.3f} vs {target_fps:.3f}, "
            f"diff={fps_diff_pct:.2f}%)"
        )

    # ── PAL speedup detection ────────────────────────────────────
    ratio = result["fps_ratio"]
    if 1.04 < ratio < 1.05:
        result["needs_scaling"] = True
        result["scale_factor"] = target_fps / source_fps
        result["strategy"] = "scale"
        result["warnings"].append(
            f"PAL speedup detected (ratio={ratio:.4f})"
        )
        runner._log_message("[VideoProps] PAL speedup detected")
    elif ratio > 0 and 0.95 < 1 / ratio < 0.96:
        result["needs_scaling"] = True
        result["scale_factor"] = target_fps / source_fps
        result["strategy"] = "scale"
        result["warnings"].append("Reverse PAL detected")
        runner._log_message("[VideoProps] Reverse PAL detected")

    # ── Pair type strategy ───────────────────────────────────────
    # Both progressive (normal CFR path — current working mode)
    if src_type == "progressive" and tgt_type == "progressive":
        if result["fps_match"]:
            result["strategy"] = "frame-based"
            runner._log_message("[VideoProps] Pair: progressive+progressive → frame-based (CFR)")
        # else: already set to scale or stays frame-based

    # Both pure interlaced (same 29.970 CFR — frame-based works)
    elif src_type == "interlaced" and tgt_type == "interlaced":
        if result["fps_match"]:
            result["strategy"] = "frame-based"
            runner._log_message("[VideoProps] Pair: interlaced+interlaced → frame-based (same CFR)")
        else:
            result["warnings"].append(
                "Both interlaced but different FPS — unusual"
            )

    # Cross-type: one interlaced/soft-TC, one progressive (cross-FPS)
    elif not result["content_type_match"] and not result["needs_scaling"]:
        # This is the DVD-vs-encode scenario
        # 29.970 interlaced vs 23.976 progressive = 5:4 ratio
        is_29_vs_23 = (
            (abs(source_fps - 29.970) < 0.1 and abs(target_fps - 23.976) < 0.1)
            or (abs(target_fps - 29.970) < 0.1 and abs(source_fps - 23.976) < 0.1)
        )
        if is_29_vs_23:
            result["strategy"] = "cross-fps"
            runner._log_message(
                f"[VideoProps] Pair: {pair_type} → cross-fps (29.970↔23.976, 5:4 ratio)"
            )
            result["warnings"].append(
                "Cross-FPS pair detected (29.970↔23.976) — "
                "frame mapping not yet implemented, will use correlation"
            )
        else:
            result["strategy"] = "timestamp-based"
            runner._log_message(
                f"[VideoProps] Pair: {pair_type} → timestamp-based"
            )
            result["warnings"].append(
                f"Mixed content types ({pair_type}) with non-standard FPS ratio"
            )

    # Soft telecine involved
    elif "soft_telecine" in pair_type:
        result["strategy"] = "timestamp-based"
        runner._log_message(
            f"[VideoProps] Pair: {pair_type} → timestamp-based (VFR involved)"
        )
        if not result["warnings"]:
            result["warnings"].append(
                "Soft telecine in pair — VFR timestamp handling needed"
            )

    # ── Summary ──────────────────────────────────────────────────
    # Detection confidence (lowest of the pair)
    src_conf = source_props.get("detection_confidence", "unknown")
    tgt_conf = target_props.get("detection_confidence", "unknown")
    conf_order = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    pair_confidence = min(src_conf, tgt_conf, key=lambda c: conf_order.get(c, 0))

    result["detection_confidence"] = pair_confidence

    runner._log_message(
        f"[VideoProps] Strategy: {result['strategy']} "
        f"(pair: {pair_type}, confidence: {pair_confidence})"
    )
    for warn in result["warnings"]:
        runner._log_message(f"[VideoProps] ⚠ {warn}")
    runner._log_message("[VideoProps] ─────────────────────────────────────────")

    return result
