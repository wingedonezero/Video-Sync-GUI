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
    # Multi-frame detection
    multi_tff: int
    multi_bff: int
    multi_progressive: int
    multi_undetermined: int
    # Duplicate detection (from mpdecimate output frame count)
    input_frames: int
    output_frames: int


@dataclass(frozen=True, slots=True)
class ContentAnalysis:
    """Analyzed content type for a video file.

    Produced by analyze_content_type() using ffmpeg idet filter on the
    whole file. Only runs for MPEG-2 DVD content (codec + resolution gate).
    """

    content_type: ContentTypeStr
    field_order: FieldOrderStr
    confidence: float  # 0.0-1.0
    duplicate_ratio: float  # ~0.2 = 3:2 telecine pattern
    analysis_source: str  # 'idet', 'idet+mpdecimate', 'metadata_only'


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
    Analyze actual content type using ffmpeg idet + mpdecimate on the WHOLE file.

    Only runs the full analysis for MPEG-2 DVD content (codec + resolution gate).
    Non-DVD content returns immediately with metadata-based classification.
    Results are cached in memory for the job duration.

    Single ffmpeg pass with chained filters:
    - idet: detects interlacing (TFF/BFF/progressive) and repeated fields (pulldown)
    - mpdecimate: detects duplicate frames (output frame count vs input)

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
            duplicate_ratio=0.0,
            analysis_source="metadata_only",
        )
        _content_analysis_cache[video_path] = result
        return result

    runner._log_message(
        f"[ContentAnalysis] MPEG-2 DVD detected, running full idet analysis on: "
        f"{Path(video_path).name}"
    )
    runner._log_message(
        "[ContentAnalysis] Analyzing whole file (this may take 1-3 minutes)..."
    )

    # Run idet + mpdecimate in a single ffmpeg pass
    idet = _run_idet_analysis(video_path, props.get("frame_count", 0), runner)

    if idet is None:
        # Analysis failed, fall back to metadata
        runner._log_message(
            "[ContentAnalysis] Analysis failed, using metadata fallback"
        )
        result = ContentAnalysis(
            content_type=props.get("content_type", "unknown"),
            field_order=props.get("field_order", "progressive"),
            confidence=0.3,
            duplicate_ratio=0.0,
            analysis_source="metadata_only",
        )
        _content_analysis_cache[video_path] = result
        return result

    # Classify based on idet results
    result = _classify_content(idet, props, runner)
    _content_analysis_cache[video_path] = result

    runner._log_message(
        f"[ContentAnalysis] Result: {result.content_type} "
        f"(field_order={result.field_order}, confidence={result.confidence:.0%}, "
        f"duplicates={result.duplicate_ratio:.1%}, source={result.analysis_source})"
    )

    return result


def _run_idet_analysis(
    video_path: str, expected_frames: int, runner
) -> IdetResult | None:
    """
    Run ffmpeg with idet + mpdecimate filters on the whole file.

    Single decode pass gives us:
    - idet: interlace detection (TFF/BFF/Progressive per frame) + repeated fields
    - mpdecimate: duplicate frame detection (compares output vs input frame count)

    Args:
        video_path: Path to video file
        expected_frames: Expected frame count from ffprobe (for duplicate ratio)
        runner: CommandRunner for logging

    Returns:
        IdetResult with all parsed stats, or None on failure.
    """
    import os

    try:
        from vsg_core.system.gpu_env import get_subprocess_environment

        env = get_subprocess_environment()
    except ImportError:
        env = os.environ.copy()

    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-vf",
        "idet,mpdecimate",
        "-an",
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

    # Parse idet output: "Repeated Fields: Neither: N Top: N Bottom: N"
    repeated_match = re.search(
        r"Repeated Fields: Neither:\s*(\d+)\s+Top:\s*(\d+)\s+Bottom:\s*(\d+)",
        stderr,
    )
    # Parse: "Single frame detection: TFF: N BFF: N Progressive: N Undetermined: N"
    single_match = re.search(
        r"Single frame detection: TFF:\s*(\d+)\s+BFF:\s*(\d+)\s+"
        r"Progressive:\s*(\d+)\s+Undetermined:\s*(\d+)",
        stderr,
    )
    # Parse: "Multi frame detection: TFF: N BFF: N Progressive: N Undetermined: N"
    multi_match = re.search(
        r"Multi frame detection:\s+TFF:\s*(\d+)\s+BFF:\s*(\d+)\s+"
        r"Progressive:\s*(\d+)\s+Undetermined:\s*(\d+)",
        stderr,
    )
    # Parse output frame count: "frame= N fps=..."
    frame_match = re.search(r"frame=\s*(\d+)", stderr)

    if not single_match:
        runner._log_message("[ContentAnalysis] WARNING: Could not parse idet output")
        return None

    # Build result
    output_frames = int(frame_match.group(1)) if frame_match else expected_frames

    # Input frames = sum of single-frame detection counts (all frames analyzed)
    input_frames = (
        int(single_match.group(1))
        + int(single_match.group(2))
        + int(single_match.group(3))
        + int(single_match.group(4))
    )

    # Use expected_frames as fallback if idet sum seems wrong
    if input_frames == 0 and expected_frames > 0:
        input_frames = expected_frames

    return IdetResult(
        repeated_neither=int(repeated_match.group(1)) if repeated_match else 0,
        repeated_top=int(repeated_match.group(2)) if repeated_match else 0,
        repeated_bottom=int(repeated_match.group(3)) if repeated_match else 0,
        single_tff=int(single_match.group(1)),
        single_bff=int(single_match.group(2)),
        single_progressive=int(single_match.group(3)),
        single_undetermined=int(single_match.group(4)),
        multi_tff=int(multi_match.group(1)) if multi_match else 0,
        multi_bff=int(multi_match.group(2)) if multi_match else 0,
        multi_progressive=int(multi_match.group(3)) if multi_match else 0,
        multi_undetermined=int(multi_match.group(4)) if multi_match else 0,
        input_frames=input_frames,
        output_frames=output_frames,
    )


