# vsg_core/subtitles/frame_utils/content_analysis.py
"""
DVD content type analysis pipeline for MPEG-2 video.

3-layer detection pipeline:
1. ffprobe repeat_pict -- reads RFF flags per frame (fast, no decode)
2. ffmpeg idet -- pixel-level interlace detection (whole-file decode)
3. Metadata fallback -- progressive MPEG-2 DVD at ~30fps = telecine_soft

Only runs the full pipeline for MPEG-2 DVD content (codec + resolution gate).
Non-DVD content returns immediately with metadata-based classification.
"""

from __future__ import annotations

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
    # Multi-frame detection (primary -- more accurate than single)
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
    # DGIndex-style film percentage from TRF cycling pattern analysis
    film_purity: int = 0  # Frames following 3:2 pulldown cadence
    video_purity: int = 0  # Frames breaking cadence


@dataclass(frozen=True, slots=True)
class ContentAnalysis:
    """Analyzed content type for a video file.

    Produced by analyze_content_type() using a 3-layer detection pipeline:
    1. ffprobe repeat_pict -- detects soft telecine pulldown flags (fast, no decode)
    2. ffmpeg idet -- detects interlacing at pixel level (requires decode)
    3. Metadata fallback -- progressive MPEG-2 DVD at ~30fps = assumed telecine_soft

    Only runs for MPEG-2 DVD content (codec + resolution gate).
    """

    content_type: ContentTypeStr
    field_order: FieldOrderStr
    confidence: float  # 0.0-1.0
    repeat_pict_ratio: float  # ratio of frames with RFF flags (~0.5 = 3:2 pulldown)
    analysis_source: str  # 'repeat_pict', 'idet', 'metadata_fallback', 'metadata_only'


# Module-level cache for content analysis results (lives for the job)
_content_analysis_cache: dict[str, ContentAnalysis] = {}


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
    1. ffprobe repeat_pict -- reads RFF flags per frame (fast, no decode)
    2. ffmpeg idet -- pixel-level interlace detection (whole-file decode)
    3. Metadata fallback -- progressive MPEG-2 DVD at ~30fps = telecine_soft

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
        from .video_properties import detect_video_properties

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

    # -- Layer 1: ffprobe repeat_pict (fast, reads flags without decoding) --
    runner._log_message("[ContentAnalysis] Layer 1: Checking repeat_pict flags...")
    rp = _analyze_repeat_pict(video_path, runner)

    if rp is not None and rp.total_frames > 0:
        rp_ratio = rp.repeat_pict_1 / rp.total_frames
        interlaced_ratio_rp = rp.interlaced_frames / rp.total_frames

        # DGIndex-style film percentage from TRF cycling pattern
        film_total = rp.film_purity + rp.video_purity
        film_percent = (rp.film_purity / film_total * 100.0) if film_total > 0 else 0.0

        runner._log_message(
            f"[ContentAnalysis] repeat_pict: {rp.repeat_pict_0} normal, "
            f"{rp.repeat_pict_1} RFF ({rp_ratio:.1%}), "
            f"interlaced={interlaced_ratio_rp:.1%}"
        )
        runner._log_message(
            f"[ContentAnalysis] DGIndex-style TRF cycling: "
            f"film_purity={rp.film_purity}, video_purity={rp.video_purity}, "
            f"film={film_percent:.1f}%"
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

        # Hard telecine with RFF: interlaced + pulldown flags AND film cycling
        if rp_ratio > 0.3 and interlaced_ratio_rp > 0.5 and film_percent > 50.0:
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
                f"(interlaced + RFF flags + film cycling, confidence={result.confidence:.0%})"
            )
            return result

        # Native interlaced: no RFF flags (or very few) + no film cycling
        if rp_ratio < 0.1 and interlaced_ratio_rp > 0.5 and film_percent < 50.0:
            fo: FieldOrderStr = "tff"  # Default for NTSC DVD
            result = ContentAnalysis(
                content_type="interlaced",
                field_order=fo,
                confidence=0.90,
                repeat_pict_ratio=rp_ratio,
                analysis_source="repeat_pict",
            )
            _content_analysis_cache[video_path] = result
            runner._log_message(
                f"[ContentAnalysis] Result: {result.content_type} "
                f"(native interlaced -- no RFF flags, film={film_percent:.1f}%, "
                f"confidence={result.confidence:.0%})"
            )
            return result
    else:
        runner._log_message(
            "[ContentAnalysis] Layer 1: No repeat_pict data (flags may be stripped)"
        )

    # -- Layer 2: ffmpeg idet (full decode, pixel-level detection) --
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

    # -- Layer 3: Metadata fallback --
    runner._log_message("[ContentAnalysis] Layer 3: Using metadata fallback")
    result = _classify_from_metadata(props, runner)
    _content_analysis_cache[video_path] = result
    runner._log_message(
        f"[ContentAnalysis] Result: {result.content_type} "
        f"(field_order={result.field_order}, confidence={result.confidence:.0%}, "
        f"source={result.analysis_source})"
    )
    return result


def clear_content_analysis_cache() -> None:
    """Clear the in-memory content analysis cache."""
    _content_analysis_cache.clear()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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

    Reads per-frame interlaced_frame, repeat_pict, and top_field_first flags
    directly from the MPEG-2 stream headers. This is fast and the most reliable
    way to detect soft telecine when pulldown flags are present.

    In addition to simple RFF ratio, this implements DGIndex-style TRF cycling
    analysis: the 2-bit value trf = (top_field_first << 1) | repeat_first_field
    should cycle through 0->1->2->3->0... for true 3:2 pulldown (film content).
    Native interlaced content has constant TFF and no RFF, so trf stays constant
    and the cycling check fails -> correctly classified as video/interlaced.

    repeat_pict=1 maps to MPEG-2 repeat_first_field=1 (3:2 pulldown marker).
    ~50% of frames having repeat_pict=1 = soft telecine.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        RepeatPictResult with flag counts and film/video purity, or None on failure.
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
        "frame=interlaced_frame,repeat_pict,top_field_first",
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

    # Parse CSV output: each line is "interlaced_frame,repeat_pict,top_field_first"
    total = 0
    rp_0 = 0
    rp_1 = 0
    rp_other = 0
    interlaced = 0
    progressive = 0

    # DGIndex-style TRF cycling analysis
    film_purity = 0
    video_purity = 0
    old_trf: int | None = None

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
            tff_flag = int(parts[2]) if len(parts) >= 3 else 0
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

        # DGIndex-style TRF cycling check
        rff = 1 if repeat_pict >= 1 else 0
        trf = (tff_flag << 1) | rff

        if old_trf is not None:
            if (trf & 3) == ((old_trf + 1) & 3):
                film_purity += 1
            else:
                video_purity += 1
        old_trf = trf

    if total == 0:
        return None

    return RepeatPictResult(
        total_frames=total,
        repeat_pict_0=rp_0,
        repeat_pict_1=rp_1,
        repeat_pict_other=rp_other,
        interlaced_frames=interlaced,
        progressive_frames=progressive,
        film_purity=film_purity,
        video_purity=video_purity,
    )


