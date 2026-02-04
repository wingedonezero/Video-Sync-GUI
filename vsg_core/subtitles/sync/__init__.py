# vsg_core/subtitles/sync/__init__.py
"""
Shared sync business logic modules.

These are pure functions that implement sync algorithms,
called by sync plugins and the subtitles step.
"""

from .delay import DelayResult, apply_delay
from .frame_matching import (
    DEFAULT_CHECKPOINT_POSITIONS,
    OffsetAgreement,
    VideoReaderPair,
    calculate_median_offset,
    check_offset_agreement,
    generate_frame_candidates,
    log_checkpoint_times,
    open_video_readers,
    select_checkpoint_times,
)

__all__ = [
    "DEFAULT_CHECKPOINT_POSITIONS",
    "DelayResult",
    "OffsetAgreement",
    "VideoReaderPair",
    "apply_delay",
    "calculate_median_offset",
    "check_offset_agreement",
    "generate_frame_candidates",
    "log_checkpoint_times",
    "open_video_readers",
    "select_checkpoint_times",
]
