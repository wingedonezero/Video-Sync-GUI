# vsg_core/analysis/correlation/registry.py
"""
Correlation method plugin registry.

Each correlation method implements the CorrelationMethod protocol and is
registered at import time. The step looks up methods by display name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@runtime_checkable
class CorrelationMethod(Protocol):
    """Protocol that all correlation method plugins must satisfy."""

    @property
    def name(self) -> str:
        """Display name shown in UI and logs (e.g. 'Phase Correlation (GCC-PHAT)')."""
        ...

    @property
    def config_key(self) -> str:
        """AppSettings attribute for multi-correlation toggle (e.g. 'multi_corr_gcc_phat')."""
        ...

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        """
        Compute delay between two audio chunks.

        Args:
            ref_chunk: Reference audio chunk (mono float32).
            tgt_chunk: Target audio chunk (mono float32).
            sr: Sample rate in Hz.

        Returns:
            (delay_ms, confidence) where confidence is 0-100.
        """
        ...


# -- Registry --

_METHODS: dict[str, CorrelationMethod] = {}


def register(method: CorrelationMethod) -> None:
    """Register a correlation method plugin."""
    _METHODS[method.name] = method


def get_method(name: str) -> CorrelationMethod:
    """Look up a method by its display name. Raises KeyError if not found."""
    return _METHODS[name]


def list_methods() -> list[CorrelationMethod]:
    """Return all registered methods in insertion order."""
    return list(_METHODS.values())
