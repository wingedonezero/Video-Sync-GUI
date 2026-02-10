# vsg_core/analysis/correlation/methods/__init__.py
"""
Built-in correlation method plugins.

All methods are registered at import time so the registry is populated
when any code imports from the correlation package.
"""

from __future__ import annotations

from ..registry import register
from .dtw import Dtw
from .gcc_phat import GccPhat
from .gcc_scot import GccScot
from .gcc_whiten import GccWhiten
from .onset import OnsetDetection
from .scc import Scc
from .spectrogram import SpectrogramCorrelation

# Register all built-in methods.
# Order here determines iteration order in list_methods().
for _cls in (
    Scc,
    GccPhat,
    OnsetDetection,
    GccScot,
    GccWhiten,
    Dtw,
    SpectrogramCorrelation,
):
    register(_cls())

__all__ = [
    "Dtw",
    "GccPhat",
    "GccScot",
    "GccWhiten",
    "OnsetDetection",
    "Scc",
    "SpectrogramCorrelation",
]
