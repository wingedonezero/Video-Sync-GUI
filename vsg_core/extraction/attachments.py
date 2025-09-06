# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List
from ..io.runner import CommandRunner
from .tracks import get_stream_info

def extract_attachments(mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, role: str) -> List[str]:
    info = get_stream_info(mkv, runner, tool_paths)
    files, specs = [], []
    for attachment in (info or {}).get('attachments', []):
        out_path = temp_dir / f"{role}_att_{attachment['id']}_{attachment['file_name']}"
        specs.append(f"{attachment['id']}:{out_path}")
        files.append(str(out_path))
    if specs:
        runner.run(['mkvextract', str(mkv), 'attachments'] + specs, tool_paths)
    return files
