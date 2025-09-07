# vsg_core/orchestrator/steps/subtitles_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import shutil

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.enums import TrackType

from vsg_core.subtitles.convert import convert_srt_to_ass
from vsg_core.subtitles.rescale import rescale_subtitle
from vsg_core.subtitles.style import multiply_font_size


class SubtitlesStep:
    """
    Applies subtitle transforms per rules, prioritizing user-edited files.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        user_edited_map = {}
        for layout_item in ctx.manual_layout:
            if layout_item.get('user_modified_path'):
                key = (layout_item.get('source', '').upper(), layout_item.get('id'))
                user_edited_map[key] = layout_item['user_modified_path']

        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            lookup_key = (item.track.source.name, item.track.id)
            user_edited_file = user_edited_map.get(lookup_key)

            if user_edited_file and Path(user_edited_file).exists():
                runner._log_message(f"[Subtitles] Using user-edited style file for track {item.track.id}.")
                shutil.copy(user_edited_file, item.extracted_path)
                continue

            if item.convert_to_ass:
                new_path = convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                item.extracted_path = Path(new_path)

            if item.rescale:
                rescale_subtitle(str(item.extracted_path), ctx.ref_file, runner, ctx.tool_paths)

            try:
                if abs(float(item.size_multiplier) - 1.0) > 1e-6:
                    multiply_font_size(str(item.extracted_path), float(item.size_multiplier), runner)
            except Exception:
                pass

        return ctx
