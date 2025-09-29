# vsg_core/subtitles/ocr.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Optional

from ..io.runner import CommandRunner

def run_ocr(
    subtitle_path: str,
    lang: str,
    runner: CommandRunner,
    tool_paths: dict,
    config: dict,
) -> Optional[str]:
    """
    Runs the subtile-ocr tool on an image-based subtitle file (IDX/SUB).

    Args:
        subtitle_path: Path to the .idx file.
        lang: The 3-letter language code for OCR (e.g., 'eng').
        runner: The CommandRunner instance.
        tool_paths: A dictionary of tool paths.
        config: The application's configuration dictionary.

    Returns:
        The path to the generated SRT file, or None on failure.
    """
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() != '.idx':
        runner._log_message(f"[OCR] Skipping {sub_path.name}: Not an IDX file.")
        return None

    ocr_tool_path = config.get('subtile_ocr_path') or tool_paths.get('subtile-ocr')
    if not ocr_tool_path:
        runner._log_message("[OCR] ERROR: 'subtile-ocr' tool path is not configured or found in PATH.")
        return None

    output_path = sub_path.with_suffix('.srt')
    runner._log_message(f"[OCR] Performing OCR on {sub_path.name}...")

    cmd = [
        ocr_tool_path,
        '--lang', lang,
        '--output', str(output_path),
        str(sub_path)
    ]

    blacklist = config.get('subtile_ocr_char_blacklist', '').strip()
    if blacklist:
        cmd.extend(['--config', f"tessedit_char_blacklist='{blacklist}'"])

    result = runner.run(cmd, tool_paths)

    if result is not None and output_path.exists():
        runner._log_message(f"[OCR] Successfully created {output_path.name}")
        return str(output_path)
    else:
        runner._log_message(f"[OCR] ERROR: Failed to perform OCR on {sub_path.name}.")
        return None
