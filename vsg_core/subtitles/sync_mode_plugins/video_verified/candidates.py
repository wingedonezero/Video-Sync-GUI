# vsg_core/subtitles/sync_mode_plugins/video_verified/candidates.py
"""
Frame candidate generation and checkpoint selection for video-verified sync.
"""

from __future__ import annotations


def generate_frame_candidates(
    correlation_frames: float, search_range_frames: int
) -> list[int]:
    """
    Generate candidate frame offsets to test, centered on the correlation value.

    This works for any offset size - small (< 3 frames) or large (24+ frames).
    We search in a window around the correlation-derived frame offset.

    Args:
        correlation_frames: Audio correlation converted to frames (can be fractional)
        search_range_frames: How many frames on each side to search

    Returns:
        Sorted list of integer frame offsets to test
    """
    candidates = set()

    # Round correlation to nearest frame
    base_frame = int(round(correlation_frames))

    # Always include zero (in case correlation is just wrong)
    candidates.add(0)

    # Search window around correlation
    for delta in range(-search_range_frames, search_range_frames + 1):
        candidates.add(base_frame + delta)

    return sorted(candidates)


def select_checkpoint_times(duration_ms: float, num_checkpoints: int) -> list[float]:
    """Select checkpoint times distributed across the video."""
    checkpoints = []

    # Use percentage-based positions (avoiding very start/end)
    positions = [15, 30, 50, 70, 85][:num_checkpoints]

    for pos in positions:
        time_ms = duration_ms * pos / 100
        checkpoints.append(time_ms)

    return checkpoints
