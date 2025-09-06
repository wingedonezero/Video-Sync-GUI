# vsg_core/orchestrator/pipeline.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import time
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from vsg_core.process import CommandRunner
from vsg_core.models.settings import AppSettings
from vsg_core.orchestrator.steps import (
    Context,
    AnalysisStep,
    ExtractStep,
    SubtitlesStep,
    ChaptersStep,
    AttachmentsStep,
    MuxStep,
)


class Orchestrator:
    """
    Runs the modular steps in the established order and returns a populated Context.
    Intended to be called by vsg_core.pipeline.JobPipeline (lean wrapper).
    """

    def run(
        self,
        *,
        settings_dict: Dict[str, Any],
        tool_paths: Dict[str, Optional[str]],
        log: Callable[[str], None],
        progress: Callable[[float], None],
        ref_file: str,
        sec_file: Optional[str],
        ter_file: Optional[str],
        and_merge: bool,
        output_dir: str,
        manual_layout: List[Dict[str, Any]],
    ) -> Context:
        """
        Execute the pipeline steps and return a final Context that includes:
          - delay_sec_val, delay_ter_val
          - delays (with global_shift_ms)
          - extracted_items (when merging)
          - chapters_xml (when merging)
          - attachments (when merging)
          - out_file and tokens (when merging)
        Any exception raised inside a step propagates upward after cleanup.
        """

        # Build typed settings while preserving the raw dict for legacy helpers
        settings = AppSettings.from_config(settings_dict)

        # Per-job temp workspace (separate from UI's log folder). We keep it isolated and clean it.
        base_temp = Path(settings_dict.get("temp_root", Path.cwd() / "temp_work"))
        job_temp = base_temp / f"orch_{Path(ref_file).stem}_{int(time.time())}"
        job_temp.mkdir(parents=True, exist_ok=True)

        runner = CommandRunner(settings_dict, log)

        # Initialize context
        ctx = Context(
            settings=settings,
            settings_dict=settings_dict,
            tool_paths=tool_paths,
            log=log,
            progress=progress,
            output_dir=str(output_dir),
            temp_dir=job_temp,
            ref_file=str(ref_file),
            sec_file=str(sec_file) if sec_file else None,
            ter_file=str(ter_file) if ter_file else None,
            and_merge=bool(and_merge),
            manual_layout=manual_layout or [],
        )

        try:
            # --- Analysis (always) ---
            log('--- Analysis Phase ---')
            progress(0.10)
            ctx = AnalysisStep().run(ctx, runner)

            if not and_merge:
                # Analyze-only path ends here; caller will read delays from ctx
                return ctx

            # --- Extraction ---
            log('--- Extraction Phase ---')
            progress(0.40)
            ctx = ExtractStep().run(ctx, runner)

            # --- Subtitles transforms ---
            log('--- Subtitle Processing Phase ---')
            ctx = SubtitlesStep().run(ctx, runner)

            # --- Chapters ---
            log('--- Chapters Phase ---')
            ctx = ChaptersStep().run(ctx, runner)

            # --- Attachments ---
            log('--- Attachments Phase ---')
            progress(0.60)
            ctx = AttachmentsStep().run(ctx, runner)

            # --- Mux token build (no execution here) ---
            log('--- Merge Planning Phase ---')
            progress(0.75)
            ctx = MuxStep().run(ctx, runner)

            # Caller (JobPipeline) will write @opts and invoke mkvmerge.
            progress(0.80)
            return ctx

        finally:
            # Cleanup our per-job temp workspace. The outer JobPipeline already
            # archives logs separately and cleans its own temp if applicable.
            try:
                shutil.rmtree(job_temp, ignore_errors=True)
            except Exception:
                # Non-fatal; nothing else to do here.
                pass
