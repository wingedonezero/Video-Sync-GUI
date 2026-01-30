# vsg_core/analysis/diagnostics/flag_handler.py
"""
Diagnosis flag handler for analysis results.

Handles applying diagnosis results (PAL_DRIFT, LINEAR_DRIFT, STEPPING)
to the context flags based on source configuration and layout.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.models import Context


def _source_has_track_type_in_layout(
    layout: list[dict[str, Any]],
    source_key: str,
    track_type: str,
) -> bool:
    """Check if a source has tracks of a given type in the layout."""
    return any(
        item.get("source") == source_key and item.get("type") == track_type
        for item in layout
    )


def apply_diagnosis_flags(
    ctx: Context,
    diagnosis: str | None,
    details: dict[str, Any],
    source_key: str,
    track_id: int | None,
    use_source_separation: bool,
    final_delay_ms: int,
    config: dict[str, Any],
    log: Callable[[str], None] | None = None,
) -> None:
    """
    Apply diagnosis results to context flags.

    Handles PAL_DRIFT, LINEAR_DRIFT, and STEPPING diagnoses, checking
    whether corrections should be applied based on source separation
    status and whether the source has audio/subtitle tracks in the layout.

    Args:
        ctx: Context to update with flags
        diagnosis: Diagnosis type ("PAL_DRIFT", "LINEAR_DRIFT", "STEPPING", or None)
        details: Diagnosis details dict
        source_key: Source being analyzed (e.g., "Source 2")
        track_id: Track ID that was analyzed
        use_source_separation: Whether source separation is enabled for this source
        final_delay_ms: The calculated final delay (for stepping info)
        config: Configuration dict (for stepping settings)
        log: Optional logging callback
    """
    if not diagnosis:
        return

    analysis_track_key = f"{source_key}_{track_id}"
    layout = ctx.manual_layout

    if diagnosis == "PAL_DRIFT":
        _handle_pal_drift(
            ctx,
            details,
            source_key,
            analysis_track_key,
            use_source_separation,
            layout,
            log,
        )

    elif diagnosis == "LINEAR_DRIFT":
        _handle_linear_drift(
            ctx,
            details,
            source_key,
            analysis_track_key,
            use_source_separation,
            layout,
            log,
        )

    elif diagnosis == "STEPPING":
        _handle_stepping(
            ctx,
            details,
            source_key,
            analysis_track_key,
            use_source_separation,
            layout,
            final_delay_ms,
            config,
            log,
        )


def _handle_pal_drift(
    ctx: Context,
    details: dict[str, Any],
    source_key: str,
    analysis_track_key: str,
    use_source_separation: bool,
    layout: list[dict[str, Any]],
    log: Callable[[str], None] | None,
) -> None:
    """Handle PAL_DRIFT diagnosis."""
    if use_source_separation:
        if log:
            log(
                f"[PAL Drift Detected] PAL drift detected in {source_key}, but source separation "
                f"is enabled. PAL correction is unreliable on separated stems - skipping."
            )
        return

    source_has_audio = _source_has_track_type_in_layout(layout, source_key, "audio")

    if source_has_audio:
        ctx.pal_drift_flags[analysis_track_key] = details
    elif log:
        log(
            f"[PAL Drift Detected] PAL drift detected in {source_key}, but no audio tracks "
            f"from this source are being used. Skipping PAL correction for {source_key}."
        )


def _handle_linear_drift(
    ctx: Context,
    details: dict[str, Any],
    source_key: str,
    analysis_track_key: str,
    use_source_separation: bool,
    layout: list[dict[str, Any]],
    log: Callable[[str], None] | None,
) -> None:
    """Handle LINEAR_DRIFT diagnosis."""
    if use_source_separation:
        if log:
            log(
                f"[Linear Drift Detected] Linear drift detected in {source_key}, but source separation "
                f"is enabled. Linear drift correction is unreliable on separated stems - skipping."
            )
        return

    source_has_audio = _source_has_track_type_in_layout(layout, source_key, "audio")

    if source_has_audio:
        ctx.linear_drift_flags[analysis_track_key] = details
    elif log:
        log(
            f"[Linear Drift Detected] Linear drift detected in {source_key}, but no audio tracks "
            f"from this source are being used. Skipping linear drift correction for {source_key}."
        )


def _handle_stepping(
    ctx: Context,
    details: dict[str, Any],
    source_key: str,
    analysis_track_key: str,
    use_source_separation: bool,
    layout: list[dict[str, Any]],
    final_delay_ms: int,
    config: dict[str, Any],
    log: Callable[[str], None] | None,
) -> None:
    """Handle STEPPING diagnosis."""
    # Block stepping correction when source separation is enabled
    # (Already handled in stepping detection, just skip flag storage)
    if use_source_separation:
        return

    source_has_audio = _source_has_track_type_in_layout(layout, source_key, "audio")
    source_has_subs = _source_has_track_type_in_layout(layout, source_key, "subtitles")

    stepping_info = {
        "base_delay": final_delay_ms,
        "cluster_details": details.get("cluster_details", []),
        "valid_clusters": details.get("valid_clusters", {}),
        "invalid_clusters": details.get("invalid_clusters", {}),
        "validation_results": details.get("validation_results", {}),
        "correction_mode": details.get("correction_mode", "full"),
        "fallback_mode": details.get("fallback_mode", "nearest"),
    }

    if source_has_audio:
        # Store stepping correction info with the corrected delay and cluster diagnostics
        ctx.segment_flags[analysis_track_key] = {
            **stepping_info,
            "subs_only": False,
        }
        if log:
            log(
                f"[Stepping] Stepping correction will be applied to audio tracks from {source_key}."
            )

    elif source_has_subs and config.get("stepping_adjust_subtitles_no_audio", True):
        # No audio but subs exist - run full stepping correction to get verified EDL
        if log:
            log(
                f"[Stepping Detected] Stepping detected in {source_key}. No audio tracks "
                f"from this source, but subtitles will use verified stepping EDL."
            )
        # Set segment_flags so stepping correction step runs full analysis
        ctx.segment_flags[analysis_track_key] = {
            **stepping_info,
            "subs_only": True,  # Flag to indicate no audio application needed
        }
        if log:
            log("[Stepping] Full stepping analysis will run for verified subtitle EDL.")

    elif log:
        log(
            f"[Stepping Detected] Stepping detected in {source_key}, but no audio or subtitle tracks "
            f"from this source are being used. Skipping stepping correction."
        )
