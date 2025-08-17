from __future__ import annotations
from typing import List, Tuple
from ..utils.proc import run_command

def run_mkvmerge_with_tokens(argv: List[str]) -> Tuple[int, str, str]:
    """Execute mkvmerge with the given argv list (JSON token array)."""
    return run_command(argv)