def _run_idet_analysis(video_path: str, runner) -> IdetResult | None:
    """
    Layer 2: Run ffmpeg idet filter on the whole file for pixel-level detection.

    Parses stderr line-by-line (modeled after the working Remux-Toolkit
    telecine_detector). Uses multi-frame detection as primary metric.

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

    tff_bff_re = re.compile(
        r"TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
    )
    repeated_re = re.compile(r"Neither:\s*(\d+)\s*Top:\s*(\d+)\s*Bottom:\s*(\d+)")

    for line in stderr.splitlines():
        if "Repeated Fields:" in line:
            after = line.split("Repeated Fields:", 1)[1]
            m = repeated_re.search(after)
            if m:
                repeated_neither = int(m.group(1))
                repeated_top = int(m.group(2))
                repeated_bottom = int(m.group(3))
                found_any = True

        elif "Single frame detection:" in line:
            after = line.split("Single frame detection:", 1)[1]
            m = tff_bff_re.search(after)
            if m:
                single_tff = int(m.group(1))
                single_bff = int(m.group(2))
                single_prog = int(m.group(3))
                single_undet = int(m.group(4))
                found_any = True

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
        stderr_lines = stderr.splitlines()
        runner._log_message(
            f"[ContentAnalysis] stderr has {len(stderr_lines)} lines, "
            f"last 5: {stderr_lines[-5:] if len(stderr_lines) >= 5 else stderr_lines}"
        )
        return None

    total_frames = multi_tff + multi_bff + multi_prog + multi_undet
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

    IMPORTANT: idet CANNOT reliably distinguish hard telecine from native
    interlaced. Both produce frames with combing artifacts that idet detects
    as "interlaced". The key difference is the 3:2 pulldown cadence, which
    idet does not track. Therefore:

    - If Layer 1 (repeat_pict) already returned a result, we don't reach here
    - If we're here, repeat_pict didn't find pulldown flags
    - Without pulldown flags AND without pixel-level cadence detection,
      we CANNOT reliably say content is telecine vs native interlaced
    - The safe default is "interlaced" (bwdif deinterlace works acceptably
      for both; IVTC on native interlaced produces corrupted output)

    Decision tree:
    - Progressive >= 90% on DVD at ~30fps -> telecine_soft (film)
    - Interlaced > progressive -> interlaced (NOT telecine_hard)
    - Progressive > interlaced -> progressive
    - Otherwise -> mixed
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

    interlaced_count = idet.multi_tff + idet.multi_bff
    interlaced_ratio = interlaced_count / total
    progressive_ratio = idet.multi_progressive / total
    repeated_count = idet.repeated_top + idet.repeated_bottom
    repeated_ratio = repeated_count / total

    if idet.multi_tff > idet.multi_bff:
        field_order: FieldOrderStr = "tff"
    elif idet.multi_bff > idet.multi_tff:
        field_order = "bff"
    else:
        field_order = "progressive"

    is_dvd_30fps = props.get("is_dvd", False) and abs(props.get("fps", 0) - 29.97) < 0.1

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

    content_type: ContentTypeStr
    confidence: float

    if progressive_ratio >= 0.9:
        if is_dvd_30fps:
            content_type = "telecine_soft"
            confidence = 0.90
        else:
            content_type = "progressive"
            confidence = min(0.95, progressive_ratio)
    elif progressive_ratio > 0.7 and repeated_ratio > 0.3:
        content_type = "telecine_soft"
        confidence = min(0.90, progressive_ratio)
    elif interlaced_count > idet.multi_progressive:
        content_type = "interlaced"
        confidence = min(0.90, interlaced_ratio)
    elif idet.multi_progressive > interlaced_count:
        content_type = "progressive"
        confidence = min(0.95, progressive_ratio)
    else:
        content_type = "mixed"
        confidence = 0.7

    runner._log_message(
        f"[ContentAnalysis] idet classification: {content_type} "
        f"(confidence={confidence:.0%})"
    )

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
    For interlaced MPEG-2 DVD, classify as interlaced (NOT telecine_hard) because
    without flag-based or pixel-based confirmation, we cannot distinguish native
    interlaced from hard telecine. The safe default is interlaced (bwdif works
    acceptably; IVTC on native interlaced produces corruption).
    """
    is_dvd = props.get("is_dvd", False)
    fps = props.get("fps", 0)
    interlaced = props.get("interlaced", False)
    field_order = props.get("field_order", "progressive")

    if is_dvd and abs(fps - 29.97) < 0.1:
        if interlaced:
            content_type: ContentTypeStr = "interlaced"
            confidence = 0.65
        else:
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
