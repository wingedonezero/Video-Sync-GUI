# vsg_core/analysis/delay_selection/stepping_override.py
"""
Stepping override logic for delay selection.

Handles the decision of whether to use first-segment delay override
when stepping is detected, based on correction settings and source separation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .first_stable import find_first_stable_segment_delay


@dataclass
class SteppingOverrideResult:
    """Result of stepping override evaluation."""

    # Override values (None if no override)
    override_delay: int | None = None
    override_delay_raw: float | None = None

    # Flags for step to handle
    add_to_stepping_sources: bool = False
    track_as_separated: bool = False  # ctx.stepping_detected_separated
    track_as_disabled: bool = False  # ctx.stepping_detected_disabled

    # Log messages for the step to emit
    log_messages: list[str] = field(default_factory=list)


def evaluate_stepping_override(
    diagnosis: str | None,
    details: dict[str, Any],
    results: list[dict[str, Any]],
    source_key: str,
    source_config: dict[str, Any],
    stepping_enabled: bool,
    use_source_separation: bool,
    has_audio_from_source: bool,
    log: Callable[[str], None] | None = None,
) -> SteppingOverrideResult:
    """
    Evaluate whether stepping override should be applied.

    This function contains the business logic for deciding whether to use
    first-segment delay when stepping is detected.

    Args:
        diagnosis: Diagnosis type from diagnose_audio_issue ("STEPPING", etc.)
        details: Diagnosis details dict
        results: Correlation chunk results
        source_key: Source being analyzed (e.g., "Source 2")
        source_config: Configuration for this source
        stepping_enabled: Whether stepping correction is enabled globally
        use_source_separation: Whether source separation was applied
        has_audio_from_source: Whether this source has audio tracks in layout
        log: Optional logging callback (for find_first_stable_segment_delay)

    Returns:
        SteppingOverrideResult with override values and flags
    """
    result = SteppingOverrideResult()

    # Only handle STEPPING diagnosis
    if diagnosis != "STEPPING":
        return result

    # CRITICAL: Stepping correction doesn't work on source-separated audio
    # Separated stems have fundamentally different waveform characteristics
    if stepping_enabled and not use_source_separation:
        # Stepping correction is ENABLED - proceed with correction logic
        result.add_to_stepping_sources = True

        if has_audio_from_source:
            # Stepping correction will run, so use first segment delay
            # Use stepping-specific stability criteria
            stepping_config = {
                "first_stable_min_chunks": source_config.get(
                    "stepping_first_stable_min_chunks", 3
                ),
                "first_stable_skip_unstable": source_config.get(
                    "stepping_first_stable_skip_unstable", True
                ),
            }

            # Get both rounded (for mkvmerge) and raw (for subtitle precision)
            stable_result = find_first_stable_segment_delay(
                results, stepping_config, log
            )

            if stable_result is not None:
                first_delay, first_delay_raw = stable_result
                result.override_delay = first_delay
                result.override_delay_raw = first_delay_raw
                result.log_messages = [
                    f"[Stepping Detected] Found stepping in {source_key}",
                    f"[Stepping Override] Using first segment's delay: {first_delay:+d}ms (raw: {first_delay_raw:.3f}ms)",
                    f"[Stepping Override] This delay will be used for ALL tracks (audio + subtitles) from {source_key}",
                    "[Stepping Override] Stepping correction will be applied to audio tracks during processing",
                ]
        else:
            # No audio tracks from this source - stepping correction won't run
            delay_mode = source_config.get("delay_selection_mode", "Mode (Most Common)")
            result.log_messages = [
                f"[Stepping Detected] Found stepping in {source_key}",
                "[Stepping] No audio tracks from this source are being merged",
                f"[Stepping] Using delay_selection_mode='{delay_mode}' instead of first segment (stepping correction won't run)",
            ]

    elif use_source_separation:
        # Source separation blocks stepping correction (unreliable on separated stems)
        result.track_as_separated = True
        delay_mode = source_config.get("delay_selection_mode", "Mode (Clustered)")
        result.log_messages = [
            f"[Stepping Detected] Found stepping in {source_key}",
            "[Stepping Disabled] Source separation is enabled - stepping correction is unreliable on separated stems",
            "[Stepping Disabled] Separated stems have different waveform characteristics that break stepping detection",
            f"[Stepping Disabled] Using delay_selection_mode='{delay_mode}' instead",
        ]

    else:
        # Stepping correction is DISABLED globally - just warn the user
        result.track_as_disabled = True
        result.log_messages = [
            f"⚠️  [Stepping Detected] Found stepping in {source_key}",
            "⚠️  [Stepping Disabled] Stepping correction is disabled - timing may be inconsistent",
            "⚠️  [Recommendation] Enable 'Stepping Correction' in settings if you want automatic correction",
            "⚠️  [Manual Review] You should manually review this file's sync quality",
        ]

    return result
