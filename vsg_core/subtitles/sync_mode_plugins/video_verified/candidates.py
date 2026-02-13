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
    """
    Select checkpoint times evenly distributed across the video.

    Places checkpoints at evenly-spaced intervals within the middle 80%
    of the video (10% to 90%), avoiding the very start and end where
    intros/outros may differ between sources.

    For 9 checkpoints this produces: [10%, 20%, 30%, 40%, 50%, 60%, 70%, 80%, 90%]
    """
    checkpoints = []

    # Evenly space within 10%-90% of video duration
    margin_pct = 10
    start_pct = margin_pct
    end_pct = 100 - margin_pct
    span_pct = end_pct - start_pct  # 80

    for i in range(num_checkpoints):
        # Center each checkpoint in its segment
        pos = start_pct + span_pct * (i + 0.5) / num_checkpoints
        time_ms = duration_ms * pos / 100
        checkpoints.append(time_ms)

    return checkpoints
