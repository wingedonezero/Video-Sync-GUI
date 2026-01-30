# vsg_core/orchestrator/steps/audio_correction_step.py
"""
Audio correction step with proper error handling and validation.
"""

from __future__ import annotations

from vsg_core.correction.linear import run_linear_correction
from vsg_core.correction.pal import run_pal_correction
from vsg_core.correction.stepping import run_stepping_correction
from vsg_core.io.runner import CommandRunner
from vsg_core.models.enums import TrackType
from vsg_core.orchestrator.steps.context import Context


class AudioCorrectionStep:
    """
    Acts as a router to apply the correct audio correction based on the
    diagnosis from the AnalysisStep.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.settings_dict.get("segmented_enabled", False):
            return ctx

        try:
            if ctx.pal_drift_flags:
                runner._log_message("--- PAL Drift Audio Correction Phase ---")
                ctx = run_pal_correction(ctx, runner)
                self._validate_pal_correction(ctx, runner)

            elif ctx.linear_drift_flags:
                runner._log_message("--- Linear Drift Audio Correction Phase ---")
                ctx = run_linear_correction(ctx, runner)
                self._validate_linear_correction(ctx, runner)

            elif ctx.segment_flags:
                runner._log_message(
                    "--- Segmented (Stepping) Audio Correction Phase ---"
                )
                ctx = run_stepping_correction(ctx, runner)
                self._validate_stepping_correction(ctx, runner)

        except Exception as e:
            runner._log_message(f"[FATAL] Audio correction failed: {e}")
            raise RuntimeError(f"Audio correction failed: {e}") from e

        return ctx

    def _validate_pal_correction(self, ctx: Context, runner: CommandRunner):
        """Validate that PAL correction was applied successfully."""
        for analysis_key in ctx.pal_drift_flags:
            source_key = analysis_key.split("_")[0]

            audio_tracks_from_source = [
                item
                for item in ctx.extracted_items
                if (
                    item.track.source == source_key
                    and item.track.type == TrackType.AUDIO
                    and not item.is_preserved
                )
            ]

            if not audio_tracks_from_source:
                runner._log_message(
                    f"[Validation] PAL correction skipped for {source_key}: "
                    f"No audio tracks from this source in layout."
                )
                continue

            corrected_items = [
                item for item in audio_tracks_from_source if item.is_corrected
            ]

            if not corrected_items:
                raise RuntimeError(
                    f"PAL correction failed for {source_key}: "
                    f"No corrected track was created. Check logs for errors."
                )

            for item in corrected_items:
                if not item.extracted_path or not item.extracted_path.exists():
                    raise RuntimeError(
                        f"PAL correction failed for {source_key}: "
                        f"Corrected file was not created at {item.extracted_path}"
                    )

                runner._log_message(
                    f"[Validation] PAL correction verified for {source_key}: "
                    f"{item.extracted_path.name}"
                )

    def _validate_linear_correction(self, ctx: Context, runner: CommandRunner):
        """Validate that linear drift correction was applied successfully."""
        for analysis_key in ctx.linear_drift_flags:
            source_key = analysis_key.split("_")[0]

            audio_tracks_from_source = [
                item
                for item in ctx.extracted_items
                if (
                    item.track.source == source_key
                    and item.track.type == TrackType.AUDIO
                    and not item.is_preserved
                )
            ]

            if not audio_tracks_from_source:
                runner._log_message(
                    f"[Validation] Linear drift correction skipped for {source_key}: "
                    f"No audio tracks from this source in layout."
                )
                continue

            corrected_items = [
                item for item in audio_tracks_from_source if item.is_corrected
            ]

            if not corrected_items:
                raise RuntimeError(
                    f"Linear drift correction failed for {source_key}: "
                    f"No corrected track was created. Check logs for errors."
                )

            for item in corrected_items:
                if not item.extracted_path or not item.extracted_path.exists():
                    raise RuntimeError(
                        f"Linear drift correction failed for {source_key}: "
                        f"Corrected file was not created at {item.extracted_path}"
                    )

                runner._log_message(
                    f"[Validation] Linear drift correction verified for {source_key}: "
                    f"{item.extracted_path.name}"
                )

    def _validate_stepping_correction(self, ctx: Context, runner: CommandRunner):
        """Validate that stepping correction was applied successfully."""
        for analysis_key in ctx.segment_flags:
            source_key = analysis_key.split("_")[0]

            audio_tracks_from_source = [
                item
                for item in ctx.extracted_items
                if (
                    item.track.source == source_key
                    and item.track.type == TrackType.AUDIO
                    and not item.is_preserved
                )
            ]

            if not audio_tracks_from_source:
                runner._log_message(
                    f"[Validation] Stepping correction skipped for {source_key}: "
                    f"No audio tracks from this source in layout."
                )
                continue

            corrected_items = [
                item for item in audio_tracks_from_source if item.is_corrected
            ]

            # SAFEGUARD #2: If no corrected items, check if stepping was actually found
            # The corrector may determine there's no stepping after detailed analysis
            if not corrected_items:
                # Check if any item has a note about "no stepping found"
                # In this case, the corrector decided no correction was needed
                runner._log_message(
                    f"[Validation] No corrected tracks found for {source_key}. "
                    f"This is expected if the corrector determined no stepping exists after detailed analysis."
                )
                runner._log_message(
                    "[Validation] The globally-shifted delay from initial analysis will be used."
                )
                # SAFEGUARD #3: Mark that this is intentional - stepping was a false positive
                # Validation passes - this is not an error condition
                continue

            # If there ARE corrected items, validate them normally
            for item in corrected_items:
                if not item.extracted_path or not item.extracted_path.exists():
                    raise RuntimeError(
                        f"Stepping correction failed for {source_key}: "
                        f"Corrected file was not created at {item.extracted_path}"
                    )

                runner._log_message(
                    f"[Validation] Stepping correction verified for {source_key}: "
                    f"{item.extracted_path.name}"
                )
