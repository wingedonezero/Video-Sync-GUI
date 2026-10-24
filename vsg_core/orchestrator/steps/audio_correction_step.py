# vsg_core/orchestrator/steps/audio_correction_step.py
"""
Stepping correction (EDL preparation) for AudioProcessingStep.

PAL and linear drift correction are disconnected (2026-10-22): analysis still
detects and flags them, AudioProcessingStep logs them and the final audit
reports them, but nothing corrects them. See docs/plans/drift-correction.md
for why and for what to revisit (vsg_core/correction/pal.py and linear.py are
kept, unused).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vsg_core.correction.stepping import run_stepping_correction

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


class AudioCorrectionStep:
    """Runs stepping analysis -> verified EDLs (ctx.stepping_corrections)."""

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.settings.stepping_enabled:
            return ctx
        if not ctx.segment_flags:
            return ctx

        try:
            runner._log_message("--- Segmented (Stepping) Audio Correction Phase ---")
            ctx = run_stepping_correction(ctx, runner)
            self._validate_stepping_correction(ctx, runner)
        except Exception as e:
            runner._log_message(f"[FATAL] Audio correction failed: {e}")
            raise RuntimeError(f"Audio correction failed: {e}") from e

        return ctx

    def _validate_stepping_correction(self, ctx: Context, runner: CommandRunner):
        """Stepping only prepares EDLs here; AudioProcessingStep applies them.
        A source without one (uniform delay, QA failure) keeps its analysis
        delay, and its tracks take the normal FLAC / untouched route."""
        for analysis_key, flag_info in ctx.segment_flags.items():
            source_key = analysis_key.split("_")[0]
            if flag_info.get("subs_only", False):
                continue
            if source_key in ctx.stepping_corrections:
                runner._log_message(
                    f"[Validation] Stepping EDL for {source_key} verified; "
                    f"applied to its audio in Audio Processing."
                )
            else:
                runner._log_message(
                    f"[Validation] No stepping correction for {source_key}; "
                    f"its audio keeps the analysis delay."
                )
