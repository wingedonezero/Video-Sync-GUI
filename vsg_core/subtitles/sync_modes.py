# vsg_core/subtitles/sync_modes.py
"""
Subtitle synchronization modes - Plugin system.

Sync modes are plugins that adjust subtitle timing to synchronize
with a target video. All modes work the same way:
1. Receive SubtitleData with float ms timing
2. Apply timing adjustments directly to events
3. Return OperationResult with statistics

Registry pattern allows easy addition of new sync modes.

Plugins are located in: vsg_core/subtitles/sync_mode_plugins/
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.settings import AppSettings
    from .data import OperationResult, SubtitleData


# =============================================================================
# Plugin System
# =============================================================================


class SyncPlugin(ABC):
    """
    Base class for sync mode plugins.

    Each sync mode implements this interface to integrate with SubtitleData.
    """

    # Plugin name (must match what's used in settings)
    name: str = ""

    # Human-readable description
    description: str = ""

    @abstractmethod
    def apply(
        self,
        subtitle_data: SubtitleData,
        total_delay_ms: float,
        global_shift_ms: float,
        target_fps: float | None = None,
        source_video: str | None = None,
        target_video: str | None = None,
        runner=None,
        settings: AppSettings | None = None,
        **kwargs,
    ) -> OperationResult:
        """
        Apply sync to subtitle data.

        This modifies subtitle_data.events in place.

        Args:
            subtitle_data: SubtitleData to modify (float ms timing)
            total_delay_ms: Total delay from correlation/analysis (raw float)
            global_shift_ms: User global shift component (raw float)
            target_fps: Target video FPS
            source_video: Source video path
            target_video: Target video path
            runner: CommandRunner for logging
            settings: AppSettings instance
            **kwargs: Additional mode-specific parameters

        Returns:
            OperationResult with success/failure and statistics
        """
        pass


# Plugin registry
_sync_plugins: dict[str, type[SyncPlugin]] = {}
_plugins_loaded = False


def register_sync_plugin(plugin_class: type[SyncPlugin]) -> type[SyncPlugin]:
    """
    Register a sync plugin.

    Can be used as a decorator:
        @register_sync_plugin
        class MySyncPlugin(SyncPlugin):
            name = 'my-sync'
            ...
    """
    if not plugin_class.name:
        raise ValueError(f"Plugin {plugin_class.__name__} must define a name")
    _sync_plugins[plugin_class.name] = plugin_class
    return plugin_class


def _ensure_plugins_loaded():
    """Lazy-load plugins to avoid circular imports."""
    global _plugins_loaded
    if not _plugins_loaded:
        import importlib

        plugins_to_load = [
            "vsg_core.subtitles.sync_mode_plugins.time_based",
            "vsg_core.subtitles.sync_mode_plugins.timebase_frame_locked",
            "vsg_core.subtitles.sync_mode_plugins.subtitle_anchored_frame_snap",
            "vsg_core.subtitles.sync_mode_plugins.video_verified",
        ]
        for module_name in plugins_to_load:
            importlib.import_module(module_name)
        _plugins_loaded = True


def get_sync_plugin(name: str) -> SyncPlugin | None:
    """
    Get a sync plugin instance by name.

    Args:
        name: Plugin name (e.g., 'timebase-frame-locked-timestamps')

    Returns:
        Plugin instance, or None if not found
    """
    _ensure_plugins_loaded()
    plugin_class = _sync_plugins.get(name)
    if plugin_class:
        return plugin_class()
    return None


def list_sync_plugins() -> dict[str, str]:
    """
    List all registered sync plugins.

    Returns:
        Dict of name -> description
    """
    _ensure_plugins_loaded()
    return {name: cls.description for name, cls in _sync_plugins.items()}


__all__ = [
    "SyncPlugin",
    "get_sync_plugin",
    "list_sync_plugins",
    "register_sync_plugin",
]
