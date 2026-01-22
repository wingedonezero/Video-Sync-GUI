# vsg_core/subtitles/sync_modes/plugins/__init__.py
# -*- coding: utf-8 -*-
"""Sync mode plugins for SubtitleData."""

from .timebase_frame_locked import TimebaseFrameLockedSync
from .time_based import TimeBasedSync

__all__ = ['TimebaseFrameLockedSync', 'TimeBasedSync']
