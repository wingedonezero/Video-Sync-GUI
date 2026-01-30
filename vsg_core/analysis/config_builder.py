# vsg_core/analysis/config_builder.py
"""
Configuration builder for source-specific analysis settings.

Handles building the appropriate configuration for each source,
including overrides for source separation mode.
"""

from __future__ import annotations

from typing import Any


def should_use_source_separation(
    source_key: str,
    config: dict[str, Any],
    source_settings: dict[str, dict[str, Any]],
) -> bool:
    """
    Check if this source should use source separation during correlation.

    Uses per-source settings from the job layout. Source separation is only applied
    when explicitly enabled for the specific source via use_source_separation flag.

    Args:
        source_key: The source being analyzed (e.g., "Source 2", "Source 3")
        config: Configuration dictionary (for separation mode/model settings)
        source_settings: Per-source correlation settings from job layout

    Returns:
        True if source separation should be applied to this comparison
    """
    # Check if source separation is configured at all (mode must be set)
    separation_mode = config.get("source_separation_mode", "none")
    if separation_mode == "none":
        return False

    # Check per-source setting - source separation must be explicitly enabled per-source
    per_source = source_settings.get(source_key, {})
    return per_source.get("use_source_separation", False)


def build_source_config(
    base_config: dict[str, Any],
    source_key: str,
    source_settings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Build configuration for a specific source.

    Applies source-specific overrides (e.g., source separation settings).

    Args:
        base_config: Base configuration dictionary
        source_key: The source being analyzed (e.g., "Source 2", "Source 3")
        source_settings: Per-source correlation settings from job layout

    Returns:
        Configuration dict with any source-specific overrides applied
    """
    use_separation = should_use_source_separation(
        source_key, base_config, source_settings
    )

    if use_separation:
        # Create config with source-separated overrides
        return {
            **base_config,
            "correlation_method": base_config.get(
                "correlation_method_source_separated",
                "Phase Correlation (GCC-PHAT)",
            ),
            "delay_selection_mode": base_config.get(
                "delay_selection_mode_source_separated", "Mode (Clustered)"
            ),
            "_use_source_separation": True,  # Flag for reference
        }

    # Return base config with flag
    return {
        **base_config,
        "_use_source_separation": False,
    }


def get_correlation_track_settings(
    source_key: str,
    source_settings: dict[str, dict[str, Any]],
    global_config: dict[str, Any],
) -> tuple[int | None, str | None]:
    """
    Get track selection settings for correlation.

    Args:
        source_key: The source being analyzed
        source_settings: Per-source settings
        global_config: Global configuration

    Returns:
        Tuple of (explicit_track_index, language) for track selection
    """
    per_source = source_settings.get(source_key, {})

    # Check for explicit track index
    explicit_index = per_source.get("correlation_source_track")

    # Get language setting (only used if no explicit index)
    if explicit_index is not None:
        language = None  # Bypassed by explicit index
    else:
        language = global_config.get("analysis_lang_others")

    return explicit_index, language


def get_reference_track_settings(
    source_settings: dict[str, dict[str, Any]],
    global_config: dict[str, Any],
) -> tuple[int | None, str | None]:
    """
    Get track selection settings for the reference (Source 1).

    Args:
        source_settings: Per-source settings
        global_config: Global configuration

    Returns:
        Tuple of (explicit_track_index, language) for track selection
    """
    source1_settings = source_settings.get("Source 1", {})

    # Check for explicit track index
    explicit_index = source1_settings.get("correlation_ref_track")

    # Get language setting
    language = global_config.get("analysis_lang_source1")

    return explicit_index, language
