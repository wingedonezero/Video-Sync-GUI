# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.process import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core import mkv_utils


class ChaptersStep:
    """
    Extracts/renames/snaps/shifts chapter XML from the reference according to settings
    and global shift.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.chapters_xml = None
            return ctx

        shift_ms = ctx.delays.global_shift_ms if ctx.delays else 0
        xml_path = mkv_utils.process_chapters(
            ctx.ref_file,
            ctx.temp_dir,
            runner,
            ctx.tool_paths,
            ctx.settings_dict,
            shift_ms
        )
        ctx.chapters_xml = xml_path
        return ctx
