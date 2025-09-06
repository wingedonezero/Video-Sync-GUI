# -*- coding: utf-8 -*-
from pathlib import Path
import re
from typing import Tuple

from ..io.runner import CommandRunner

def run_videodiff(ref_file: str, target_file: str, config: dict, runner: CommandRunner, tool_paths: dict) -> Tuple[int, float]:
    videodiff_path = config.get('videodiff_path') or tool_paths.get('videodiff', 'videodiff')
    if not Path(videodiff_path).exists():
        raise FileNotFoundError(f"videodiff executable not found at '{videodiff_path}'")

    out = runner.run([str(videodiff_path), str(ref_file), str(target_file)], tool_paths)
    if not out:
        raise RuntimeError('videodiff produced no output or failed to run.')

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    last_line = ''
    for ln in reversed(lines):
        if '[Result]' in ln and ('ss:' in ln or 'itsoffset:' in ln):
            last_line = ln
            break

    if not last_line:
        raise RuntimeError(f"Could not find a valid '[Result]' line in videodiff output.")

    m = re.search(r'(itsoffset|ss)\s*:\s*(-?\d+(?:\.\d+)?)s.*?error:\s*([0-9.]+)', last_line, flags=re.IGNORECASE)
    if not m:
        raise RuntimeError(f"Could not parse videodiff result line: '{last_line}'")

    kind, s_val, err_val = m.groups()
    seconds = float(s_val)
    delay_ms = int(round(seconds * 1000))
    if kind.lower() == 'ss':
        delay_ms = -delay_ms

    error_value = float(err_val)
    runner._log_message(f'[VideoDiff] Result -> {kind.lower()} {seconds:.5f}s, error {error_value:.2f} => delay {delay_ms:+} ms')
    return delay_ms, error_value
