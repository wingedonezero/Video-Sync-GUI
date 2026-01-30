# vsg_core/models/correction.py
"""
Centralized correction model definitions.

This module contains the correction-related enums and dataclasses
used by the stepping, PAL drift, and linear drift correction systems.

Previously these were defined in vsg_core/correction/stepping.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class CorrectionVerdict(Enum):
    """Verdict from correction analysis."""

    UNIFORM = auto()
    STEPPED = auto()
    FAILED = auto()


@dataclass
class CorrectionResult:
    """Result of a correction analysis operation."""

    verdict: CorrectionVerdict
    data: Any = None


@dataclass(unsafe_hash=True)
class AudioSegment:
    """
    Represents an action point on the target timeline for the assembly function.

    Used for stepping correction EDL (Edit Decision List) generation.
    """

    start_s: float
    end_s: float
    delay_ms: int
    delay_raw: float = (
        0.0  # Raw float delay for subtitle precision (avoids double rounding)
    )
    drift_rate_ms_s: float = 0.0
