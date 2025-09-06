# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.process import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core import mkv_utils


class AttachmentsStep:
    """
    Extracts attachments from TER (same behavior as before).
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        files = []
        if ctx.and_merge and ctx.ter_file:
            files = mkv_utils.extract_attachments(ctx.ter_file, ctx.temp_dir, runner, ctx.tool_paths, 'ter') or []
        ctx.attachments = files
        return ctx
