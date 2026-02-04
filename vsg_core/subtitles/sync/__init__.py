# vsg_core/subtitles/sync/__init__.py
"""
Shared sync business logic modules.

These are pure functions that implement sync algorithms,
called by sync plugins and the subtitles step.
"""

from .delay import DelayResult, apply_delay

__all__ = [
    "DelayResult",
    "apply_delay",
]
