"""Moved implementations for mux.run (full-move RC)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
import os, re, json, math, logging, subprocess, tempfile, pathlib
from pathlib import Path

from vsg.logbus import _log
from vsg.settings import CONFIG
from vsg.tools import run_command, find_required_tools
def write_mkvmerge_json_options(tokens: List[str], json_path: Path, logger) -> str:
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    raw_json = json.dumps(tokens, ensure_ascii=False)
    json_path.write_text(raw_json, encoding='utf-8')
    pretty_path = json_path.parent / 'opts.pretty.txt'
    pretty_txt = ' \\n  '.join(tokens)
    pretty_path.write_text(pretty_txt, encoding='utf-8')
    _log(logger, f'@JSON options written: {json_path}')
    if CONFIG.get('log_show_options_pretty', False):
        _log(logger, '[OPTIONS] mkvmerge tokens (pretty):')
        for line in pretty_txt.splitlines():
            _log(logger, '  ' + line)
    if CONFIG.get('log_show_options_json', False):
        _log(logger, '[OPTIONS] mkvmerge tokens (raw JSON array):')
        for i in range(0, len(raw_json), 512):
            _log(logger, raw_json[i:i + 512])
    return str(json_path)


def run_mkvmerge_with_json(json_path: str, logger) -> bool:
    out = run_command(['mkvmerge', f'@{json_path}'], logger)
    return out is not None

