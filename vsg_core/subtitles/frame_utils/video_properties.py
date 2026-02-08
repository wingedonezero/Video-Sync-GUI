# vsg_core/subtitles/frame_utils/video_properties.py
"""
Video property detection functions for subtitle synchronization.

Contains:
- FPS detection
- Comprehensive video property detection (interlacing, duration, resolution)
- Content type analysis (idet + mpdecimate for MPEG-2 DVD content)
- Video property comparison for sync strategy selection
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.models.types import ContentTypeStr, FieldOrderStr


@dataclass(frozen=True, slots=True)
class IdetResult:
    """Raw output from ffmpeg idet filter (whole-file analysis)."""

    # Repeated fields
    repeated_neither: int
    repeated_top: int
    repeated_bottom: int
    # Single-frame detection
    single_tff: int
    single_bff: int
    single_progressive: int
    single_undetermined: int
    # Multi-frame detection (primary — more accurate than single)
    multi_tff: int
    multi_bff: int
    multi_progressive: int
    multi_undetermined: int
    # Total frames analyzed
    total_frames: int


@dataclass(frozen=True, slots=True)
class RepeatPictResult:
    """Per-frame repeat_pict analysis from ffprobe.

    repeat_pict maps to MPEG-2 repeat_first_field flag:
    - repeat_pict=0: normal frame (2 fields)
    - repeat_pict=1: repeat first field (3 fields) = pulldown marker
    """

    total_frames: int
    repeat_pict_0: int  # Normal frames
    repeat_pict_1: int  # Frames with RFF set (pulldown)
    repeat_pict_other: int  # Any other values (rare)
    interlaced_frames: int  # Frames with interlaced_frame=1
    progressive_frames: int  # Frames with interlaced_frame=0


@dataclass(frozen=True, slots=True)
class ContentAnalysis:
    """Analyzed content type for a video file.

    Produced by analyze_content_type() using a 3-layer detection pipeline:
    1. ffprobe repeat_pict — detects soft telecine pulldown flags (fast, no decode)
    2. ffmpeg idet — detects interlacing at pixel level (requires decode)
    3. Metadata fallback — progressive MPEG-2 DVD at ~30fps = assumed telecine_soft

    Only runs for MPEG-2 DVD content (codec + resolution gate).
    """

    content_type: ContentTypeStr
    field_order: FieldOrderStr
    confidence: float  # 0.0-1.0
    repeat_pict_ratio: float  # ratio of frames with RFF flags (~0.5 = 3:2 pulldown)
    analysis_source: str  # 'repeat_pict', 'idet', 'metadata_fallback', 'metadata_only'


# Module-level cache for content analysis results (lives for the job)
_content_analysis_cache: dict[str, ContentAnalysis] = {}


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

        # Determine content_type based on multiple factors
        # This helps decide which settings to use
        if props["interlaced"]:
            # Check for telecine characteristics
            # NTSC telecine: 29.97fps interlaced from 24fps film
            if abs(props["fps"] - 29.97) < 0.1 and is_ntsc_dvd:
                # Likely telecine - NTSC DVD with 29.97i that was probably 24fps film
                props["content_type"] = "telecine"
            else:
                props["content_type"] = "interlaced"
        elif abs(props["fps"] - 29.97) < 0.1 and props["is_sd"]:
            # 29.97p SD content - could be soft telecine or native
            props["content_type"] = "unknown"  # Need further analysis
        else:
            props["content_type"] = "progressive"

        # Log detected properties
        if props["is_vfr"]:
            runner._log_message(
                f"[VideoProps] FPS: {props['fps']:.3f} (VFR avg), Original: {props['original_fps']:.3f} ({props['original_fps_fraction'][0]}/{props['original_fps_fraction'][1]})"
            )
            if props["is_soft_telecine"]:
                runner._log_message(
                    "[VideoProps] NOTE: Soft-telecine removal detected (MakeMKV/mkvmerge created VFR)"
                )
        else:
            runner._log_message(
                f"[VideoProps] FPS: {props['fps']:.3f} ({props['fps_fraction'][0]}/{props['fps_fraction'][1]})"
            )
        runner._log_message(
            f"[VideoProps] Resolution: {props['width']}x{props['height']}"
        )
        runner._log_message(
            f"[VideoProps] Scan type: {props['scan_type']}, Field order: {props['field_order']}"
        )
        runner._log_message(
            f"[VideoProps] Duration: {props['duration_ms']:.0f}ms, Frames: {props['frame_count']}"
        )

        # Log content type detection
        if props["is_dvd"]:
            runner._log_message(
                f"[VideoProps] Content type: {props['content_type']} (DVD detected)"
            )
        elif props["is_sd"]:
            runner._log_message(
                f"[VideoProps] Content type: {props['content_type']} (SD content)"
            )
        else:
            runner._log_message(f"[VideoProps] Content type: {props['content_type']}")

        # Additional notes for specific content types
        if props["content_type"] == "telecine":
            runner._log_message(
                "[VideoProps] NOTE: Telecine detected - IVTC may improve frame matching"
            )
        elif props["content_type"] == "interlaced":
            runner._log_message(
                "[VideoProps] NOTE: Interlaced content - deinterlacing required for frame matching"
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


def analyze_content_type(
    video_path: str,
    runner,
    props: dict[str, Any] | None = None,
) -> ContentAnalysis:
    """
    Analyze actual content type using a 3-layer detection pipeline.

    Only runs for MPEG-2 DVD content (codec + resolution gate).
    Non-DVD content returns immediately with metadata-based classification.
    Results are cached in memory for the job duration.

    Detection layers:
    1. ffprobe repeat_pict — reads RFF flags per frame (fast, no decode)
    2. ffmpeg idet — pixel-level interlace detection (whole-file decode)
    3. Metadata fallback — progressive MPEG-2 DVD at ~30fps = telecine_soft

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging
        props: Pre-detected properties (avoids re-running ffprobe). If None,
               detect_video_properties() is called automatically.

    Returns:
        ContentAnalysis with precise content_type, field_order, and confidence.
    """
    # Check cache first
    if video_path in _content_analysis_cache:
        cached = _content_analysis_cache[video_path]
        runner._log_message(
            f"[ContentAnalysis] Using cached result: {cached.content_type} "
            f"(confidence={cached.confidence:.0%})"
        )
        return cached

    # Get properties if not provided
    if props is None:
        props = detect_video_properties(video_path, runner)

    # Gate: only run full analysis for MPEG-2 DVD content
    if not props.get("is_dvd", False):
        # Non-DVD: use metadata classification directly
        result = ContentAnalysis(
            content_type=props.get("content_type", "progressive"),
            field_order=props.get("field_order", "progressive"),
            confidence=0.5,
            repeat_pict_ratio=0.0,
            analysis_source="metadata_only",
        )
        _content_analysis_cache[video_path] = result
        return result

    filename = Path(video_path).name
    runner._log_message(f"[ContentAnalysis] MPEG-2 DVD detected, analyzing: {filename}")

    # ── Layer 1: ffprobe repeat_pict (fast, reads flags without decoding) ──
    runner._log_message("[ContentAnalysis] Layer 1: Checking repeat_pict flags...")
    rp = _analyze_repeat_pict(video_path, runner)

    if rp is not None and rp.total_frames > 0:
        rp_ratio = rp.repeat_pict_1 / rp.total_frames
        interlaced_ratio_rp = rp.interlaced_frames / rp.total_frames
        runner._log_message(
            f"[ContentAnalysis] repeat_pict: {rp.repeat_pict_0} normal, "
            f"{rp.repeat_pict_1} RFF ({rp_ratio:.1%}), "
            f"interlaced={interlaced_ratio_rp:.1%}"
        )

        # Soft telecine: ~50% RFF flags + progressive frames
        if rp_ratio > 0.3 and interlaced_ratio_rp < 0.1:
            result = ContentAnalysis(
                content_type="telecine_soft",
                field_order="progressive",
                confidence=min(0.98, 0.5 + rp_ratio),
                repeat_pict_ratio=rp_ratio,
                analysis_source="repeat_pict",
            )
            _content_analysis_cache[video_path] = result
            runner._log_message(
                f"[ContentAnalysis] Result: {result.content_type} "
                f"(RFF flags detected, confidence={result.confidence:.0%})"
            )
            return result

        # Hard telecine with RFF: interlaced + pulldown flags (rare but possible)
        if rp_ratio > 0.3 and interlaced_ratio_rp > 0.5:
            result = ContentAnalysis(
                content_type="telecine_hard",
                field_order="tff" if rp.interlaced_frames > 0 else "progressive",
                confidence=min(0.95, 0.5 + rp_ratio),
                repeat_pict_ratio=rp_ratio,
                analysis_source="repeat_pict",
            )
            _content_analysis_cache[video_path] = result
            runner._log_message(
                f"[ContentAnalysis] Result: {result.content_type} "
                f"(interlaced + RFF flags, confidence={result.confidence:.0%})"
            )
            return result
    else:
        runner._log_message(
            "[ContentAnalysis] Layer 1: No repeat_pict data (flags may be stripped)"
        )

    # ── Layer 2: ffmpeg idet (full decode, pixel-level detection) ──
    runner._log_message(
        "[ContentAnalysis] Layer 2: Running idet analysis (whole file decode)..."
    )
    idet = _run_idet_analysis(video_path, runner)

    if idet is not None and idet.total_frames > 0:
        result = _classify_from_idet(idet, props, runner)
        _content_analysis_cache[video_path] = result
        runner._log_message(
            f"[ContentAnalysis] Result: {result.content_type} "
            f"(field_order={result.field_order}, confidence={result.confidence:.0%}, "
            f"source={result.analysis_source})"
        )
        return result

    runner._log_message("[ContentAnalysis] Layer 2: idet analysis returned no data")

    # ── Layer 3: Metadata fallback ──
    runner._log_message("[ContentAnalysis] Layer 3: Using metadata fallback")
    result = _classify_from_metadata(props, runner)
    _content_analysis_cache[video_path] = result
    runner._log_message(
        f"[ContentAnalysis] Result: {result.content_type} "
        f"(field_order={result.field_order}, confidence={result.confidence:.0%}, "
        f"source={result.analysis_source})"
    )
    return result


def _get_subprocess_env() -> dict[str, str]:
    """Get subprocess environment with GPU support if available."""
    import os

    try:
        from vsg_core.system.gpu_env import get_subprocess_environment

        return get_subprocess_environment()
    except ImportError:
        return os.environ.copy()


def _analyze_repeat_pict(video_path: str, runner) -> RepeatPictResult | None:
    """
    Layer 1: Analyze repeat_pict flags using ffprobe (no decode needed).

    Reads per-frame interlaced_frame and repeat_pict flags directly from the
    MPEG-2 stream headers. This is fast and the most reliable way to detect
    soft telecine when pulldown flags are present.

    repeat_pict=1 maps to MPEG-2 repeat_first_field=1 (3:2 pulldown marker).
    ~50% of frames having repeat_pict=1 = soft telecine.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        RepeatPictResult with flag counts, or None on failure.
    """
    env = _get_subprocess_env()

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=interlaced_frame,repeat_pict",
        "-of",
        "csv=p=0",
        str(video_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, env=env
        )
    except subprocess.TimeoutExpired:
        runner._log_message(
            "[ContentAnalysis] WARNING: repeat_pict analysis timed out (5min)"
        )
        return None
    except Exception as e:
        runner._log_message(
            f"[ContentAnalysis] WARNING: repeat_pict analysis failed: {e}"
        )
        return None

    if result.returncode != 0:
        return None

    # Parse CSV output: each line is "interlaced_frame,repeat_pict"
    total = 0
    rp_0 = 0
    rp_1 = 0
    rp_other = 0
    interlaced = 0
    progressive = 0

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            interlaced_flag = int(parts[0])
            repeat_pict = int(parts[1])
        except (ValueError, IndexError):
            continue

        total += 1
        if repeat_pict == 0:
            rp_0 += 1
        elif repeat_pict == 1:
            rp_1 += 1
        else:
            rp_other += 1

        if interlaced_flag == 1:
            interlaced += 1
        else:
            progressive += 1

    if total == 0:
        return None

    return RepeatPictResult(
        total_frames=total,
        repeat_pict_0=rp_0,
        repeat_pict_1=rp_1,
        repeat_pict_other=rp_other,
        interlaced_frames=interlaced,
        progressive_frames=progressive,
    )


def _run_idet_analysis(video_path: str, runner) -> IdetResult | None:
    """
    Layer 2: Run ffmpeg idet filter on the whole file for pixel-level detection.

    Parses stderr line-by-line (modeled after the working Remux-Toolkit
    telecine_detector). Uses multi-frame detection as primary metric.

    No mpdecimate — just idet alone for reliable interlace detection.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        IdetResult with all parsed stats, or None on failure.
    """
    env = _get_subprocess_env()

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-i",
        str(video_path),
        "-vf",
        "idet",
        "-an",
        "-sn",
        "-dn",
        "-f",
        "null",
        "-",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, env=env
        )
    except subprocess.TimeoutExpired:
        runner._log_message(
            "[ContentAnalysis] WARNING: idet analysis timed out (10min)"
        )
        return None
    except Exception as e:
        runner._log_message(f"[ContentAnalysis] WARNING: idet analysis failed: {e}")
        return None

    stderr = result.stderr

    # Parse line-by-line like the working Remux-Toolkit telecine_detector
    repeated_neither = repeated_top = repeated_bottom = 0
    single_tff = single_bff = single_prog = single_undet = 0
    multi_tff = multi_bff = multi_prog = multi_undet = 0
    found_any = False

    # Regex for the 4-value TFF/BFF/Progressive/Undetermined pattern
    tff_bff_re = re.compile(
        r"TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
    )
    # Regex for repeated fields
    repeated_re = re.compile(r"Neither:\s*(\d+)\s*Top:\s*(\d+)\s*Bottom:\s*(\d+)")

    for line in stderr.splitlines():
        # Repeated Fields summary line
        if "Repeated Fields:" in line:
            after = line.split("Repeated Fields:", 1)[1]
            m = repeated_re.search(after)
            if m:
                repeated_neither = int(m.group(1))
                repeated_top = int(m.group(2))
                repeated_bottom = int(m.group(3))
                found_any = True

        # Single frame detection summary line
        elif "Single frame detection:" in line:
            after = line.split("Single frame detection:", 1)[1]
            m = tff_bff_re.search(after)
            if m:
                single_tff = int(m.group(1))
                single_bff = int(m.group(2))
                single_prog = int(m.group(3))
                single_undet = int(m.group(4))
                found_any = True

        # Multi frame detection summary line
        elif "Multi frame detection:" in line:
            after = line.split("Multi frame detection:", 1)[1]
            m = tff_bff_re.search(after)
            if m:
                multi_tff = int(m.group(1))
                multi_bff = int(m.group(2))
                multi_prog = int(m.group(3))
                multi_undet = int(m.group(4))
                found_any = True

    if not found_any:
        runner._log_message(
            "[ContentAnalysis] WARNING: Could not parse idet output from stderr"
        )
        # Log a snippet of stderr for debugging
        stderr_lines = stderr.splitlines()
        runner._log_message(
            f"[ContentAnalysis] stderr has {len(stderr_lines)} lines, "
            f"last 5: {stderr_lines[-5:] if len(stderr_lines) >= 5 else stderr_lines}"
        )
        return None

    # Total frames = sum of multi-frame detection counts (primary metric)
    total_frames = multi_tff + multi_bff + multi_prog + multi_undet
    # Fallback to single-frame if multi is empty
    if total_frames == 0:
        total_frames = single_tff + single_bff + single_prog + single_undet

    return IdetResult(
        repeated_neither=repeated_neither,
        repeated_top=repeated_top,
        repeated_bottom=repeated_bottom,
        single_tff=single_tff,
        single_bff=single_bff,
        single_progressive=single_prog,
        single_undetermined=single_undet,
        multi_tff=multi_tff,
        multi_bff=multi_bff,
        multi_progressive=multi_prog,
        multi_undetermined=multi_undet,
        total_frames=total_frames,
    )


def _classify_from_idet(
    idet: IdetResult, props: dict[str, Any], runner
) -> ContentAnalysis:
    """
    Classify content type from idet results (Layer 2).

    Uses multi-frame detection as primary metric (more accurate than single).
    Modeled after Remux-Toolkit telecine_detector classification.

    Decision tree:
    - Progressive >= 90% → telecine_soft (film content, like Remux-Toolkit "Telecined (Film)")
      BUT only if MPEG-2 DVD at ~30fps (otherwise just progressive)
    - Interlaced > progressive → telecine_hard (if DVD ~30fps) or interlaced
    - Progressive > interlaced → progressive
    - Otherwise → mixed
    """
    total = idet.total_frames
    if total == 0:
        return ContentAnalysis(
            content_type="unknown",
            field_order=props.get("field_order", "progressive"),
            confidence=0.0,
            repeat_pict_ratio=0.0,
            analysis_source="idet",
        )

    # Use multi-frame detection as primary (like Remux-Toolkit)
    interlaced_count = idet.multi_tff + idet.multi_bff
    interlaced_ratio = interlaced_count / total
    progressive_ratio = idet.multi_progressive / total
    repeated_count = idet.repeated_top + idet.repeated_bottom
    repeated_ratio = repeated_count / total

    # Field order from whichever dominates (multi-frame)
    if idet.multi_tff > idet.multi_bff:
        field_order: FieldOrderStr = "tff"
    elif idet.multi_bff > idet.multi_tff:
        field_order = "bff"
    else:
        field_order = "progressive"

    is_dvd_30fps = props.get("is_dvd", False) and abs(props.get("fps", 0) - 29.97) < 0.1

    # Log detailed stats
    runner._log_message(
        f"[ContentAnalysis] idet multi: interlaced={interlaced_ratio:.1%} "
        f"(TFF={idet.multi_tff}, BFF={idet.multi_bff}), "
        f"progressive={progressive_ratio:.1%} ({idet.multi_progressive}), "
        f"undetermined={idet.multi_undetermined}"
    )
    runner._log_message(
        f"[ContentAnalysis] Repeated fields: top={idet.repeated_top}, "
        f"bottom={idet.repeated_bottom}, neither={idet.repeated_neither} "
        f"(ratio={repeated_ratio:.1%})"
    )

    # Classification decision tree
    content_type: ContentTypeStr
    confidence: float

    # Check for telecine with repeated fields first
    if interlaced_ratio > 0.5 and repeated_ratio > 0.05:
        content_type = "telecine_hard"
        confidence = min(0.95, interlaced_ratio)
    elif progressive_ratio > 0.7 and repeated_ratio > 0.05:
        content_type = "telecine_soft"
        confidence = min(0.95, progressive_ratio)
    elif progressive_ratio >= 0.9 and is_dvd_30fps:
        # High progressive on MPEG-2 DVD at ~30fps = film content (baked-in telecine)
        # Matches Remux-Toolkit "Telecined (Film)" classification
        content_type = "telecine_soft"
        confidence = 0.90
    elif interlaced_count > idet.multi_progressive:
        # More interlaced than progressive
        if is_dvd_30fps:
            content_type = "telecine_hard"
            confidence = min(0.90, interlaced_ratio)
        else:
            content_type = "interlaced"
            confidence = min(0.95, interlaced_ratio)
    elif idet.multi_progressive > interlaced_count:
        content_type = "progressive"
        confidence = min(0.95, progressive_ratio)
    else:
        content_type = "mixed"
        confidence = 0.7

    return ContentAnalysis(
        content_type=content_type,
        field_order=field_order,
        confidence=confidence,
        repeat_pict_ratio=0.0,
        analysis_source="idet",
    )


def _classify_from_metadata(props: dict[str, Any], runner) -> ContentAnalysis:
    """
    Layer 3: Classify from metadata when Layers 1 and 2 fail.

    For progressive MPEG-2 DVD at ~30fps, assume telecine_soft (baked-in pulldown).
    This is reliable because of the MPEG-2 codec gate — no false positives on encodes.
    """
    is_dvd = props.get("is_dvd", False)
    fps = props.get("fps", 0)
    interlaced = props.get("interlaced", False)
    field_order = props.get("field_order", "progressive")

    if is_dvd and abs(fps - 29.97) < 0.1:
        if interlaced:
            content_type: ContentTypeStr = "telecine_hard"
            confidence = 0.75
        else:
            # Progressive MPEG-2 DVD at ~30fps with no flags = baked-in telecine
            content_type = "telecine_soft"
            confidence = 0.70
    elif interlaced:
        content_type = "interlaced"
        confidence = 0.6
    else:
        content_type = props.get("content_type", "progressive")
        confidence = 0.4

    runner._log_message(
        f"[ContentAnalysis] Metadata fallback: {content_type} "
        f"(interlaced={interlaced}, fps={fps:.3f}, is_dvd={is_dvd})"
    )

    return ContentAnalysis(
        content_type=content_type,
        field_order=field_order,
        confidence=confidence,
        repeat_pict_ratio=0.0,
        analysis_source="metadata_fallback",
    )


def clear_content_analysis_cache() -> None:
    """Clear the in-memory content analysis cache."""
    _content_analysis_cache.clear()


def compare_video_properties(
    source_props: dict[str, Any], target_props: dict[str, Any], runner
) -> dict[str, Any]:
    """
    Compare video properties between source and target to determine sync strategy.

    Args:
        source_props: Properties dict from detect_video_properties() for source
        target_props: Properties dict from detect_video_properties() for target
        runner: CommandRunner for logging

    Returns:
        Dict with:
            - strategy: str ('frame-based', 'timestamp-based', 'deinterlace', 'scale')
            - fps_match: bool
            - fps_ratio: float (source_fps / target_fps)
            - interlace_mismatch: bool
            - needs_deinterlace: bool
            - needs_scaling: bool
            - scale_factor: float (for PAL speedup etc.)
            - warnings: list of warning strings
    """
    runner._log_message("[VideoProps] -----------------------------------------")
    runner._log_message("[VideoProps] Comparing source vs target properties...")

    result = {
        "strategy": "frame-based",  # Default: current mode works
        "fps_match": True,
        "fps_ratio": 1.0,
        "interlace_mismatch": False,
        "needs_deinterlace": False,
        "needs_scaling": False,
        "scale_factor": 1.0,
        "warnings": [],
    }

    source_fps = source_props["fps"]
    target_fps = target_props["fps"]

    # Check FPS match (within 0.1% tolerance)
    fps_diff_pct = abs(source_fps - target_fps) / target_fps * 100
    result["fps_ratio"] = source_fps / target_fps

    if fps_diff_pct < 0.1:
        # FPS matches
        result["fps_match"] = True
        runner._log_message(
            f"[VideoProps] FPS: MATCH ({source_fps:.3f} ~ {target_fps:.3f})"
        )
    else:
        result["fps_match"] = False
        runner._log_message(
            f"[VideoProps] FPS: MISMATCH ({source_fps:.3f} vs {target_fps:.3f}, diff={fps_diff_pct:.2f}%)"
        )

        # Check for PAL speedup (23.976 -> 25 = 4.17% faster)
        if 1.04 < result["fps_ratio"] < 1.05:
            result["needs_scaling"] = True
            result["scale_factor"] = target_fps / source_fps  # e.g., 23.976/25 = 0.959
            result["strategy"] = "scale"
            result["warnings"].append(
                f"PAL speedup detected (ratio={result['fps_ratio']:.4f}), subtitles need scaling"
            )
            runner._log_message(
                "[VideoProps] PAL speedup detected - will need subtitle scaling"
            )
        elif 0.95 < 1 / result["fps_ratio"] < 0.96:
            # Reverse PAL (25 -> 23.976)
            result["needs_scaling"] = True
            result["scale_factor"] = target_fps / source_fps
            result["strategy"] = "scale"
            result["warnings"].append("Reverse PAL detected, subtitles need scaling")
            runner._log_message(
                "[VideoProps] Reverse PAL detected - will need subtitle scaling"
            )
        else:
            # Different framerates, use timestamp-based
            result["strategy"] = "timestamp-based"
            result["warnings"].append(
                "Different framerates - frame-based matching may be unreliable"
            )
            runner._log_message(
                "[VideoProps] Different framerates - timestamp-based matching recommended"
            )

    # Check interlacing
    source_interlaced = source_props["interlaced"]
    target_interlaced = target_props["interlaced"]

    if source_interlaced != target_interlaced:
        result["interlace_mismatch"] = True
        runner._log_message(
            f"[VideoProps] Interlacing: MISMATCH (source={source_interlaced}, target={target_interlaced})"
        )

    if source_interlaced or target_interlaced:
        result["needs_deinterlace"] = True
        if result["strategy"] == "frame-based":
            result["strategy"] = "deinterlace"
        result["warnings"].append(
            "Interlaced content detected - frame hashing may be less reliable"
        )
        runner._log_message(
            "[VideoProps] Interlaced content - will need deinterlace for frame matching"
        )

    # Summary
    runner._log_message(f"[VideoProps] Recommended strategy: {result['strategy']}")
    if result["warnings"]:
        for warn in result["warnings"]:
            runner._log_message(f"[VideoProps] WARNING: {warn}")
    runner._log_message("[VideoProps] -----------------------------------------")

    return result
