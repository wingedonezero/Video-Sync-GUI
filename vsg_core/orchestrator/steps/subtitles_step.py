# vsg_core/orchestrator/steps/subtitles_step.py
# -*- coding: utf-8 -*-
"""
Unified subtitle processing step using SubtitleData.

Flow:
1. Load subtitle into SubtitleData (single load)
2. Apply operations in order:
   - Stepping (EDL-based timing adjustment)
   - Sync mode (timing sync to target video)
   - Style operations (font replacement, style patch, rescale, size multiplier)
3. Save once at end (single rounding point)

All timing is float ms internally - rounding only at final save.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.subtitles.data import SubtitleData

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.enums import TrackType
from vsg_core.models.media import StreamProps, Track


class SubtitlesStep:
    """
    Unified subtitle processing step.

    Uses SubtitleData as the central container for all operations.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            runner._log_message("[WARN] No Source 1 file found for subtitle processing reference.")

        items_to_add = []
        _any_no_scene_fallback = False

        # Cache for scene detection results per source
        _scene_detection_cache = {}

        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            # Handle manually edited files
            if item.user_modified_path and not item.style_patch:
                runner._log_message(f"[Subtitles] Using manually edited file for track {item.track.id}.")
                shutil.copy(item.user_modified_path, item.extracted_path)
            elif item.user_modified_path and item.style_patch:
                runner._log_message(f"[Subtitles] Ignoring temp preview file for track {item.track.id} (will apply style patch after conversion).")

            # ================================================================
            # OCR Processing (if needed)
            # ================================================================
            ocr_subtitle_data = None
            if item.perform_ocr and item.extracted_path:
                ocr_result = self._process_ocr(item, ctx, runner, items_to_add)
                if ocr_result is None:
                    continue  # OCR failed, skip this track
                elif ocr_result is True:
                    # Legacy mode - file was written, proceed with file loading
                    pass
                else:
                    # Unified mode - SubtitleData returned directly
                    ocr_subtitle_data = ocr_result

            # ================================================================
            # Unified SubtitleData Processing
            # ================================================================
            if ocr_subtitle_data is not None:
                # OCR already gave us SubtitleData - use it directly
                try:
                    self._process_track_unified(
                        item, ctx, runner, source1_file,
                        _scene_detection_cache, items_to_add,
                        subtitle_data=ocr_subtitle_data
                    )
                except Exception as e:
                    runner._log_message(f"[Subtitles] ERROR processing track {item.track.id}: {e}")
                    raise
            elif item.extracted_path:
                ext = item.extracted_path.suffix.lower()
                supported_formats = ['.ass', '.ssa', '.srt', '.vtt']

                if ext in supported_formats:
                    try:
                        self._process_track_unified(
                            item, ctx, runner, source1_file,
                            _scene_detection_cache, items_to_add
                        )
                    except Exception as e:
                        runner._log_message(f"[Subtitles] ERROR processing track {item.track.id}: {e}")
                        raise
                else:
                    # Bitmap subtitles - can't process with unified flow
                    runner._log_message(f"[Subtitles] Track {item.track.id}: format {ext} not supported for unified processing")

        # Set context flag if any track used raw delay fallback
        if _any_no_scene_fallback:
            ctx.correlation_snap_no_scenes_fallback = True

        if items_to_add:
            ctx.extracted_items.extend(items_to_add)

        return ctx

    def _process_track_unified(
        self,
        item,
        ctx: Context,
        runner: CommandRunner,
        source1_file: Optional[Path],
        scene_cache: Dict[str, Any],
        items_to_add: list,
        subtitle_data: Optional['SubtitleData'] = None
    ) -> None:
        """
        Process a subtitle track using the unified SubtitleData flow.

        1. Load into SubtitleData (or use provided SubtitleData from OCR)
        2. Apply stepping (if applicable)
        3. Apply sync mode
        4. Apply style operations
        5. Save (single rounding point)

        Args:
            subtitle_data: Optional pre-loaded SubtitleData (from OCR).
                          If provided, skips file loading step.
        """
        from vsg_core.subtitles.data import SubtitleData as SubtitleDataClass

        subtitle_sync_mode = ctx.settings_dict.get('subtitle_sync_mode', 'time-based')
        logs_dir = Path(ctx.settings_dict.get('logs_folder', ctx.temp_dir))

        # ================================================================
        # STEP 1: Load into SubtitleData (or use provided)
        # ================================================================
        if subtitle_data is not None:
            # SubtitleData provided (from OCR)
            runner._log_message(f"[SubtitleData] Using OCR SubtitleData for track {item.track.id}")
            runner._log_message(f"[SubtitleData] {len(subtitle_data.events)} events, OCR metadata preserved")
        else:
            # Load from file
            runner._log_message(f"[SubtitleData] Loading track {item.track.id}: {item.extracted_path.name}")

            try:
                subtitle_data = SubtitleDataClass.from_file(item.extracted_path)
                runner._log_message(f"[SubtitleData] Loaded {len(subtitle_data.events)} events, {len(subtitle_data.styles)} styles")
            except Exception as e:
                runner._log_message(f"[SubtitleData] ERROR: Failed to load: {e}")
                raise

        # ================================================================
        # STEP 1b: Apply Style Filtering (for generated tracks)
        # ================================================================
        if item.is_generated and item.generated_filter_styles:
            runner._log_message(f"[SubtitleData] Applying style filter for generated track...")
            result = subtitle_data.filter_by_styles(
                styles=item.generated_filter_styles,
                mode=item.generated_filter_mode or 'exclude',
                runner=runner
            )
            if result.success:
                runner._log_message(f"[SubtitleData] Style filter: {result.summary}")
                # Check for missing styles (validation already happened, just warn)
                if result.details and result.details.get('styles_missing'):
                    runner._log_message(
                        f"[SubtitleData] WARNING: Filter styles not found: "
                        f"{', '.join(result.details['styles_missing'])}"
                    )
            else:
                runner._log_message(f"[SubtitleData] Style filter failed: {result.error}")

        # ================================================================
        # STEP 2: Apply Stepping (if applicable)
        # ================================================================
        if ctx.settings_dict.get('stepping_adjust_subtitles', True):
            source_key = item.track.source
            if source_key in ctx.stepping_edls:
                runner._log_message(f"[SubtitleData] Applying stepping correction...")

                result = subtitle_data.apply_stepping(
                    edl_segments=ctx.stepping_edls[source_key],
                    boundary_mode=ctx.settings_dict.get('stepping_boundary_mode', 'start'),
                    runner=runner
                )

                if result.success:
                    runner._log_message(f"[SubtitleData] Stepping: {result.summary}")
                    item.stepping_adjusted = True
                else:
                    runner._log_message(f"[SubtitleData] Stepping failed: {result.error}")

        # ================================================================
        # STEP 3: Apply Sync Mode
        # ================================================================
        # For non-frame-locked modes with stepping already applied, skip sync
        should_apply_sync = True
        if item.stepping_adjusted and subtitle_sync_mode not in ['timebase-frame-locked-timestamps']:
            should_apply_sync = False
            runner._log_message(f"[SubtitleData] Skipping {subtitle_sync_mode} - stepping already applied")

        if should_apply_sync:
            sync_result = self._apply_sync_unified(
                item, subtitle_data, ctx, runner, source1_file, subtitle_sync_mode, scene_cache
            )

            if sync_result and sync_result.success:
                item.frame_adjusted = True
                if hasattr(sync_result, 'details'):
                    item.framelocked_stats = sync_result.details

        # ================================================================
        # STEP 4: Apply SRT to ASS Conversion (if needed)
        # ================================================================
        output_format = '.ass'
        if item.convert_to_ass and item.extracted_path.suffix.lower() == '.srt':
            # Conversion happens at save - SubtitleData can save to any format
            runner._log_message(f"[SubtitleData] Will convert SRT to ASS at save")
            output_format = '.ass'
        else:
            output_format = item.extracted_path.suffix.lower()

        # ================================================================
        # STEP 5: Apply Style Operations
        # ================================================================

        # Font replacements
        if item.font_replacements:
            runner._log_message(f"[SubtitleData] Applying font replacements...")
            result = subtitle_data.apply_font_replacement(item.font_replacements, runner)
            if result.success:
                runner._log_message(f"[SubtitleData] Font replacement: {result.summary}")

        # Style patches
        if item.style_patch:
            runner._log_message(f"[SubtitleData] Applying style patch...")
            result = subtitle_data.apply_style_patch(item.style_patch, runner)
            if result.success:
                runner._log_message(f"[SubtitleData] Style patch: {result.summary}")

        # Rescale
        if item.rescale and source1_file:
            runner._log_message(f"[SubtitleData] Applying rescale...")
            target_res = self._get_video_resolution(source1_file, runner, ctx)
            if target_res:
                result = subtitle_data.apply_rescale(target_res, runner)
                if result.success:
                    runner._log_message(f"[SubtitleData] Rescale: {result.summary}")

        # Size multiplier
        size_mult = float(item.size_multiplier) if hasattr(item, 'size_multiplier') else 1.0
        if abs(size_mult - 1.0) > 1e-6:
            if 0.5 <= size_mult <= 3.0:
                runner._log_message(f"[SubtitleData] Applying size multiplier: {size_mult}x")
                result = subtitle_data.apply_size_multiplier(size_mult, runner)
                if result.success:
                    runner._log_message(f"[SubtitleData] Size multiplier: {result.summary}")
            else:
                runner._log_message(f"[SubtitleData] WARNING: Ignoring unreasonable size multiplier {size_mult:.2f}x")

        # ================================================================
        # STEP 6: Save JSON (ALWAYS - before ASS/SRT to preserve all data)
        # ================================================================
        # JSON contains all metadata that would be lost in ASS/SRT
        # Always write to temp folder so it can be grabbed for debugging
        json_path = ctx.temp_dir / f"subtitle_data_track_{item.track.id}.json"
        try:
            subtitle_data.save_json(json_path)
            runner._log_message(f"[SubtitleData] JSON saved: {json_path.name}")
        except Exception as e:
            runner._log_message(f"[SubtitleData] WARNING: Could not save JSON: {e}")

        # For OCR with debug enabled, also copy to OCR debug folder
        if item.perform_ocr and ctx.settings_dict.get('ocr_debug_output', False):
            ocr_debug_dir = self._get_ocr_debug_dir(item, ctx)
            if ocr_debug_dir:
                ocr_json_path = ocr_debug_dir / "subtitle_data.json"
                try:
                    subtitle_data.save_json(ocr_json_path)
                    runner._log_message(f"[SubtitleData] OCR debug JSON saved: {ocr_json_path}")
                except Exception as e:
                    runner._log_message(f"[SubtitleData] WARNING: Could not save OCR debug JSON: {e}")

        # ================================================================
        # STEP 7: Save ASS/SRT (SINGLE ROUNDING POINT)
        # ================================================================
        output_path = item.extracted_path.with_suffix(output_format)

        runner._log_message(f"[SubtitleData] Saving to {output_path.name}...")
        try:
            rounding_mode = ctx.settings_dict.get('subtitle_rounding', 'floor')
            subtitle_data.save(output_path, rounding=rounding_mode)
            item.extracted_path = output_path
            runner._log_message(f"[SubtitleData] Saved successfully ({len(subtitle_data.events)} events)")
        except Exception as e:
            runner._log_message(f"[SubtitleData] ERROR: Failed to save: {e}")
            raise

        # Update track codec if format changed
        if output_path.suffix.lower() == '.ass':
            item.track = Track(
                source=item.track.source,
                id=item.track.id,
                type=item.track.type,
                props=StreamProps(
                    codec_id="S_TEXT/ASS",
                    lang=item.track.props.lang,
                    name=item.track.props.name
                )
            )

        # Log summary
        runner._log_message(f"[SubtitleData] Track {item.track.id} complete: {len(subtitle_data.operations)} operations applied")

    def _apply_sync_unified(
        self,
        item,
        subtitle_data,
        ctx: Context,
        runner: CommandRunner,
        source1_file: Optional[Path],
        sync_mode: str,
        scene_cache: Dict[str, Any]
    ):
        """Apply sync mode using unified SubtitleData flow."""
        from vsg_core.subtitles.sync_modes import get_sync_plugin

        # Get source and delays
        source_key = item.sync_to if item.track.source == 'External' else item.track.source
        source_video = ctx.sources.get(source_key)
        target_video = source1_file

        # Get delays
        total_delay_ms = 0.0
        global_shift_ms = 0.0
        if ctx.delays:
            if source_key in ctx.delays.raw_source_delays_ms:
                total_delay_ms = ctx.delays.raw_source_delays_ms[source_key]
            global_shift_ms = ctx.delays.raw_global_shift_ms

        # Get target FPS
        target_fps = None
        if target_video:
            try:
                from vsg_core.subtitles.frame_utils import detect_video_fps
                target_fps = detect_video_fps(str(target_video), runner)
            except Exception as e:
                runner._log_message(f"[Sync] WARNING: Could not detect FPS: {e}")

        runner._log_message(f"[Sync] Mode: {sync_mode}")
        runner._log_message(f"[Sync] Delay: {total_delay_ms:+.3f}ms (global: {global_shift_ms:+.3f}ms)")

        # Try to use new plugin system
        plugin = get_sync_plugin(sync_mode)

        if plugin:
            # Use new unified plugin
            runner._log_message(f"[Sync] Using plugin: {plugin.name}")

            result = plugin.apply(
                subtitle_data=subtitle_data,
                total_delay_ms=total_delay_ms,
                global_shift_ms=global_shift_ms,
                target_fps=target_fps,
                source_video=str(source_video) if source_video else None,
                target_video=str(target_video) if target_video else None,
                runner=runner,
                config=ctx.settings_dict,
                temp_dir=ctx.temp_dir,
                sync_exclusion_styles=getattr(item, 'sync_exclusion_styles', None),
                sync_exclusion_mode=getattr(item, 'sync_exclusion_mode', 'exclude'),
            )

            if result.success:
                runner._log_message(f"[Sync] {result.summary}")
            else:
                runner._log_message(f"[Sync] WARNING: {result.error or 'Sync failed'}")

            return result

        else:
            # All sync modes should have plugins - unknown mode
            from vsg_core.subtitles.data import OperationResult
            runner._log_message(f"[Sync] ERROR: Unknown sync mode: {sync_mode}")
            return OperationResult(
                success=False,
                operation='sync',
                error=f'Unknown sync mode: {sync_mode}'
            )

    def _process_ocr(self, item, ctx, runner, items_to_add):
        """
        Process OCR for a track.

        Returns:
            - SubtitleData if unified OCR succeeded
            - True if legacy OCR succeeded (file written)
            - None if OCR failed/skipped
        """
        from vsg_core.subtitles.ocr import run_ocr_unified

        ocr_work_dir = ctx.temp_dir / 'ocr'
        logs_dir = Path(ctx.settings_dict.get('logs_folder', ctx.temp_dir))

        if ctx.settings_dict.get('ocr_run_in_subprocess', False):
            subtitle_data = self._run_ocr_subprocess(
                item=item,
                ctx=ctx,
                runner=runner,
                ocr_work_dir=ocr_work_dir,
                logs_dir=logs_dir,
            )
        else:
            subtitle_data = run_ocr_unified(
                str(item.extracted_path.with_suffix('.idx')),
                item.track.props.lang,
                runner,
                ctx.tool_paths,
                ctx.settings_dict,
                work_dir=ocr_work_dir,
                logs_dir=logs_dir,
                track_id=item.track.id
            )

        if subtitle_data is None:
            runner._log_message(f"[OCR] ERROR: OCR failed for track {item.track.id}")
            runner._log_message(f"[OCR] Keeping original image-based subtitle")
            item.perform_ocr = False
            return None

        # Check if we got valid events
        if not subtitle_data.events:
            runner._log_message(f"[OCR] WARNING: OCR produced no events for track {item.track.id}")
            item.perform_ocr = False
            return None

        # OCR succeeded - create preserved copy of original
        preserved_item = copy.deepcopy(item)
        preserved_item.is_preserved = True
        original_props = preserved_item.track.props
        preserved_item.track = Track(
            source=preserved_item.track.source,
            id=preserved_item.track.id,
            type=preserved_item.track.type,
            props=StreamProps(
                codec_id=original_props.codec_id,
                lang=original_props.lang,
                name=f"{original_props.name} (Original)" if original_props.name else "Original"
            )
        )
        items_to_add.append(preserved_item)

        # Update item to reflect OCR output
        # Set expected output path for later save
        item.extracted_path = item.extracted_path.with_suffix('.ass')
        item.track = Track(
            source=item.track.source,
            id=item.track.id,
            type=item.track.type,
            props=StreamProps(
                codec_id="S_TEXT/ASS",
                lang=original_props.lang,
                name=original_props.name
            )
        )

        return subtitle_data

    def _run_ocr_subprocess(self, item, ctx, runner, ocr_work_dir: Path, logs_dir: Path):
        from vsg_core.subtitles.data import SubtitleData

        config_path = ctx.temp_dir / f"ocr_config_track_{item.track.id}.json"
        output_json = ctx.temp_dir / f"subtitle_data_track_{item.track.id}.json"

        try:
            with open(config_path, 'w', encoding='utf-8') as config_file:
                json.dump(ctx.settings_dict, config_file, indent=2, ensure_ascii=False)
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to write OCR config: {e}")
            return None

        cmd = [
            sys.executable,
            "-m",
            "vsg_core.subtitles.ocr.unified_subprocess",
            "--subtitle-path",
            str(item.extracted_path.with_suffix('.idx')),
            "--lang",
            item.track.props.lang,
            "--config-json",
            str(config_path),
            "--output-json",
            str(output_json),
            "--work-dir",
            str(ocr_work_dir),
            "--logs-dir",
            str(logs_dir),
            "--track-id",
            str(item.track.id),
        ]

        runner._log_message(f"[OCR] Running OCR in subprocess for track {item.track.id}...")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
            )
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to start OCR subprocess: {e}")
            return None

        json_payload = None
        json_prefix = "__VSG_UNIFIED_OCR_JSON__ "

        if process.stdout:
            for line in process.stdout:
                line = line.rstrip('\n')
                if line.startswith(json_prefix):
                    try:
                        json_payload = json.loads(line.split(json_prefix, 1)[1])
                    except json.JSONDecodeError:
                        json_payload = None
                elif line:
                    runner._log_message(line)

        return_code = process.wait()

        if process.stderr:
            for line in process.stderr:
                line = line.rstrip('\n')
                if line:
                    runner._log_message(f"[OCR] {line}")

        if return_code != 0:
            error_detail = None
            if json_payload and not json_payload.get('success'):
                error_detail = json_payload.get('error')
            runner._log_message(f"[OCR] ERROR: OCR subprocess failed (code {return_code})")
            if error_detail:
                runner._log_message(f"[OCR] ERROR: {error_detail}")
            return None

        if not json_payload or not json_payload.get('success'):
            runner._log_message("[OCR] ERROR: OCR subprocess returned no result")
            return None

        json_path = json_payload.get('json_path')
        if not json_path:
            runner._log_message("[OCR] ERROR: OCR subprocess returned no JSON path")
            return None

        try:
            return SubtitleData.from_json(json_path)
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to load SubtitleData JSON: {e}")
            return None

    def _get_video_resolution(self, video_path: Path, runner, ctx) -> Optional[tuple]:
        """Get video resolution for rescaling."""
        try:
            from vsg_core.subtitles.frame_utils import get_video_properties
            props = get_video_properties(str(video_path), runner, ctx.tool_paths)
            if props:
                return (props.get('width', 1920), props.get('height', 1080))
        except Exception as e:
            runner._log_message(f"[Rescale] WARNING: Could not get video resolution: {e}")
        return None

    def _get_ocr_debug_dir(self, item, ctx) -> Optional[Path]:
        """
        Get OCR debug directory for a track if it exists.

        Looks for the debug folder created by OCR pipeline:
        {logs_dir}/{base_name}_ocr_debug_{timestamp}/
        """
        logs_dir = Path(ctx.settings_dict.get('logs_folder', ctx.temp_dir))

        # Find existing OCR debug directory for this track
        # Format: track_{id}_ocr_debug_* or similar
        try:
            base_name = item.extracted_path.stem if item.extracted_path else f"track_{item.track.id}"

            # Look for directories matching OCR debug pattern
            for path in logs_dir.iterdir():
                if path.is_dir() and '_ocr_debug_' in path.name:
                    # Check if this is the right track's debug dir
                    if base_name in path.name or f"track_{item.track.id}" in str(path):
                        return path

            # Also check temp_dir/ocr for debug output
            ocr_dir = ctx.temp_dir / 'ocr'
            if ocr_dir.exists():
                for path in ocr_dir.iterdir():
                    if path.is_dir() and 'debug' in path.name.lower():
                        return path

        except Exception:
            pass

        return None
