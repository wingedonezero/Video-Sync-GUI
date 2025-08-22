
"""External tool discovery and command runner."""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional

from vsg.logbus import _log

try:
    from vsg.settings import CONFIG  # legacy fallback
except Exception:
    CONFIG: Dict[str, str] = {}

def find_tool(name: str, override_path: Optional[str]) -> Optional[str]:
    if override_path:
        return override_path
    return shutil.which(name)

def run_command(cmd: List[str], logger: Optional[object] = None, *, echo: bool = True) -> Optional[int]:
    """Run a command, streaming stdout to _log. Returns exit code or None on failure."""
    try:
        if echo:
            _log("Run:", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        last = 0.0
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break
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
    except FileNotFoundError:
        _log("Tool not found:", cmd[0])
        return None
    except Exception as e:
        _log("Command failed:", repr(e))
        return None
