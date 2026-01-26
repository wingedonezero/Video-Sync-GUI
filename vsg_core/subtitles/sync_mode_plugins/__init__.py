# vsg_core/subtitles/sync_mode_plugins/__init__.py
# -*- coding: utf-8 -*-
"""
Sync mode plugin implementations.

Each plugin implements the SyncPlugin interface from sync_modes
and handles a specific synchronization algorithm.

Plugins are registered via decorator when imported.

Note: Imports are done lazily to avoid circular imports with sync_modes.
"""
import importlib

# Module mapping for lazy loading
_MODULE_MAP = {
    'TimeBasedSync': ('time_based', 'TimeBasedSync'),
    'TimebaseFrameLockedSync': ('timebase_frame_locked', 'TimebaseFrameLockedSync'),
    'DurationAlignSync': ('duration_align', 'DurationAlignSync'),
    'CorrelationFrameSnapSync': ('correlation_frame_snap', 'CorrelationFrameSnapSync'),
    'SubtitleAnchoredFrameSnapSync': ('subtitle_anchored_frame_snap', 'SubtitleAnchoredFrameSnapSync'),
    'CorrelationGuidedFrameAnchorSync': ('correlation_guided_frame_anchor', 'CorrelationGuidedFrameAnchorSync'),
    'VideoVerifiedSync': ('video_verified', 'VideoVerifiedSync'),
}

_SUBMODULES = [
    'time_based',
    'timebase_frame_locked',
    'duration_align',
    'correlation_frame_snap',
    'subtitle_anchored_frame_snap',
    'correlation_guided_frame_anchor',
    'video_verified',
]

# Cache for loaded modules
_loaded_modules = {}


def __getattr__(name):
    """Lazy import to avoid circular imports."""
    # Check if it's a class name
    if name in _MODULE_MAP:
        module_name, class_name = _MODULE_MAP[name]
        full_module = f'vsg_core.subtitles.sync_mode_plugins.{module_name}'
        if full_module not in _loaded_modules:
            _loaded_modules[full_module] = importlib.import_module(full_module)
        return getattr(_loaded_modules[full_module], class_name)

    # Check if it's a submodule name
    if name in _SUBMODULES:
        full_module = f'vsg_core.subtitles.sync_mode_plugins.{name}'
        if full_module not in _loaded_modules:
            _loaded_modules[full_module] = importlib.import_module(full_module)
        return _loaded_modules[full_module]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'TimeBasedSync',
    'TimebaseFrameLockedSync',
    'DurationAlignSync',
    'CorrelationFrameSnapSync',
    'SubtitleAnchoredFrameSnapSync',
    'CorrelationGuidedFrameAnchorSync',
    'VideoVerifiedSync',
]
