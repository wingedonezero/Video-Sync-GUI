# vsg_core/analysis/correlation/run.py
"""
Correlation method resolution.

Provides _resolve_method() for modules that need to pick the correct
correlation plugin based on settings (e.g. stepping correction QA checks).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .methods.scc import Scc
from .registry import get_method

if TYPE_CHECKING:
    from ...models.settings import AppSettings
    from .registry import CorrelationMethod


def _resolve_method(
    settings: AppSettings, *, source_separated: bool
) -> CorrelationMethod:
    """Resolve the correlation method to use based on settings."""
    method_name = (
        settings.correlation_method_source_separated
        if source_separated
        else settings.correlation_method
    )
    if "Standard Correlation" in method_name or "SCC" in method_name:
        return Scc(peak_fit=settings.audio_peak_fit)
    return get_method(method_name)
