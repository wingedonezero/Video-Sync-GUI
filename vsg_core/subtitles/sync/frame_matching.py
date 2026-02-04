# vsg_core/subtitles/sync/frame_matching.py
"""
Shared frame matching utilities for sync plugins.

This module consolidates common frame matching patterns found in:
- video_verified.py (checkpoint selection, offset agreement)
- subtitle_anchored_frame_snap.py (checkpoint selection, median calculation)
- correlation_guided_frame_anchor.py (offset agreement, median calculation)

All functions are pure and stateless - no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..frame_utils import VideoReader


# Default checkpoint positions as percentage of video duration
DEFAULT_CHECKPOINT_POSITIONS = (15, 30, 50, 70, 85)


@dataclass(frozen=True, slots=True)
class OffsetAgreement:
    """Result of checking offset agreement."""

    offsets_agree: bool
    offset_range_ms: float
    median_offset_ms: float
    sorted_offsets: tuple[float, ...]


def select_checkpoint_times(
    duration_ms: float,
    num_checkpoints: int,
    positions: tuple[int, ...] = DEFAULT_CHECKPOINT_POSITIONS,
) -> list[float]:
    """
    Select checkpoint times distributed across a video duration.

    Uses percentage-based positions to avoid very start/end where
    there may be logos, black frames, or other non-representative content.

    Args:
        duration_ms: Total video duration in milliseconds
        num_checkpoints: Number of checkpoints to return
        positions: Tuple of percentage positions (default: 15, 30, 50, 70, 85)

    Returns:
        List of checkpoint times in milliseconds
    """
    checkpoints = []
    for pos in positions[:num_checkpoints]:
        time_ms = duration_ms * pos / 100
        checkpoints.append(time_ms)
    return checkpoints


def calculate_median_offset(offsets: list[float]) -> float:
    """
    Calculate median offset from a list of offset measurements.

    Uses simple median calculation (middle element of sorted list).
    For even-length lists, returns the lower middle element.

    Args:
        offsets: List of offset measurements in milliseconds

    Returns:
        Median offset in milliseconds

    Raises:
        ValueError: If offsets list is empty
    """
    if not offsets:
        raise ValueError("Cannot calculate median of empty list")

    sorted_offsets = sorted(offsets)
    return sorted_offsets[len(sorted_offsets) // 2]


def check_offset_agreement(
    offsets: list[float],
    tolerance_ms: float,
) -> OffsetAgreement:
    """
    Check if a list of offset measurements agree within tolerance.

    Agreement is determined by the range (max - min) being within tolerance.
    Also calculates the median offset for use when offsets agree.

    Args:
        offsets: List of offset measurements in milliseconds
        tolerance_ms: Maximum allowed range for agreement

    Returns:
        OffsetAgreement with agreement status, range, median, and sorted offsets

    Raises:
        ValueError: If offsets list is empty
    """
    if not offsets:
        raise ValueError("Cannot check agreement of empty list")

    sorted_offsets = tuple(sorted(offsets))
    offset_range = sorted_offsets[-1] - sorted_offsets[0]
    offsets_agree = offset_range <= tolerance_ms
    median_offset = sorted_offsets[len(sorted_offsets) // 2]

    return OffsetAgreement(
        offsets_agree=offsets_agree,
        offset_range_ms=offset_range,
        median_offset_ms=median_offset,
        sorted_offsets=sorted_offsets,
    )


def generate_frame_candidates(
    correlation_frames: float,
    search_range_frames: int,
    *,
    include_zero: bool = True,
) -> list[int]:
    """
    Generate candidate frame offsets to test, centered on the correlation value.

    Creates a window of integer frame offsets around the correlation-derived
    frame offset. Always includes the correlation value rounded to nearest frame.

    Args:
        correlation_frames: Audio correlation converted to frames (can be fractional)
        search_range_frames: How many frames on each side to search
        include_zero: Whether to always include 0 as a candidate (default True)

    Returns:
        Sorted list of integer frame offsets to test
    """
    candidates = set()

    # Round correlation to nearest frame
    base_frame = int(round(correlation_frames))

    # Optionally include zero (in case correlation is just wrong)
    if include_zero:
        candidates.add(0)

    # Search window around correlation
    for delta in range(-search_range_frames, search_range_frames + 1):
        candidates.add(base_frame + delta)

    return sorted(candidates)


@dataclass(frozen=True, slots=True)
class VideoReaderPair:
    """Container for source and target video readers."""

    source: VideoReader
    target: VideoReader

    def close(self) -> None:
        """Close both readers, ignoring errors."""
        try:
            self.source.close()
        except Exception:
            pass
        try:
            self.target.close()
        except Exception:
            pass


def open_video_readers(
    source_video: str,
    target_video: str,
    runner,
    *,
    use_vapoursynth: bool = False,
    temp_dir=None,
    deinterlace: str | None = None,
    config: dict | None = None,
) -> VideoReaderPair:
    """
    Open source and target video readers as a pair.

    This is a convenience function that ensures both readers are opened
    together. If the target reader fails to open, the source reader is
    closed before raising.

    Args:
        source_video: Path to source video
        target_video: Path to target video
        runner: CommandRunner for logging
        use_vapoursynth: Whether to use VapourSynth backend
        temp_dir: Temp directory for index files
        deinterlace: Deinterlace mode ('auto', 'yadif', etc.)
        config: Optional config dict for VideoReader

    Returns:
        VideoReaderPair with both readers

    Raises:
        Exception: If either video fails to open
    """
    from ..frame_utils import VideoReader

    # Build kwargs for VideoReader
    kwargs: dict = {"use_vapoursynth": use_vapoursynth}
    if temp_dir is not None:
        kwargs["temp_dir"] = temp_dir
    if deinterlace is not None:
        kwargs["deinterlace"] = deinterlace
    if config is not None:
        kwargs["config"] = config

    source_reader = None
    try:
        source_reader = VideoReader(source_video, runner, **kwargs)
        target_reader = VideoReader(target_video, runner, **kwargs)
        return VideoReaderPair(source=source_reader, target=target_reader)
    except Exception:
        if source_reader is not None:
            try:
                source_reader.close()
            except Exception:
                pass
        raise


def log_checkpoint_times(
    checkpoint_times: list[float],
    log: Callable[[str], None] | None,
    prefix: str = "",
) -> None:
    """
    Log checkpoint times in human-readable format.

    Args:
        checkpoint_times: List of checkpoint times in milliseconds
        log: Optional logging function
        prefix: Log message prefix (e.g., "[VideoVerified]")
    """
    if log is None:
        return

    formatted = [f"{t / 1000:.1f}s" for t in checkpoint_times]
    log(f"{prefix} Checkpoint times: {formatted}")
