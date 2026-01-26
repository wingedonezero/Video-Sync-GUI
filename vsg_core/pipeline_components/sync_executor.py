# vsg_core/pipeline_components/sync_executor.py
# -*- coding: utf-8 -*-
"""
Sync executor component.

Handles merge execution and post-processing finalization.
"""

import hashlib
import shutil
from pathlib import Path
from typing import Dict

from ..io.runner import CommandRunner
from ..postprocess import finalize_merged_file, check_if_rebasing_is_needed


def _file_hash(path: Path) -> str:
    """Compute MD5 hash of a file for debugging."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


class SyncExecutor:
    """Executes sync merges and finalizes output."""

    @staticmethod
    def execute_merge(
        mkvmerge_options_path: str,
        tool_paths: Dict[str, str],
        runner: CommandRunner
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
        result = runner.run(['mkvmerge', f'@{mkvmerge_options_path}'], tool_paths)
        return result is not None

    @staticmethod
    def finalize_output(
        temp_output_path: Path,
        final_output_path: Path,
        config: dict,
        tool_paths: Dict[str, str],
        runner: CommandRunner
    ):
        """
        Finalizes the merged output file.

        Handles timestamp normalization if enabled and needed, otherwise
        simply moves the file to its final location.

        Args:
            temp_output_path: Path to temporary merged file
            final_output_path: Path to final output location
            config: Configuration dictionary
            tool_paths: Dictionary of tool paths
            runner: CommandRunner for execution
        """
        normalize_enabled = config.get('post_mux_normalize_timestamps', False)

        # DEBUG: Log file hash before any processing
        temp_path = Path(temp_output_path)
        if temp_path.exists():
            pre_hash = _file_hash(temp_path)
            pre_size = temp_path.stat().st_size
            runner._log_message(f"[DEBUG] temp_1.mkv BEFORE move: hash={pre_hash}, size={pre_size}")

        if normalize_enabled and check_if_rebasing_is_needed(temp_output_path, runner, tool_paths):
            runner._log_message(f"[DEBUG] Running FFmpeg normalization (normalize_enabled={normalize_enabled})")
            finalize_merged_file(temp_output_path, final_output_path, runner, config, tool_paths)
        else:
            runner._log_message(f"[DEBUG] Simple move (no normalization, normalize_enabled={normalize_enabled})")
            shutil.move(temp_output_path, final_output_path)

        # DEBUG: Log file hash after processing
        final_path = Path(final_output_path)
        if final_path.exists():
            post_hash = _file_hash(final_path)
            post_size = final_path.stat().st_size
            runner._log_message(f"[DEBUG] final output AFTER move: hash={post_hash}, size={post_size}")
            if temp_path.exists() or pre_hash:
                if pre_hash == post_hash:
                    runner._log_message(f"[DEBUG] ✓ File unchanged (hashes match)")
                else:
                    runner._log_message(f"[DEBUG] ✗ FILE MODIFIED! Hashes differ!")
