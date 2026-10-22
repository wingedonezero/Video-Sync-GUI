# vsg_core/correction/__init__.py
"""Audio timing corrections. Only stepping is connected; PAL (pal.py) and
linear (linear.py) drift correction are disconnected and kept for later, see
docs/plans/drift-correction.md."""

from .linear import run_linear_correction
from .pal import run_pal_correction
from .stepping import run_stepping_correction

__all__ = [
    "run_linear_correction",
    "run_pal_correction",
    "run_stepping_correction",
]
