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

        # Chapters are part of Source 1 and should never be shifted under the new logic.
        shift_ms = 0

        xml_path = process_chapters(
            source1_file, ctx.temp_dir, runner, ctx.tool_paths,
            ctx.settings_dict, shift_ms
        )
        ctx.chapters_xml = xml_path
        return ctx
