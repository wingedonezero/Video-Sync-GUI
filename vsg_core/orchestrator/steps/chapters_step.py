# vsg_core/orchestrator/steps/chapters_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.chapters.process import process_chapters

class ChaptersStep:
    """
    Extracts/modifies chapter XML from Source 1.
    Applies global shift to keep chapters in sync with shifted audio tracks.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        # Ensure ctx is not None
        if ctx is None:
            runner._log_message("[ERROR] Context is None in ChaptersStep")
            raise RuntimeError("Context is None in ChaptersStep")

        if not ctx.and_merge:
            ctx.chapters_xml = None
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            runner._log_message("[WARN] No Source 1 file found for chapter processing.")
            ctx.chapters_xml = None
            return ctx

        # CRITICAL: Chapters must be shifted by the global shift amount
        # This keeps them in sync when we had to shift all audio tracks to eliminate negative delays
        shift_ms = ctx.delays.global_shift_ms if ctx.delays else 0

        if shift_ms != 0:
            runner._log_message(f"[Chapters] Applying global shift of +{shift_ms}ms to chapter timestamps")
            runner._log_message(f"[Chapters] This keeps chapters in sync with the shifted audio tracks")
        else:
            runner._log_message("[Chapters] No global shift needed for chapters")

        xml_path = process_chapters(
            source1_file, ctx.temp_dir, runner, ctx.tool_paths,
            ctx.settings_dict, shift_ms
        )
        ctx.chapters_xml = xml_path
        return ctx
