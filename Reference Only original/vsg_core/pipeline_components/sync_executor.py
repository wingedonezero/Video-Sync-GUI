# vsg_core/pipeline_components/sync_executor.py
"""
Sync executor component.

Handles merge execution and post-processing finalization.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ..io.runner import CommandRunner
from ..postprocess import check_if_rebasing_is_needed, finalize_merged_file

if TYPE_CHECKING:
    from vsg_core.models import AppSettings


class SyncExecutor:
    """Executes sync merges and finalizes output."""

    @staticmethod
    def execute_merge(
        mkvmerge_options_path: str, tool_paths: dict[str, str], runner: CommandRunner
    ) -> bool:
        """
        Executes mkvmerge with the provided options file.

        Args:
            mkvmerge_options_path: Path to mkvmerge options JSON file
            tool_paths: Dictionary of tool paths
            runner: CommandRunner for execution

        Returns:
            True if merge succeeded, False otherwise
        """
        result = runner.run(["mkvmerge", f"@{mkvmerge_options_path}"], tool_paths)
        return result is not None

    @staticmethod
    def finalize_output(
        temp_output_path: Path,
        final_output_path: Path,
        settings: AppSettings,
        tool_paths: dict[str, str],
        runner: CommandRunner,
    ):
        """
        Finalizes the merged output file.

        Handles timestamp normalization if enabled and needed, otherwise
        simply moves the file to its final location.

        Args:
            temp_output_path: Path to temporary merged file
            final_output_path: Path to final output location
            settings: AppSettings with post-mux options
            tool_paths: Dictionary of tool paths
            runner: CommandRunner for execution
        """
        normalize_enabled = settings.post_mux_normalize_timestamps

        if normalize_enabled and check_if_rebasing_is_needed(
            temp_output_path, runner, tool_paths
        ):
            finalize_merged_file(
                temp_output_path, final_output_path, runner, settings, tool_paths
            )
        else:
            shutil.move(temp_output_path, final_output_path)
