# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List
from ..io.runner import CommandRunner
from .tracks import get_stream_info

def extract_attachments(mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, role: str) -> List[str]:
    info = get_stream_info(mkv, runner, tool_paths)
    if not info:
        return []

    files, specs = [], []
    font_count = 0
    total_attachments = len((info or {}).get('attachments', []))

    for attachment in (info or {}).get('attachments', []):
        mime_type = attachment.get('content_type', '').lower()

        # --- The New Filter Logic ---
        # Only include attachments whose MIME type is a known font type.
        is_font = mime_type.startswith(('font/', 'application/font-', 'application/x-font'))

        if is_font:
            font_count += 1
            out_path = temp_dir / f"{role}_att_{attachment['id']}_{attachment['file_name']}"
            specs.append(f"{attachment['id']}:{out_path}")
            files.append(str(out_path))

    if specs:
        runner._log_message(f"[Attachments] Found {total_attachments} attachments, extracting {font_count} font file(s)...")
        runner.run(['mkvextract', str(mkv), 'attachments'] + specs, tool_paths)
    else:
        runner._log_message(f"[Attachments] Found {total_attachments} attachments, but none were identified as fonts.")

    return files
