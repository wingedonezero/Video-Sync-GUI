# vsg_core/orchestrator/steps/attachments_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.extraction.attachments import extract_attachments

class AttachmentsStep:
    """
    Extracts attachments.
    New convention: Pulls from the highest-numbered source file that exists.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.attachments = []
            return ctx

        # Find the highest-numbered source to pull attachments from
        highest_source_key = ""
        highest_source_num = 0
        for key in ctx.sources.keys():
            try:
                num = int(key.split(" ")[1])
                if num > highest_source_num:
                    highest_source_num = num
                    highest_source_key = key
            except (IndexError, ValueError):
                continue

        attachment_source_file = ctx.sources.get(highest_source_key)
        if attachment_source_file:
            runner._log_message(f"Extracting attachments from {highest_source_key}...")
            ctx.attachments = extract_attachments(str(attachment_source_file), ctx.temp_dir, runner, ctx.tool_paths, highest_source_key) or []
        else:
            ctx.attachments = []

        return ctx
