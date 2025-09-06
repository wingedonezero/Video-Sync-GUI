# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.enums import TrackType
from vsg_core import subtitle_utils


class SubtitlesStep:
    """
    Applies subtitle transforms per rules:
      - Convert SRT -> ASS
      - Rescale PlayResX/Y to video resolution
      - Multiply style font size
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            if item.convert_to_ass:
                new_path = subtitle_utils.convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                from pathlib import Path
                item.extracted_path = Path(new_path)

            if item.rescale:
                subtitle_utils.rescale_subtitle(str(item.extracted_path), ctx.ref_file, runner, ctx.tool_paths)

            try:
                if abs(float(item.size_multiplier) - 1.0) > 1e-6:
                    subtitle_utils.multiply_font_size(str(item.extracted_path), float(item.size_multiplier), runner)
            except Exception:
                pass

        return ctx
