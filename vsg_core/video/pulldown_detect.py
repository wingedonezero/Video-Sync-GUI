# vsg_core/video/pulldown_detect.py
"""High-level pulldown detection for pipeline use.

Wraps the low-level MPEG-2 bitstream scanner with quick-reject checks
so we only do the expensive ES scan when the track is a plausible
candidate for soft pulldown removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vsg_core.video.mpeg2_pulldown import PulldownScanResult, scan_for_pulldown

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class PulldownDetection:
    """Complete pulldown detection result for pipeline use."""

    detected: bool  # True if soft pulldown is present
    safe_to_remove: bool  # True if removal is safe
    codec_id: str  # "V_MPEG2" etc.
    source_fps: float  # Current stream fps (from scan)
    target_fps: float | None  # FPS after removal (None if not applicable)
    scan_result: PulldownScanResult | None  # Full scan details (None if skipped)
    reason: str  # Why detected/not detected/not safe


# MPEG-2 frame rates from ISO 13818-2 (duplicated here to avoid circular import)
_FRAME_RATES: dict[int, float] = {
    1: 24000.0 / 1001.0,
    2: 24.0,
    3: 25.0,
    4: 30000.0 / 1001.0,
    5: 30.0,
    6: 50.0,
    7: 60000.0 / 1001.0,
    8: 60.0,
}


def detect_pulldown(
    extracted_path: Path,
    codec_id: str,
    log: Callable[[str], None],
) -> PulldownDetection:
    """Determine if an extracted video track has removable soft pulldown.

    Quick-reject checks are applied first to avoid scanning non-MPEG-2
    streams or files that clearly can't have pulldown. If quick checks
    pass, the full bitstream scan is performed.

    Args:
        extracted_path: Path to the extracted elementary stream (.mpg).
        codec_id: The codec ID from mkvmerge (e.g., "V_MPEG2").
        log: Logging callback for status messages.

    Returns:
        PulldownDetection with detection results and details.
    """
    # Quick reject 1: Must be MPEG-2
    if codec_id != "V_MPEG2":
        return PulldownDetection(
            detected=False,
            safe_to_remove=False,
            codec_id=codec_id,
            source_fps=0,
            target_fps=None,
            scan_result=None,
            reason=f"Not MPEG-2 (codec: {codec_id})",
        )

    # Quick reject 2: File must exist and be non-empty
    if not extracted_path.exists():
        return PulldownDetection(
            detected=False,
            safe_to_remove=False,
            codec_id=codec_id,
            source_fps=0,
            target_fps=None,
            scan_result=None,
            reason=f"File not found: {extracted_path}",
        )

    file_size = extracted_path.stat().st_size
    if file_size == 0:
        return PulldownDetection(
            detected=False,
            safe_to_remove=False,
            codec_id=codec_id,
            source_fps=0,
            target_fps=None,
            scan_result=None,
            reason="File is empty",
        )

    # Quick reject 3: Must be a .mpg file
    if extracted_path.suffix.lower() != ".mpg":
        return PulldownDetection(
            detected=False,
            safe_to_remove=False,
            codec_id=codec_id,
            source_fps=0,
            target_fps=None,
            scan_result=None,
            reason=f"Unexpected extension: {extracted_path.suffix} (expected .mpg)",
        )

    # Full scan
    log(
        f"[Pulldown] Scanning MPEG-2 stream for soft pulldown: "
        f"{extracted_path.name} ({file_size / (1024 * 1024):.1f} MB)"
    )

    scan = scan_for_pulldown(extracted_path)

    source_fps = _FRAME_RATES.get(scan.original_frame_rate_index, 0)
    target_fps = (
        _FRAME_RATES.get(scan.target_frame_rate_index, 0)
        if scan.target_frame_rate_index is not None
        else None
    )

    if not scan.has_pulldown:
        log("[Pulldown] No pulldown flags found in stream")
        return PulldownDetection(
            detected=False,
            safe_to_remove=False,
            codec_id=codec_id,
            source_fps=source_fps,
            target_fps=None,
            scan_result=scan,
            reason=scan.reason,
        )

    if scan.is_safe_to_remove:
        rff_pct = (
            (scan.rff_count / scan.total_pictures * 100.0) if scan.total_pictures else 0
        )
        if target_fps:
            log(
                f"[Pulldown] Soft pulldown detected and safe to remove: "
                f"{scan.rff_count}/{scan.total_pictures} frames have RFF ({rff_pct:.1f}%), "
                f"{source_fps:.3f} fps -> {target_fps:.3f} fps, "
                f"{scan.progressive_pct:.1f}% progressive"
            )
        else:
            log(f"[Pulldown] Soft pulldown detected: {scan.rff_count} RFF frames")
        if scan.non_progressive_count > 0:
            log(
                f"[Pulldown] Note: {scan.non_progressive_count} non-progressive "
                f"frames ({100.0 - scan.progressive_pct:.1f}%) — likely interlaced "
                f"inserts (credits/OP/ED). RFF will be cleared on all frames."
            )
    else:
        log(f"[Pulldown] Pulldown detected but NOT safe to remove: {scan.reason}")

    return PulldownDetection(
        detected=scan.has_pulldown,
        safe_to_remove=scan.is_safe_to_remove,
        codec_id=codec_id,
        source_fps=source_fps,
        target_fps=target_fps,
        scan_result=scan,
        reason=scan.reason,
    )
