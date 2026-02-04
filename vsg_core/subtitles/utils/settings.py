# vsg_core/subtitles/utils/settings.py
"""
Settings utilities for subtitle processing.

Consolidates duplicate settings validation from:
- sync_mode_plugins/timebase_frame_locked.py
- sync_mode_plugins/correlation_frame_snap.py
- sync_mode_plugins/correlation_guided_frame_anchor.py
- sync_mode_plugins/subtitle_anchored_frame_snap.py
- sync_mode_plugins/duration_align.py
- sync_mode_plugins/time_based.py
- sync_mode_plugins/video_verified.py (2 instances)
- orchestrator/pipeline.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.settings import AppSettings


def ensure_settings(settings: AppSettings | None) -> AppSettings:
    """
    Ensure we have valid AppSettings, creating defaults if None.

    This replaces the duplicate pattern found in 9+ locations:
        if settings is None:
            settings = AppSettings.from_config({})

    Args:
        settings: AppSettings instance or None

    Returns:
        Valid AppSettings instance (input or new default)
    """
    if settings is None:
        from ...models.settings import AppSettings

        return AppSettings.from_config({})
    return settings
