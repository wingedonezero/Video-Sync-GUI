# vsg_core/analysis/separation/__init__.py
"""
Audio source separation module.

This module provides audio source separation using python-audio-separator
for cross-language correlation.
"""

from __future__ import annotations

# Import from modular submodules
from .core import (
    apply_source_separation,
    is_separation_enabled,
    resample_audio,
    separate_audio,
)
from .models import (
    CURATED_MODELS,
    DEFAULT_MODEL,
    MODEL_QUALITY_DATABASE,
    SEPARATION_MODES,
)
from .registry import (
    download_model,
    fallback_models,
    get_all_available_models_from_registry,
    get_installed_models,
    get_installed_models_json_path,
    is_audio_separator_available,
    list_available_models,
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
    "get_installed_models_json_path",
    "get_all_available_models_from_registry",
    "download_model",
    "update_installed_models_json",
    "fallback_models",
    # Utilities
    "resample_audio",
    # Constants
    "SEPARATION_MODES",
    "DEFAULT_MODEL",
    "MODEL_QUALITY_DATABASE",
    "CURATED_MODELS",
]
