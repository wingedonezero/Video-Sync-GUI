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
from vsg_core.subtitles.frame_sync import apply_frame_perfect_sync, apply_videotimestamps_sync, apply_frame_snapped_sync, apply_dual_videotimestamps_sync, detect_video_fps
from vsg_core.subtitles.frame_matching import apply_frame_matched_sync

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

            # Apply frame-perfect or videotimestamps sync for uniform delays (when not using stepping)
            # This applies to both OCR and non-OCR subtitles
            if item.extracted_path and not item.stepping_adjusted:
                subtitle_sync_mode = ctx.settings_dict.get('subtitle_sync_mode', 'time-based')

                if subtitle_sync_mode in ['frame-perfect', 'videotimestamps', 'frame-snapped', 'frame-matched', 'dual-videotimestamps']:
                    # Check if this subtitle format supports frame-perfect sync
                    ext = item.extracted_path.suffix.lower()
                    supported_formats = ['.ass', '.ssa', '.srt', '.vtt']

                    if ext in supported_formats:
                        # Frame-matched mode uses audio delay for smart search centering
                        if subtitle_sync_mode == 'frame-matched':
                            # Frame-matched mode requires source and target videos
                            source_key = item.sync_to if item.track.source == 'External' else item.track.source
                            source_video = ctx.sources.get(source_key)
                            target_video = source1_file

                            # Get audio delay for smart search centering (optional)
                            audio_delay_ms = 0
                            if ctx.delays and source_key in ctx.delays.source_delays_ms:
                                audio_delay_ms = int(ctx.delays.source_delays_ms[source_key])
                                runner._log_message(f"[Frame-Matched Sync] Using audio delay for smart search: {audio_delay_ms:+d}ms")

                            if source_video and target_video:
                                runner._log_message(f"[Frame-Matched Sync] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                runner._log_message(f"[Frame-Matched Sync] Source video: {Path(source_video).name}")
                                runner._log_message(f"[Frame-Matched Sync] Target video: {Path(target_video).name}")

                                frame_sync_report = apply_frame_matched_sync(
                                    str(item.extracted_path),
                                    str(source_video),
                                    str(target_video),
                                    runner,
                                    ctx.settings_dict,
                                    audio_delay_ms=audio_delay_ms  # Pass audio delay for smart centering!
                                )

                                if frame_sync_report and 'error' not in frame_sync_report:
                                    runner._log_message(f"--- Frame-Matched Sync Report ---")
                                    for key, value in frame_sync_report.items():
                                        runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                    runner._log_message("-----------------------------------")
                                    # Mark that timestamps have been adjusted
                                    item.frame_adjusted = True
                                else:
                                    runner._log_message(f"[Frame-Matched Sync] WARNING: Sync failed for track {item.track.id}")
                            else:
                                runner._log_message(f"[Frame-Matched Sync] ERROR: Missing source or target video")
                                runner._log_message(f"[Frame-Matched Sync] Source: {source_video}, Target: {target_video}")

                            # Skip the delay-based sync logic for frame-matched mode
                            continue

                        # Dual-VideoTimestamps mode: Frame-accurate mapping using both videos' timestamps
                        if subtitle_sync_mode == 'dual-videotimestamps':
                            # Requires source and target videos (like frame-matched)
                            source_key = item.sync_to if item.track.source == 'External' else item.track.source
                            source_video = ctx.sources.get(source_key)
                            target_video = source1_file

                            # Get audio delay for subtitle positioning
                            audio_delay_ms = 0
                            if ctx.delays and source_key in ctx.delays.source_delays_ms:
                                audio_delay_ms = int(ctx.delays.source_delays_ms[source_key])
                                runner._log_message(f"[Dual VideoTimestamps] Using audio delay: {audio_delay_ms:+d}ms")

                            if source_video and target_video:
                                runner._log_message(f"[Dual VideoTimestamps] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                runner._log_message(f"[Dual VideoTimestamps] Source video: {Path(source_video).name}")
                                runner._log_message(f"[Dual VideoTimestamps] Target video: {Path(target_video).name}")

                                frame_sync_report = apply_dual_videotimestamps_sync(
                                    str(item.extracted_path),
                                    str(source_video),
                                    str(target_video),
                                    audio_delay_ms,
                                    runner,
                                    ctx.settings_dict
                                )

                                if frame_sync_report and 'error' not in frame_sync_report:
                                    runner._log_message(f"--- Dual VideoTimestamps Sync Report ---")
                                    for key, value in frame_sync_report.items():
                                        runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                    runner._log_message("------------------------------------------")
                                    # Mark that timestamps have been adjusted
                                    item.frame_adjusted = True
                                else:
                                    runner._log_message(f"[Dual VideoTimestamps] WARNING: Sync failed for track {item.track.id}")
                            else:
                                runner._log_message(f"[Dual VideoTimestamps] ERROR: Missing source or target video")
                                runner._log_message(f"[Dual VideoTimestamps] Source: {source_video}, Target: {target_video}")

                            # Skip the delay-based sync logic for dual-videotimestamps mode
                            continue

                        # Get the uniform delay for this source (for other modes)
                        source_key = item.sync_to if item.track.source == 'External' else item.track.source
                        delay_ms = 0

                        if ctx.delays and source_key in ctx.delays.source_delays_ms:
                            delay_ms = int(ctx.delays.source_delays_ms[source_key])
                            mode_label = "Frame-Snapped Sync" if subtitle_sync_mode == 'frame-snapped' else ("VideoTimestamps Sync" if subtitle_sync_mode == 'videotimestamps' else "Frame-Perfect Sync")
                            runner._log_message(f"[{mode_label}] DEBUG: source_key='{source_key}', delay from source_delays_ms={delay_ms}ms")
                            runner._log_message(f"[{mode_label}] DEBUG: All source_delays_ms: {ctx.delays.source_delays_ms}")
                            runner._log_message(f"[{mode_label}] DEBUG: Global shift: {ctx.delays.global_shift_ms}ms")
                        else:
                            mode_label = "Frame-Snapped Sync" if subtitle_sync_mode == 'frame-snapped' else ("VideoTimestamps Sync" if subtitle_sync_mode == 'videotimestamps' else "Frame-Perfect Sync")
                            runner._log_message(f"[{mode_label}] DEBUG: source_key='{source_key}' not found in delays or delays is None")
                            if ctx.delays:
                                runner._log_message(f"[{mode_label}] DEBUG: Available keys: {list(ctx.delays.source_delays_ms.keys())}")

                        # Only apply if there's a non-zero delay
                        if delay_ms != 0:
                            # Detect FPS from Source 1 video (or use manual override)
                            target_fps = ctx.settings_dict.get('subtitle_target_fps', None)

                            if target_fps is None or target_fps <= 0:
                                # Auto-detect FPS from Source 1
                                if source1_file:
                                    target_fps = detect_video_fps(source1_file, runner)
                                else:
                                    mode_label = "Frame-Snapped Sync" if subtitle_sync_mode == 'frame-snapped' else ("VideoTimestamps Sync" if subtitle_sync_mode == 'videotimestamps' else "Frame-Perfect Sync")
                                    runner._log_message(f"[{mode_label}] WARNING: No Source 1 video found, using default 23.976 fps")
                                    target_fps = 23.976
                            else:
                                mode_label = "Frame-Snapped Sync" if subtitle_sync_mode == 'frame-snapped' else ("VideoTimestamps Sync" if subtitle_sync_mode == 'videotimestamps' else "Frame-Perfect Sync")
                                runner._log_message(f"[{mode_label}] Using manual FPS: {target_fps:.3f}")

                            # Apply appropriate sync mode
                            if subtitle_sync_mode == 'videotimestamps':
                                # VideoTimestamps mode - pure library, no custom offsets
                                runner._log_message(f"[VideoTimestamps Sync] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                frame_sync_report = apply_videotimestamps_sync(
                                    str(item.extracted_path),
                                    delay_ms,
                                    target_fps,
                                    runner,
                                    ctx.settings_dict,
                                    video_path=source1_file  # Required for VideoTimestamps
                                )
                            elif subtitle_sync_mode == 'frame-snapped':
                                # Frame-snapped mode - snap start to frames, preserve duration
                                runner._log_message(f"[Frame-Snapped Sync] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                frame_sync_report = apply_frame_snapped_sync(
                                    str(item.extracted_path),
                                    delay_ms,
                                    target_fps,
                                    runner,
                                    ctx.settings_dict,
                                    video_path=source1_file
                                )
                            else:
                                # Frame-perfect mode - with middle/aegisub/vfr options
                                runner._log_message(f"[Frame-Perfect Sync] Applying to track {item.track.id} ({item.track.props.name or 'Unnamed'})")
                                frame_sync_report = apply_frame_perfect_sync(
                                    str(item.extracted_path),
                                    delay_ms,
                                    target_fps,
                                    runner,
                                    ctx.settings_dict,
                                    video_path=source1_file  # For VFR mode
                                )

                            if frame_sync_report and 'error' not in frame_sync_report:
                                mode_label = "Frame-Snapped Sync" if subtitle_sync_mode == 'frame-snapped' else ("VideoTimestamps Sync" if subtitle_sync_mode == 'videotimestamps' else "Frame-Perfect Sync")
                                runner._log_message(f"--- {mode_label} Report ---")
                                for key, value in frame_sync_report.items():
                                    runner._log_message(f"  - {key.replace('_', ' ').title()}: {value}")
                                runner._log_message("-----------------------------------")
                                # Mark that timestamps have been adjusted (so mux doesn't double-apply delay)
                                item.frame_adjusted = True
                    else:
                        # Unsupported format (PGS/VOB bitmap subtitles)
                        # These can't be processed with advanced sync, but they still need
                        # the basic audio delay applied via mkvmerge --sync
                        mode_label = "Frame-Snapped Sync" if subtitle_sync_mode == 'frame-snapped' else ("VideoTimestamps Sync" if subtitle_sync_mode == 'videotimestamps' else "Frame-Perfect Sync")
                        runner._log_message(f"[{mode_label}] Skipping track {item.track.id} - format {ext} not supported (bitmap subtitle)")

                        # Get the delay for this source
                        source_key = item.sync_to if item.track.source == 'External' else item.track.source
                        delay_ms = 0

                        if ctx.delays and source_key in ctx.delays.source_delays_ms:
                            delay_ms = int(ctx.delays.source_delays_ms[source_key])
                            runner._log_message(f"[{mode_label}] Track {item.track.id} will use mkvmerge --sync delay: {delay_ms:+d}ms (from {source_key})")
                        else:
                            runner._log_message(f"[{mode_label}] Track {item.track.id} will use mkvmerge --sync delay: 0ms (no delay found for {source_key})")

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
