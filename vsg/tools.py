"""External tool discovery and command runner."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict

from vsg.logbus import _log

try:
    from vsg.settings import CONFIG
except Exception:
    CONFIG = {}

ABS: Dict[str, str] = {}


def _resolve_tool(name: str) -> str | None:
    key = f"{name}_path"
    if isinstance(CONFIG, dict):
        p = CONFIG.get(key)
        if p and Path(p).exists():
            return str(Path(p).resolve())
    p = shutil.which(name)
    if p:
        return p
    here = Path(".") / name
    if here.exists() and os.access(here, os.X_OK):
        return str(here.resolve())
    return None


def find_required_tools() -> bool:
    required = ["ffmpeg", "ffprobe", "mkvmerge", "mkvextract"]
    optional = ["videodiff"]
    missing = []
    for name in required + optional:
        p = _resolve_tool(name)
        if p:
            ABS[name] = p
        elif name in required:
            missing.append(name)
    if missing:
        _log("Missing tools:", ", ".join(missing))
        return False
    _log("Tools ready:", ", ".join(f"{k}={v}" for k, v in ABS.items()))
    return True


def run_command(cmd: list[str]) -> int:
    _log("$", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last = 0.0
    for line in proc.stdout or []:
        line = (line or "").rstrip()
        if not line:
            continue
        if re.match(r"^Progress", line):
            now = time.time()
            if now - last > 1.0:
                _log(line)
                last = now
        else:
            _log(line)
    return proc.wait()
