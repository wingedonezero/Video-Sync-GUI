# vsg_core/pipeline_components/output_writer.py
"""
Output writer component.

Handles writing mkvmerge options files and managing output paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..io.runner import CommandRunner

if TYPE_CHECKING:
    from vsg_core.models import AppSettings


class OutputWriter:
    """Writes output files and mkvmerge configuration."""

    @staticmethod
    def write_mkvmerge_options(
        tokens: list[str], temp_dir: Path, settings: AppSettings, runner: CommandRunner
    ) -> str:
        """
        Writes mkvmerge options to a JSON file.

        Args:
            tokens: List of mkvmerge command arguments
            temp_dir: Temporary directory for options file
            settings: AppSettings for logging preferences
            runner: CommandRunner for logging

        Returns:
            Path to the written options file

        Raises:
            IOError: If writing the file fails
        """
        opts_path = temp_dir / "opts.json"

        try:
            opts_path.write_text(
                json.dumps(tokens, ensure_ascii=False), encoding="utf-8"
            )

            # Optional logging
            if settings.log_show_options_json:
                runner._log_message(
                    "--- mkvmerge options (json) ---\n"
                    + json.dumps(tokens, indent=2, ensure_ascii=False)
                    + "\n-------------------------------"
                )

            if settings.log_show_options_pretty:
                runner._log_message(
                    "--- mkvmerge options (pretty) ---\n"
                    + " \\\n  ".join(tokens)
                    + "\n-------------------------------"
                )

            return str(opts_path)

        except Exception as e:
            raise OSError(f"Failed to write mkvmerge options file: {e}")

    @staticmethod
    def prepare_output_path(output_dir: Path, source1_filename: str) -> Path:
        """
        Prepares the final output path.

        Args:
            output_dir: Output directory
            source1_filename: Name of the reference source file

        Returns:
            Path for the final output file
        """
        return output_dir / source1_filename
