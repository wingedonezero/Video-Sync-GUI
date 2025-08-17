from __future__ import annotations
from pathlib import Path
from typing import List, Optional
from .plan import PositiveOnlyDelayPlan
from .settings import AppSettings

def build_mkvmerge_tokens(
    output_path: Path,
    ref_path: Path,
    sec_path: Optional[Path],
    ter_path: Optional[Path],
    plan: PositiveOnlyDelayPlan,
    chapters_xml: Optional[Path],
    settings: Optional[AppSettings],
) -> List[str]:
    """Return a JSON-serializable argv list for mkvmerge.

    Per-file options must appear immediately before that file and be grouped
    with parentheses in the pretty representation (the raw argv does not include
    parentheses as tokens; those are for pretty printing only).
    """
    argv: List[str] = ["mkvmerge", "--output", str(output_path)]
    if chapters_xml is not None:
        argv += ["--chapters", str(chapters_xml)]
    # REF video
    argv += ["--default-track-flag", "0:no", "--compression", "0:none", str(ref_path)]
    # SEC audio
    if sec_path is not None and plan.sec_ms is not None:
        argv += ["--sync", f"0:+{plan.sec_ms}", "--default-track-flag", "0:yes", "--compression", "0:none", str(sec_path)]
    # TER subs
    if ter_path is not None and plan.ter_ms is not None:
        argv += ["--sync", f"0:+{plan.ter_ms}", "--default-track-flag", "0:no", "--compression", "0:none", str(ter_path)]
    return argv

def pretty_print_tokens(argv: List[str]) -> str:
    """Return a human-readable pretty view of argv similar to the logs."""
    out = []
    i = 0
    line = []
    for tok in argv:
        if tok in {"mkvmerge"}:
            continue
        if tok in {"--output", "--chapters", "--sync", "--compression", "--default-track-flag", "--language", "--track-name", "--attach-file"}:
            if line:
                out.append(" ".join(line))
                line = []
        line.append(tok)
    if line:
        out.append(" ".join(line))
    return "\n".join(out)