def _classify_content(
    idet: IdetResult, props: dict[str, Any], runner
) -> ContentAnalysis:
    """
    Classify content type based on idet analysis results.

    Classification logic:
    - Mostly TFF/BFF + repeated fields → telecine_hard (needs VFM + VDecimate)
    - Mostly progressive + repeated fields → telecine_soft (needs VDecimate only)
    - Mostly TFF/BFF, few repeated → interlaced (needs deinterlace)
    - Mostly progressive + duplicates (~20%) → telecine_soft (baked-in pulldown)
    - Mostly progressive, no duplicates → progressive (passthrough)
    - Mix → mixed
    """
    total = idet.input_frames
    if total == 0:
        return ContentAnalysis(
            content_type="unknown",
            field_order=props.get("field_order", "progressive"),
            confidence=0.0,
            duplicate_ratio=0.0,
            analysis_source="idet",
        )

    # Calculate ratios
    interlaced_count = idet.single_tff + idet.single_bff
    interlaced_ratio = interlaced_count / total
    progressive_ratio = idet.single_progressive / total
    repeated_count = idet.repeated_top + idet.repeated_bottom
    repeated_ratio = repeated_count / total if total > 0 else 0.0

    # Duplicate ratio from mpdecimate (output vs input frame count)
    if idet.input_frames > 0 and idet.output_frames > 0:
        duplicate_ratio = 1.0 - (idet.output_frames / idet.input_frames)
    else:
        duplicate_ratio = 0.0

    # Determine field order from whichever dominates
    if idet.single_tff > idet.single_bff:
        field_order: FieldOrderStr = "tff"
    elif idet.single_bff > idet.single_tff:
        field_order = "bff"
    else:
        field_order = "progressive"

    # Log detailed stats
    runner._log_message(
        f"[ContentAnalysis] idet: interlaced={interlaced_ratio:.1%} "
        f"(TFF={idet.single_tff}, BFF={idet.single_bff}), "
        f"progressive={progressive_ratio:.1%} ({idet.single_progressive}), "
        f"undetermined={idet.single_undetermined}"
    )
    runner._log_message(
        f"[ContentAnalysis] Repeated fields: top={idet.repeated_top}, "
        f"bottom={idet.repeated_bottom}, neither={idet.repeated_neither} "
        f"(ratio={repeated_ratio:.1%})"
    )
    runner._log_message(
        f"[ContentAnalysis] Duplicates: {idet.output_frames}/{idet.input_frames} "
        f"output frames (duplicate_ratio={duplicate_ratio:.1%})"
    )

    # Classification decision tree
    content_type: ContentTypeStr
    confidence: float
    analysis_source: str

    if interlaced_ratio > 0.5 and repeated_ratio > 0.05:
        # Mostly interlaced + repeated fields = hard telecine
        content_type = "telecine_hard"
        confidence = min(0.95, interlaced_ratio)
        analysis_source = "idet"

    elif progressive_ratio > 0.7 and repeated_ratio > 0.05:
        # Mostly progressive + repeated fields = soft telecine (flags present)
        content_type = "telecine_soft"
        confidence = min(0.95, progressive_ratio)
        analysis_source = "idet"

    elif interlaced_ratio > 0.5:
        # Mostly interlaced, few/no repeated fields = pure interlaced
        content_type = "interlaced"
        confidence = min(0.95, interlaced_ratio)
        analysis_source = "idet"

    elif progressive_ratio > 0.7 and duplicate_ratio > 0.15:
        # Mostly progressive but ~20% duplicates = baked-in pulldown
        # (flags were stripped but duplicate frames remain)
        content_type = "telecine_soft"
        confidence = 0.85
        analysis_source = "idet+mpdecimate"

    elif progressive_ratio > 0.7:
        # Mostly progressive, no duplicates = true progressive
        content_type = "progressive"
        confidence = min(0.95, progressive_ratio)
        analysis_source = "idet+mpdecimate"

    else:
        # Mix of interlaced and progressive sections
        content_type = "mixed"
        confidence = 0.7
        analysis_source = "idet"

    return ContentAnalysis(
        content_type=content_type,
        field_order=field_order,
        confidence=confidence,
        duplicate_ratio=duplicate_ratio,
        analysis_source=analysis_source,
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
