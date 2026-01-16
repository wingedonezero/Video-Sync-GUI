# vsg_core/orchestrator/steps/attachments_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.extraction.attachments import extract_attachments

class AttachmentsStep:
    """
    Extracts attachments from all sources specified by the user in the UI.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.attachment_sources:
            ctx.attachments = []
            return ctx

        all_attachments: List[str] = []
        for source_key in ctx.attachment_sources:
            source_file = ctx.sources.get(source_key)
            if source_file:
                runner._log_message(f"Extracting attachments from {source_key}...")
                attachments_from_source = extract_attachments(
                    str(source_file), ctx.temp_dir, runner, ctx.tool_paths, source_key
                )
                if attachments_from_source:
                    all_attachments.extend(attachments_from_source)

        ctx.attachments = all_attachments
        return ctx
