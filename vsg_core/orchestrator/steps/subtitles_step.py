# vsg_core/orchestrator/steps/subtitles_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import shutil
import copy

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.enums import TrackType
from vsg_core.models.media import StreamProps, Track
from vsg_core.subtitles.convert import convert_srt_to_ass
from vsg_core.subtitles.rescale import rescale_subtitle
from vsg_core.subtitles.style import multiply_font_size
from vsg_core.subtitles.style_engine import StyleEngine
from vsg_core.subtitles.ocr import run_ocr
from vsg_core.subtitles.cleanup import run_cleanup

class SubtitlesStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            runner._log_message("[WARN] No Source 1 file found for subtitle rescaling reference.")

        items_to_add = []
        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            # Handle user-modified files first, as they are the starting point.
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

            # --- OCR Step ---
            if item.perform_ocr and item.extracted_path:
                ocr_output_path = run_ocr(
                    str(item.extracted_path.with_suffix('.idx')),
                    item.track.props.lang,
                    runner,
                    ctx.tool_paths,
                    ctx.settings_dict
                )
                if ocr_output_path:
                    # Preserve the original track
                    preserved_item = copy.deepcopy(item)
                    preserved_item.is_preserved = True
                    original_props = preserved_item.track.props
                    preserved_item.track = Track(
                        source=preserved_item.track.source, id=preserved_item.track.id, type=preserved_item.track.type,
                        props=StreamProps(
                            codec_id=original_props.codec_id,
                            lang=original_props.lang,
                            name=f"{original_props.name} (Original)" if original_props.name else "Original"
                        )
                    )
                    items_to_add.append(preserved_item)

                    # Update the current item to be the new SRT track
                    item.extracted_path = Path(ocr_output_path)
                    item.track = Track(
                        source=item.track.source, id=item.track.id, type=item.track.type,
                        props=StreamProps(
                            codec_id="S_TEXT/UTF8",
                            lang=original_props.lang,
                            name=original_props.name
                        )
                    )

                    # --- Post-OCR Cleanup Step ---
                    if item.perform_ocr_cleanup:
                        report = run_cleanup(ocr_output_path, ctx.settings_dict, runner)
                        if report:
                            runner._log_message("--- OCR Cleanup Report ---")
                            for key, value in report.items():
                                runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                            runner._log_message("------------------------")

                else:
                    runner._log_message(f"[WARN] OCR failed for track {item.track.id}. Using original.")

            if item.convert_to_ass and item.extracted_path and item.extracted_path.suffix.lower() == '.srt':
                new_path = convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                item.extracted_path = Path(new_path)

            if item.rescale and source1_file:
                rescale_subtitle(str(item.extracted_path), source1_file, runner, ctx.tool_paths)

            size_mult = float(item.size_multiplier)
            if abs(size_mult - 1.0) > 1e-6:
                if 0.5 <= size_mult <= 3.0:
                    multiply_font_size(str(item.extracted_path), size_mult, runner)
                else:
                    runner._log_message(f"[Font Size] WARNING: Ignoring unreasonable size multiplier {size_mult:.2f}x for track {item.track.id}. Using 1.0x instead.")

        if items_to_add:
            ctx.extracted_items.extend(items_to_add)

        return ctx
