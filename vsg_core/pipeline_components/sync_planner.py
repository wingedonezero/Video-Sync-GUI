# vsg_core/pipeline_components/sync_planner.py
# -*- coding: utf-8 -*-
"""
Sync planner component.

Wraps the Orchestrator to provide a cleaner interface for sync planning.
"""

from typing import Dict, List, Optional, Callable, Any

from ..orchestrator.pipeline import Orchestrator


class SyncPlanner:
    """Plans sync operations by delegating to the Orchestrator."""

    @staticmethod
    def plan_sync(
        config: dict,
        tool_paths: Dict[str, str],
        log_callback: Callable[[str], None],
        progress_callback: Callable[[float], None],
        sources: Dict[str, str],
        and_merge: bool,
        output_dir: str,
        manual_layout: List[Dict],
        attachment_sources: List[str]
    ) -> Any:
        """
        Plans the sync operation by analyzing sources and preparing merge tokens.

        This wraps the existing Orchestrator to provide a cleaner interface.

        Args:
            config: Configuration dictionary
            tool_paths: Dictionary of tool paths
            log_callback: Logging callback function
            progress_callback: Progress callback function
            sources: Dictionary mapping source names to file paths
            and_merge: Whether to prepare for merging
            output_dir: Output directory path
            manual_layout: Manual layout configuration
            attachment_sources: List of attachment source paths

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
            settings_dict=config,
            tool_paths=tool_paths,
            log=log_callback,
            progress=progress_callback,
            sources=sources,
            and_merge=and_merge,
            output_dir=output_dir,
            manual_layout=manual_layout,
            attachment_sources=attachment_sources
        )
