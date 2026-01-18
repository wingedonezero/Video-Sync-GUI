# vsg_core/orchestrator/pipeline.py
# -*- coding: utf-8 -*-
"""
Enhanced pipeline with comprehensive validation at each step.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from vsg_core.io.runner import CommandRunner
from vsg_core.models.settings import AppSettings
from vsg_core.orchestrator.steps import (
    Context, AnalysisStep, ExtractStep, AudioCorrectionStep, SubtitlesStep,
    ChaptersStep, AttachmentsStep, MuxStep
)
from vsg_core.orchestrator.validation import StepValidator, PipelineValidationError


class Orchestrator:
    """
    Runs the modular steps in order with validation at each stage.
    Any validation failure will halt the job with a clear error message.
    """
    def run(
        self,
        *,
        settings_dict: Dict[str, Any],
        tool_paths: Dict[str, Optional[str]],
        log: Callable[[str], None],
        progress: Callable[[float], None],
        sources: Dict[str, str],
        and_merge: bool,
        output_dir: str,
        manual_layout: List[Dict[str, Any]],
        attachment_sources: List[str],
        source_settings: Dict[str, Dict[str, Any]] = None
    ) -> Context:
        """
        Executes the pipeline steps with validation.
        Raises PipelineValidationError if any step fails validation.
        """
        settings = AppSettings.from_config(settings_dict)
        source1_file = sources.get("Source 1")
        if not source1_file:
            raise ValueError("Job is missing Source 1 (Reference).")

        base_temp = Path(settings_dict.get("temp_root", Path.cwd() / "temp_work"))
        job_temp = base_temp / f"orch_{Path(source1_file).stem}_{int(time.time())}"
        job_temp.mkdir(parents=True, exist_ok=True)

        runner = CommandRunner(settings_dict, log)

        ctx = Context(
            settings=settings,
            settings_dict=settings_dict,
            tool_paths=tool_paths,
            log=log,
            progress=progress,
            output_dir=str(output_dir),
            temp_dir=job_temp,
            sources=sources,
            and_merge=bool(and_merge),
            manual_layout=manual_layout or [],
            attachment_sources=attachment_sources,
            source_settings=source_settings or {}
        )

        log('--- Analysis Phase ---')
        progress(0.10)
        try:
            ctx = AnalysisStep().run(ctx, runner)
            StepValidator.validate_analysis(ctx)
            log('[Validation] Analysis phase validated successfully.')
        except PipelineValidationError as e:
            log(f'[FATAL] Analysis validation failed: {e}')
            raise
        except Exception as e:
            log(f'[FATAL] Analysis phase failed: {e}')
            raise RuntimeError(f"Analysis phase failed: {e}") from e

        if not and_merge:
            log('--- Analysis Complete (No Merge) ---')
            progress(1.0)
            return ctx

        log('--- Extraction Phase ---')
        progress(0.40)
        try:
            ctx = ExtractStep().run(ctx, runner)
            StepValidator.validate_extraction(ctx)
            log('[Validation] Extraction phase validated successfully.')
        except PipelineValidationError as e:
            log(f'[FATAL] Extraction validation failed: {e}')
            raise
        except Exception as e:
            log(f'[FATAL] Extraction phase failed: {e}')
            raise RuntimeError(f"Extraction phase failed: {e}") from e

        if ctx.settings_dict.get('segmented_enabled', False) and (ctx.segment_flags or ctx.pal_drift_flags or ctx.linear_drift_flags):
            log('--- Advanced Audio Correction Phase ---')
            progress(0.50)
            try:
                ctx = AudioCorrectionStep().run(ctx, runner)
                StepValidator.validate_correction(ctx)
                log('[Validation] Audio correction phase validated successfully.')
            except PipelineValidationError as e:
                log(f'[FATAL] Audio correction validation failed: {e}')
                raise
            except Exception as e:
                log(f'[FATAL] Audio correction phase failed: {e}')
                raise RuntimeError(f"Audio correction phase failed: {e}") from e

        log('--- Subtitle Processing Phase ---')
        try:
            ctx = SubtitlesStep().run(ctx, runner)
            StepValidator.validate_subtitles(ctx)
            log('[Validation] Subtitle processing phase validated successfully.')
        except PipelineValidationError as e:
            log(f'[FATAL] Subtitle processing validation failed: {e}')
            raise
        except Exception as e:
            log(f'[FATAL] Subtitle processing phase failed: {e}')
            raise RuntimeError(f"Subtitle processing phase failed: {e}") from e

        log('--- Chapters Phase ---')
        try:
            ctx = ChaptersStep().run(ctx, runner)
            log('[Validation] Chapters phase completed.')
        except Exception as e:
            log(f'[WARNING] Chapters phase had issues (non-fatal): {e}')

        log('--- Attachments Phase ---')
        progress(0.60)
        try:
            ctx = AttachmentsStep().run(ctx, runner)
            log('[Validation] Attachments phase completed.')
        except Exception as e:
            log(f'[WARNING] Attachments phase had issues (non-fatal): {e}')

        log('--- Merge Planning Phase ---')
        progress(0.75)
        try:
            ctx = MuxStep().run(ctx, runner)
            StepValidator.validate_mux(ctx)
            log('[Validation] Merge planning phase validated successfully.')
        except PipelineValidationError as e:
            log(f'[FATAL] Merge planning validation failed: {e}')
            raise
        except Exception as e:
            log(f'[FATAL] Merge planning phase failed: {e}')
            raise RuntimeError(f"Merge planning phase failed: {e}") from e

        progress(0.80)
        return ctx
