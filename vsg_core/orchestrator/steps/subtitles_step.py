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
from vsg_core.subtitles.style_engine import StyleEngine


class SubtitlesStep:
    """
    Applies subtitle transforms per rules, prioritizing files modified by the editor.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            # First, handle SRT to ASS conversion if requested, as it's a prerequisite for styling.
            if item.convert_to_ass:
                if item.extracted_path and Path(item.extracted_path).suffix.lower() == '.srt':
                    new_path = convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                    item.extracted_path = Path(new_path)

            # If the file was touched by the Style Editor...
            if item.user_modified_path:
                runner._log_message(f"[Subtitles] Using editor-modified file for track {item.track.id}.")
                # Copy the final, edited version to the location the muxer expects.
                shutil.copy(item.user_modified_path, item.extracted_path)

                # Now, apply a patch if one was generated. The patch is applied to the
                # file that was just copied, which already contains other editor changes (like resampling).
                if item.style_patch:
                    runner._log_message(f"[Style] Applying patch to track {item.track.id}...")
                    engine = StyleEngine(str(item.extracted_path))
                    if engine.subs:
                        for style_name, changes in item.style_patch.items():
                            if style_name in engine.subs.styles:
                                engine.update_style_attributes(style_name, changes)
                        engine.save()
                        runner._log_message(f"[Style] Patch applied successfully.")
                    else:
                        runner._log_message(f"[Style] WARNING: Could not load subtitle file to apply patch.")

                # Since the editor was used, this file is considered final. Skip other transforms.
                continue

            # --- The following automated logic only runs if the Style Editor was NOT used ---
            if item.rescale:
                rescale_subtitle(str(item.extracted_path), ctx.ref_file, runner, ctx.tool_paths)

            try:
                if abs(float(item.size_multiplier) - 1.0) > 1e-6:
                    multiply_font_size(str(item.extracted_path), float(item.size_multiplier), runner)
            except Exception:
                pass

        return ctx
