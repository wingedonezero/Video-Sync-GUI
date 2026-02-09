# vsg_core/pipeline_components/sync_planner.py
"""
Sync planner component.

Wraps the Orchestrator to provide a cleaner interface for sync planning.
"""

from collections.abc import Callable
from typing import Any

from ..models.context_types import ManualLayoutItem
from ..models.settings import AppSettings
from ..orchestrator.pipeline import Orchestrator


class SyncPlanner:
    """Plans sync operations by delegating to the Orchestrator."""

    @staticmethod
    def plan_sync(
        settings: AppSettings,
        tool_paths: dict[str, str],
        log_callback: Callable[[str], None],
        progress_callback: Callable[[float], None],
        sources: dict[str, str],
        and_merge: bool,
        output_dir: str,
        manual_layout: list[ManualLayoutItem],
        attachment_sources: list[str],
        source_settings: dict[str, dict[str, Any]] | None = None,
        debug_paths=None,
    ) -> Any:
        """
        Plans the sync operation by analyzing sources and preparing merge tokens.

        This wraps the existing Orchestrator to provide a cleaner interface.

        Args:
            settings: AppSettings instance with all configuration
            tool_paths: Dictionary of tool paths
            log_callback: Logging callback function
            progress_callback: Progress callback function
            sources: Dictionary mapping source names to file paths
            and_merge: Whether to prepare for merging
            output_dir: Output directory path
            manual_layout: Manual layout configuration (typed as ManualLayoutItem)
            attachment_sources: List of attachment source paths
            source_settings: Per-source correlation settings, e.g.:
                {'Source 1': {'correlation_ref_track': 0}, 'Source 2': {'correlation_source_track': 1, 'use_source_separation': True}}
            debug_paths: DebugOutputPaths for this job

        Returns:
            Context object containing:
            - delays: Sync delays
            - tokens: mkvmerge command tokens (if and_merge=True)
            - temp_dir: Temporary directory
            - stepping_sources: Sources with stepping detected
            - stepping_detected_disabled: Sources with stepping detection disabled
        """
        orch = Orchestrator()
        return orch.run(
            settings=settings,
            tool_paths=tool_paths,
            log=log_callback,
            progress=progress_callback,
            sources=sources,
            and_merge=and_merge,
            output_dir=output_dir,
            manual_layout=manual_layout,
            attachment_sources=attachment_sources,
            source_settings=source_settings or {},
            debug_paths=debug_paths,
        )
