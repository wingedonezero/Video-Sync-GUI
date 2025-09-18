# vsg_core/orchestrator/steps/audio_correction_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.orchestrator.steps.context import Context
from ...io.runner import CommandRunner
from ...correction.pal import run_pal_correction
from ...correction.stepping import run_stepping_correction

class AudioCorrectionStep:
    """
    Acts as a router to apply the correct audio correction based on the
    diagnosis from the AnalysisStep.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.settings_dict.get('segmented_enabled', False):
            return ctx

        # Router logic: Check for different types of required corrections.
        # The order can be important if a file could have multiple issues.
        if ctx.pal_drift_flags:
            runner._log_message('--- PAL Drift Audio Correction Phase ---')
            ctx = run_pal_correction(ctx, runner)

        if ctx.segment_flags:
            runner._log_message('--- Segmented (Stepping) Audio Correction Phase ---')
            ctx = run_stepping_correction(ctx, runner)

        return ctx
