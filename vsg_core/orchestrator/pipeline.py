# vsg_core/orchestrator/pipeline.py
# -*- coding: utf-8 -*-
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

class Orchestrator:
    """
    Runs the modular steps in order and returns a populated Context.
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
        attachment_sources: List[str]
    ) -> Context:
        """
        Executes the pipeline steps using the new dynamic sources model.
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
            attachment_sources=attachment_sources
        )

        log('--- Analysis Phase ---')
        progress(0.10)
        ctx = AnalysisStep().run(ctx, runner)

        if not and_merge:
            return ctx

        log('--- Extraction Phase ---')
        progress(0.40)
        ctx = ExtractStep().run(ctx, runner)

        # Check for any advanced correction flags (stepping or drift)
        if ctx.settings_dict.get('segmented_enabled', False) and (ctx.segment_flags or ctx.pal_drift_flags):
            log('--- Advanced Audio Correction Phase ---')
            progress(0.50)
            ctx = AudioCorrectionStep().run(ctx, runner)

        log('--- Subtitle Processing Phase ---')
        ctx = SubtitlesStep().run(ctx, runner)

        log('--- Chapters Phase ---')
        ctx = ChaptersStep().run(ctx, runner)

        log('--- Attachments Phase ---')
        progress(0.60)
        ctx = AttachmentsStep().run(ctx, runner)

        log('--- Merge Planning Phase ---')
        progress(0.75)
        ctx = MuxStep().run(ctx, runner)

        progress(0.80)
        return ctx
