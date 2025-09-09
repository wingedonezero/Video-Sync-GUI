# vsg_core/orchestrator/steps/chapters_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.chapters.process import process_chapters

class ChaptersStep:
    """
    Extracts/modifies chapter XML from Source 1.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.chapters_xml = None
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            runner._log_message("[WARN] No Source 1 file found for chapter processing.")
            ctx.chapters_xml = None
            return ctx

        shift_ms = ctx.delays.global_shift_ms if ctx.delays else 0
        xml_path = process_chapters(
            source1_file, ctx.temp_dir, runner, ctx.tool_paths,
            ctx.settings_dict, shift_ms
        )
        ctx.chapters_xml = xml_path
        return ctx
