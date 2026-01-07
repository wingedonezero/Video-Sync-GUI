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
from vsg_core.subtitles.stepping_adjust import apply_stepping_to_subtitles
from vsg_core.subtitles.frame_sync import apply_raw_delay_sync, apply_duration_align_sync, apply_correlation_frame_snap_sync

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
                        # OCR tool didn't create output file - this is a critical failure
                        runner._log_message(
                            f"[OCR] ERROR: Output file was not created at {ocr_output_path}. "
                            f"OCR completely failed for track {item.track.id}."
                        )
                        runner._log_message(
                            f"[OCR] WARNING: Keeping original image-based subtitle for track {item.track.id} "
                            f"({item.track.props.name or 'Unnamed'})."
                        )
                        # Don't raise - just skip OCR for this track and keep original
                        item.perform_ocr = False
                        continue

                    # Check if OCR produced meaningful output
                    file_size = ocr_file.stat().st_size
                    if file_size < 50:
                        # OCR produced an empty or nearly-empty file
                        runner._log_message(
                            f"[OCR] WARNING: OCR output is nearly empty for track {item.track.id} "
                            f"({item.track.props.name or 'Unnamed'}). "
                            f"File size: {file_size} bytes."
                        )
                        runner._log_message(
                            f"[OCR] This likely means the subtitle track is empty or contains no recognizable text."
                        )
                        runner._log_message(
                            f"[OCR] Keeping original image-based subtitle instead."
                        )
                        # Don't raise - just skip OCR for this track and keep original
                        item.perform_ocr = False

                        # Clean up the empty OCR file
                        try:
                            ocr_file.unlink()
                        except Exception as e:
                            runner._log_message(f"[OCR] Note: Could not delete empty OCR file: {e}")

                        continue

                    # OCR succeeded - proceed with processing
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

                    # Apply stepping correction to subtitle timestamps (if applicable)
                    if ctx.settings_dict.get('stepping_adjust_subtitles', True):
                        source_key = item.track.source
                        if source_key in ctx.stepping_edls:
                            stepping_report = apply_stepping_to_subtitles(
                                str(item.extracted_path),
                                ctx.stepping_edls[source_key],
                                runner,
                                ctx.settings_dict
                            )
                            if stepping_report and 'error' not in stepping_report:
                                runner._log_message("--- Stepping Adjustment Report ---")
                                for key, value in stepping_report.items():
                                    runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                runner._log_message("--------------------------------")
                                # Mark that timestamps have been adjusted (so mux doesn't double-apply delay)
                                item.stepping_adjusted = True

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
                    # run_ocr returned None - complete failure
                    runner._log_message(
                        f"[OCR] ERROR: OCR tool failed for track {item.track.id} "
                        f"({item.track.props.name or 'Unnamed'}). "
                        f"Check that subtile-ocr is installed and the IDX/SUB files are valid."
                    )
                    runner._log_message(
                        f"[OCR] WARNING: Keeping original image-based subtitle for track {item.track.id}."
                    )
                    # Don't raise - just skip OCR for this track
                    item.perform_ocr = False
                    continue

            # Apply stepping correction to subtitle timestamps for non-OCR subtitles
            # (OCR subtitles already handled above)
            if not item.perform_ocr and item.extracted_path:
                if ctx.settings_dict.get('stepping_adjust_subtitles', True):
                    source_key = item.track.source
                    if source_key in ctx.stepping_edls:
                        stepping_report = apply_stepping_to_subtitles(
                            str(item.extracted_path),
                            ctx.stepping_edls[source_key],
                            runner,
                            ctx.settings_dict
                        )
                        if stepping_report and 'error' not in stepping_report:
                            runner._log_message("--- Stepping Adjustment Report ---")
                            for key, value in stepping_report.items():
                                runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                            runner._log_message("--------------------------------")
                            # Mark that timestamps have been adjusted (so mux doesn't double-apply delay)
                            item.stepping_adjusted = True

            # Apply subtitle sync mode (when not using stepping)
            # This applies to both OCR and non-OCR subtitles
            if item.extracted_path and not item.stepping_adjusted:
                subtitle_sync_mode = ctx.settings_dict.get('subtitle_sync_mode', 'time-based')

                # Check for time-based with raw values option
                if subtitle_sync_mode == 'time-based':
                    use_raw_values = ctx.settings_dict.get('time_based_use_raw_values', False)
                    if use_raw_values:
                        # Time-based with raw values - apply delay using pysubs
                        ext = item.extracted_path.suffix.lower()
                        supported_formats = ['.ass', '.ssa', '.srt', '.vtt']

                        if ext in supported_formats:
                            source_key = item.sync_to if item.track.source == 'External' else item.track.source
                            audio_delay_ms = 0.0
                            if ctx.delays and source_key in ctx.delays.raw_source_delays_ms:
                                audio_delay_ms = ctx.delays.raw_source_delays_ms[source_key]
                                runner._log_message(f"[Time-Based Raw] Using raw audio delay: {audio_delay_ms:+.3f}ms from {source_key}")

                            runner._log_message(f"[Time-Based Raw] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")

                            frame_sync_report = apply_raw_delay_sync(
                                str(item.extracted_path),
                                audio_delay_ms,
                                runner,
                                ctx.settings_dict
                            )

                            if frame_sync_report and 'error' not in frame_sync_report:
                                runner._log_message(f"--- Time-Based Raw Sync Report ---")
                                for key, value in frame_sync_report.items():
                                    runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                runner._log_message("------------------------------------------")
                                # Mark that timestamps have been adjusted (so mux uses --sync 0:0)
                                item.frame_adjusted = True
                            else:
                                runner._log_message(f"[Time-Based Raw] WARNING: Sync failed for track {item.track.id}")
                        else:
                            runner._log_message(f"[Time-Based Raw] Skipping track {item.track.id} - format {ext} not supported")
                    # else: default time-based mode uses mkvmerge --sync, no processing needed here

                elif subtitle_sync_mode in ['duration-align', 'correlation-frame-snap']:
                    # Check if this subtitle format supports advanced sync
                    ext = item.extracted_path.suffix.lower()
                    supported_formats = ['.ass', '.ssa', '.srt', '.vtt']

                    if ext in supported_formats:
                        # Duration-Align mode: Frame alignment via total duration difference
                        if subtitle_sync_mode == 'duration-align':
                            # Requires source and target videos
                            source_key = item.sync_to if item.track.source == 'External' else item.track.source
                            source_video = ctx.sources.get(source_key)
                            target_video = source1_file

                            # Get raw global shift (NOT source-specific delay)
                            global_shift_ms = 0.0
                            if ctx.delays:
                                global_shift_ms = ctx.delays.raw_global_shift_ms
                                runner._log_message(f"[Duration Align] Using raw global shift: {global_shift_ms:+.3f}ms")

                            if source_video and target_video:
                                runner._log_message(f"[Duration Align] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                runner._log_message(f"[Duration Align] Source video: {Path(source_video).name}")
                                runner._log_message(f"[Duration Align] Target video: {Path(target_video).name}")

                                # Check if this track should skip frame validation (for generated tracks)
                                sync_config = ctx.settings_dict.copy()
                                if item.skip_frame_validation:
                                    runner._log_message(f"[Duration Align] Skipping frame validation for this track (generated track)")
                                    sync_config['duration_align_validate'] = False

                                frame_sync_report = apply_duration_align_sync(
                                    str(item.extracted_path),
                                    str(source_video),
                                    str(target_video),
                                    global_shift_ms,
                                    runner,
                                    sync_config
                                )

                                if frame_sync_report and 'error' not in frame_sync_report:
                                    runner._log_message(f"--- Duration Align Sync Report ---")
                                    for key, value in frame_sync_report.items():
                                        runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                    runner._log_message("------------------------------------------")
                                    # Mark that timestamps have been adjusted
                                    item.frame_adjusted = True
                                elif frame_sync_report and 'error' in frame_sync_report:
                                    # Sync function returned error - this is a fatal error (abort mode)
                                    error_msg = frame_sync_report['error']
                                    runner._log_message(f"[Duration Align] ERROR: Sync failed for track {item.track.id}: {error_msg}")
                                    raise RuntimeError(f"Duration-align sync failed for track {item.track.id}: {error_msg}")
                                else:
                                    # No report returned at all - unexpected
                                    runner._log_message(f"[Duration Align] ERROR: No sync report returned for track {item.track.id}")
                                    raise RuntimeError(f"Duration-align sync failed for track {item.track.id}: No report returned")
                            else:
                                runner._log_message(f"[Duration Align] ERROR: Missing source or target video")
                                runner._log_message(f"[Duration Align] Source: {source_video}, Target: {target_video}")

                            # Skip the delay-based sync logic for duration-align mode
                            continue

                        # Correlation + Frame Snap mode: Use correlation as authoritative, refined to frame boundaries
                        if subtitle_sync_mode == 'correlation-frame-snap':
                            # Requires source and target videos + correlation delay
                            source_key = item.sync_to if item.track.source == 'External' else item.track.source
                            source_video = ctx.sources.get(source_key)
                            target_video = source1_file

                            # CRITICAL: Get the TOTAL delay (which ALREADY includes global_shift)
                            # raw_source_delays_ms has global_shift baked in from analysis step
                            total_delay_with_global_ms = 0.0
                            if ctx.delays and source_key in ctx.delays.raw_source_delays_ms:
                                total_delay_with_global_ms = ctx.delays.raw_source_delays_ms[source_key]
                                runner._log_message(f"[Correlation+FrameSnap] Total delay (with global): {total_delay_with_global_ms:+.3f}ms from {source_key}")

                            # Get raw global shift separately (for the function to subtract and get pure correlation)
                            raw_global_shift_ms = 0.0
                            if ctx.delays:
                                raw_global_shift_ms = ctx.delays.raw_global_shift_ms
                                runner._log_message(f"[Correlation+FrameSnap] Global shift: {raw_global_shift_ms:+.3f}ms")

                            if source_video and target_video:
                                runner._log_message(f"[Correlation+FrameSnap] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                runner._log_message(f"[Correlation+FrameSnap] Source video: {Path(source_video).name}")
                                runner._log_message(f"[Correlation+FrameSnap] Target video: {Path(target_video).name}")

                                frame_sync_report = apply_correlation_frame_snap_sync(
                                    str(item.extracted_path),
                                    str(source_video),
                                    str(target_video),
                                    total_delay_with_global_ms,  # ALREADY includes global_shift
                                    raw_global_shift_ms,          # Passed separately for pure correlation calculation
                                    runner,
                                    ctx.settings_dict
                                )

                                if frame_sync_report and frame_sync_report.get('success'):
                                    runner._log_message(f"--- Correlation+FrameSnap Sync Report ---")
                                    for key, value in frame_sync_report.items():
                                        if key != 'verification':  # Skip nested verification dict
                                            runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                    runner._log_message("------------------------------------------")
                                    # Mark that timestamps have been adjusted
                                    item.frame_adjusted = True
                                elif frame_sync_report and 'error' in frame_sync_report:
                                    # Sync function returned error
                                    error_msg = frame_sync_report['error']
                                    runner._log_message(f"[Correlation+FrameSnap] ERROR: Sync failed for track {item.track.id}: {error_msg}")
                                    raise RuntimeError(f"Correlation+FrameSnap sync failed for track {item.track.id}: {error_msg}")
                                else:
                                    # No report or unexpected result
                                    runner._log_message(f"[Correlation+FrameSnap] ERROR: No sync report returned for track {item.track.id}")
                                    raise RuntimeError(f"Correlation+FrameSnap sync failed for track {item.track.id}: No report returned")
                            else:
                                runner._log_message(f"[Correlation+FrameSnap] ERROR: Missing source or target video")
                                runner._log_message(f"[Correlation+FrameSnap] Source: {source_video}, Target: {target_video}")
                                raise RuntimeError(f"Correlation+FrameSnap sync failed: missing source/target video")

                    else:
                        # Unsupported format (PGS/VOB bitmap subtitles)
                        # These can't be processed with advanced sync, but they still need
                        # the basic audio delay applied via mkvmerge --sync
                        runner._log_message(f"[{subtitle_sync_mode}] Skipping track {item.track.id} - format {ext} not supported (bitmap subtitle)")

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
