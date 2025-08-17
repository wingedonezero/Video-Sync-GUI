from __future__ import annotations
import subprocess
from typing import List, Tuple

def run_command(argv: List[str]) -> Tuple[int, str, str]:
    """Run a subprocess and capture (returncode, stdout, stderr).

    The GUI should print a compact `$ <cmd>` line and throttle progress lines.
    """
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr
