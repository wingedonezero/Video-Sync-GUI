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
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        # Ensure ctx is valid
        if ctx is None:
            runner._log_message("[ERROR] Context is None in SubtitlesStep")
            raise RuntimeError("Context is None in SubtitlesStep")

        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            runner._log_message("[WARN] No Source 1 file found for subtitle rescaling reference.")

        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            if item.convert_to_ass and item.extracted_path and item.extracted_path.suffix.lower() == '.srt':
                new_path = convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                item.extracted_path = Path(new_path)

            if item.user_modified_path:
                runner._log_message(f"[Subtitles] Using editor-modified file for track {item.track.id}.")
                shutil.copy(item.user_modified_path, item.extracted_path)
                if item.style_patch:
                    runner._log_message(f"[Style] Applying patch to track {item.track.id}...")
                    engine = StyleEngine(str(item.extracted_path))
                    if engine.subs:
                        for style_name, changes in item.style_patch.items():
                            if style_name in engine.subs.styles:
                                engine.update_style_attributes(style_name, changes)
                        engine.save()
                        runner._log_message("[Style] Patch applied successfully.")
                    else:
                        runner._log_message("[Style] WARNING: Could not load subtitle file to apply patch.")
                continue

            if item.rescale and source1_file:
                rescale_subtitle(str(item.extracted_path), source1_file, runner, ctx.tool_paths)

            # Safety check: Only apply size multiplier if it's significantly different from 1.0
            # and within reasonable bounds (0.5 to 3.0)
            size_mult = float(item.size_multiplier)
            if abs(size_mult - 1.0) > 1e-6:
                if 0.5 <= size_mult <= 3.0:
                    multiply_font_size(str(item.extracted_path), size_mult, runner)
                else:
                    runner._log_message(f"[Font Size] WARNING: Ignoring unreasonable size multiplier {size_mult:.2f}x for track {item.track.id}. Using 1.0x instead.")

        # IMPORTANT: Always return the context
        return ctx
