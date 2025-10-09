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
from vsg_core.subtitles.timing import fix_subtitle_timing

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

            if item.user_modified_path and not item.style_patch:
                runner._log_message(f"[Subtitles] Using manually edited file for track {item.track.id}.")
                shutil.copy(item.user_modified_path, item.extracted_path)
            elif item.user_modified_path and item.style_patch:
                runner._log_message(f"[Subtitles] Ignoring temp preview file for track {item.track.id} (will apply style patch after conversion).")

            if item.perform_ocr and item.extracted_path:
                ocr_output_path = run_ocr(
                    str(item.extracted_path.with_suffix('.idx')),
                    item.track.props.lang,
                    runner,
                    ctx.tool_paths,
                    ctx.settings_dict
                )
                if ocr_output_path:
                    ocr_file = Path(ocr_output_path)
                    if not ocr_file.exists():
                        raise RuntimeError(
                            f"OCR failed for track {item.track.id}: "
                            f"Output file was not created at {ocr_output_path}"
                        )
                    # FIXED: Changed from == 0 to < 50 to allow for minimal SRT headers
                    if ocr_file.stat().st_size < 50:
                        raise RuntimeError(
                            f"OCR failed for track {item.track.id}: "
                            f"Output file is nearly empty at {ocr_output_path} "
                            f"(size: {ocr_file.stat().st_size} bytes)"
                        )

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

                    item.extracted_path = Path(ocr_output_path)
                    item.track = Track(
                        source=item.track.source, id=item.track.id, type=item.track.type,
                        props=StreamProps(
                            codec_id="S_TEXT/UTF8",
                            lang=original_props.lang,
                            name=original_props.name
                        )
                    )

                    if item.perform_ocr_cleanup:
                        report = run_cleanup(ocr_output_path, ctx.settings_dict, runner)
                        if report:
                            runner._log_message("--- OCR Cleanup Report ---")
                            for key, value in report.items():
                                runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                            runner._log_message("------------------------")

                    if ctx.settings_dict.get('timing_fix_enabled', False):
                        timing_report = fix_subtitle_timing(ocr_output_path, ctx.settings_dict, runner)
                        if timing_report:
                            runner._log_message("--- Subtitle Timing Report ---")
                            for key, value in timing_report.items():
                                runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                            runner._log_message("--------------------------")

                else:
                    raise RuntimeError(
                        f"OCR failed for track {item.track.id} "
                        f"({item.track.props.name or 'Unnamed'}). "
                        f"Check that subtile-ocr is installed and the IDX/SUB files are valid."
                    )

            if item.convert_to_ass and item.extracted_path and item.extracted_path.suffix.lower() == '.srt':
                new_path = convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                item.extracted_path = Path(new_path)

            if item.style_patch and item.extracted_path:
                if item.extracted_path.suffix.lower() in ['.ass', '.ssa']:
                    runner._log_message(f"[Style] Applying style patch to track {item.track.id}...")
                    engine = StyleEngine(str(item.extracted_path))
                    if engine.subs:
                        for style_name, changes in item.style_patch.items():
                            if style_name in engine.subs.styles:
                                engine.update_style_attributes(style_name, changes)
                        engine.save()
                        runner._log_message("[Style] Patch applied successfully.")
                    else:
                        runner._log_message("[Style] WARNING: Could not load subtitle file to apply patch.")
                else:
                    runner._log_message(f"[Style] WARNING: Cannot apply style patch to {item.extracted_path.suffix} file. Patch requires ASS/SSA format.")

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
