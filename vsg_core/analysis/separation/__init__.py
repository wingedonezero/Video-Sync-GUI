# vsg_core/analysis/separation/__init__.py
"""
Audio source separation module.

This module provides audio source separation using python-audio-separator
for cross-language correlation.

The actual implementation remains in source_separation.py for now
to maintain backward compatibility during the refactor.
"""

from __future__ import annotations

# Re-export from existing module for backward compatibility
from ..source_separation import (
    CURATED_MODELS,
    DEFAULT_MODEL,
    MODEL_QUALITY_DATABASE,
    SEPARATION_MODES,
    apply_source_separation,
    download_model,
    get_all_available_models_from_registry,
    get_installed_models,
    is_audio_separator_available,
    is_separation_enabled,
    list_available_models,
    resample_audio,
    separate_audio,
    update_installed_models_json,
)

__all__ = [
    # Main API
    "apply_source_separation",
    "separate_audio",
    "is_separation_enabled",
    "is_audio_separator_available",
    # Model management
    "list_available_models",
    "get_installed_models",
    "get_all_available_models_from_registry",
    "download_model",
    "update_installed_models_json",
    # Utilities
    "resample_audio",
    # Constants
    "SEPARATION_MODES",
    "DEFAULT_MODEL",
    "MODEL_QUALITY_DATABASE",
    "CURATED_MODELS",
]
