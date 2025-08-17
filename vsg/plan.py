from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class PositiveOnlyDelayPlan:
    global_anchor_ms: int
    ref_ms: int
    sec_ms: Optional[int]
    ter_ms: Optional[int]

def build_positive_only_delays(measured: Dict[str, Optional[int]]) -> PositiveOnlyDelayPlan:
    """Normalize measured delays to non-negative syncs.

    measured: {"ref": 0, "sec": int|None, "ter": int|None}
    positive = behind ref; negative = ahead of ref
    """
    vals = [0]
    for k in ("sec", "ter"):
        v = measured.get(k)
        if isinstance(v, int):
            vals.append(v)
    G = max(vals)  # highest/most positive delay
    ref = G - 0
    sec = None if measured.get("sec") is None else G - measured["sec"]
    ter = None if measured.get("ter") is None else G - measured["ter"]
    return PositiveOnlyDelayPlan(global_anchor_ms=G, ref_ms=ref, sec_ms=sec, ter_ms=ter)
