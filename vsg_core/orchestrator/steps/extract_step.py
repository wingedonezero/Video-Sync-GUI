# vsg_core/orchestrator/steps/extract_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Dict, Any, List

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import PlanItem
from vsg_core.models.media import Track, StreamProps
from vsg_core.models.enums import TrackType
from vsg_core.extraction.tracks import extract_tracks, get_stream_info_with_delays

class ExtractStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.extracted_items = []
            return ctx

        # CRITICAL FIX: Filter out video tracks from secondary sources BEFORE extraction
        # Video tracks are only allowed from Source 1
        filtered_layout = []
        for item in ctx.manual_layout:
            source = item.get('source', '')
            track_type = item.get('type', '')

            # Block video tracks from any source except Source 1
            if track_type == 'video' and source != 'Source 1':
                runner._log_message(f"[WARNING] Skipping video track from {source} (ID {item.get('id')}). Video is only allowed from Source 1.")
                continue

            filtered_layout.append(item)

        # Update the context with the filtered layout
        ctx.manual_layout = filtered_layout

        # --- Read container delays for all sources ---
        runner._log_message("--- Reading Container Delays from Source Files ---")

        # This will hold the video delay for Source 1 to calculate relative audio delays
        source1_video_delay_ms = 0

        for source_key, source_path in ctx.sources.items():
            info = get_stream_info_with_delays(str(source_path), runner, ctx.tool_paths)
            if info:
                delays_for_source = {}
                runner._log_message(f"[Container Delays] Reading delays from {source_key}:")

                # If this is Source 1, find the video track's delay first
                if source_key == 'Source 1':
                    for track in info.get('tracks', []):
                        if track.get('type') == 'video':
                            source1_video_delay_ms = track.get('container_delay_ms', 0)
                            break

                for track in info.get('tracks', []):
                    tid = track.get('id')
                    track_type = track.get('type', 'unknown')
                    delay_ms = track.get('container_delay_ms', 0)

                    # For Source 1 audio tracks, calculate the delay relative to the video.
                    # For all other tracks, use the absolute delay.
                    if source_key == 'Source 1' and track_type == 'audio':
                        delays_for_source[tid] = delay_ms - source1_video_delay_ms
                    else:
                        delays_for_source[tid] = delay_ms

                    # Only log non-zero delays for audio/video tracks
                    if delay_ms != 0 and track_type in ['audio', 'video']:
                        props = track.get('properties', {})
                        lang = props.get('language', 'und')
                        name = props.get('track_name', '')

                        desc = f"  Track {tid} ({track_type}"
                        if lang != 'und':
                            desc += f", {lang}"
                        if name:
                            desc += f", '{name}'"
                        desc += f"): {delay_ms:+.1f}ms"
                        runner._log_message(desc)

                # Store in context
                ctx.container_delays[source_key] = delays_for_source

                # Check if all delays are zero
                non_zero_delays = [d for d in delays_for_source.values() if d != 0]
                if not non_zero_delays:
                    runner._log_message(f"  All tracks have zero container delay")

        # --- Read aspect ratios from ffprobe for all sources ---
        runner._log_message("--- Reading Aspect Ratios from Source Files ---")
        source_aspect_ratios: Dict[str, Dict[int, str]] = {}

        for source_key, source_path in ctx.sources.items():
            # Use ffprobe to get display_aspect_ratio
            import json
            cmd = ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source_path)]
            ffprobe_out = runner.run(cmd, ctx.tool_paths)

            if ffprobe_out:
                try:
                    ffprobe_data = json.loads(ffprobe_out)
                    aspect_ratios_for_source = {}

                    for stream in ffprobe_data.get('streams', []):
                        if stream.get('codec_type') == 'video':
                            dar = stream.get('display_aspect_ratio')
                            stream_index = stream.get('index', 0)

                            if dar:
                                # Match stream index to mkvmerge track ID (usually the same)
                                aspect_ratios_for_source[stream_index] = dar
                                runner._log_message(f"[{source_key}] Video track {stream_index} aspect ratio: {dar}")

                    source_aspect_ratios[source_key] = aspect_ratios_for_source
                except json.JSONDecodeError:
                    runner._log_message(f"[WARNING] Could not parse ffprobe output for {source_key}")
                    source_aspect_ratios[source_key] = {}

        # --- Part 1: Extract tracks from MKV sources ---
        all_extracted_tracks = []
        for source_key, source_path in ctx.sources.items():
            track_ids_to_extract = [t['id'] for t in ctx.manual_layout if t.get('source') == source_key]
            if track_ids_to_extract:
                runner._log_message(f"Preparing to extract {len(track_ids_to_extract)} track(s) from {source_key}...")
                extracted_for_source = extract_tracks(
                    str(source_path), ctx.temp_dir, runner, ctx.tool_paths,
                    role=source_key,
                    specific_tracks=track_ids_to_extract
                )
                all_extracted_tracks.extend(extracted_for_source)

        extracted_map: Dict[str, Dict[str, Any]] = {
            f"{t['source']}_{t['id']}": t
            for t in all_extracted_tracks
        }

        # --- Part 2: Build the final PlanItem list ---
        items: List[PlanItem] = []
        for sel in ctx.manual_layout:
            source = sel.get('source', '')

            if source == 'External':
                original_path = Path(sel['original_path'])
                temp_path = ctx.temp_dir / original_path.name
                shutil.copy(original_path, temp_path)

                track_model = Track(
                    source='External',
                    id=0, # Dummy ID
                    type=TrackType.SUBTITLES,
                    props=StreamProps(
                        codec_id=sel.get('codec_id', ''),
                        lang=sel.get('lang', 'und'),
                        name=sel.get('name', '')
                    )
                )
                plan_item = PlanItem(
                    track=track_model,
                    extracted_path=temp_path,
                    container_delay_ms=0,  # External files have no container delay
                    aspect_ratio=None  # External subtitles have no aspect ratio
                )

            else:
                key = f"{source}_{sel['id']}"
                trk = extracted_map.get(key)
                if not trk:
                    runner._log_message(f"[WARNING] Could not find extracted file for {key}. Skipping.")
                    continue

                track_model = Track(
                    source=source,
                    id=int(trk['id']),
                    type=TrackType(trk.get('type', 'video')),
                    props=StreamProps(
                        codec_id=trk.get('codec_id', '') or '',
                        lang=trk.get('lang', 'und') or 'und',
                        name=trk.get('name', '') or ''
                    )
                )

                # Get the container delay for this track
                container_delay = ctx.container_delays.get(source, {}).get(int(trk['id']), 0)

                # Get the aspect ratio for video tracks
                aspect_ratio = None
                if track_model.type == TrackType.VIDEO:
                    aspect_ratio = source_aspect_ratios.get(source, {}).get(int(trk['id']))

                plan_item = PlanItem(
                    track=track_model,
                    extracted_path=Path(trk['path']),
                    container_delay_ms=container_delay,
                    aspect_ratio=aspect_ratio  # Store the original aspect ratio
                )

            plan_item.is_default = bool(sel.get('is_default', False))
            plan_item.is_forced_display = bool(sel.get('is_forced_display', False))
            plan_item.apply_track_name = bool(sel.get('apply_track_name', False))
            plan_item.perform_ocr = bool(sel.get('perform_ocr', False))
            plan_item.perform_ocr_cleanup = bool(sel.get('perform_ocr_cleanup', False))
            plan_item.convert_to_ass = bool(sel.get('convert_to_ass', False))
            plan_item.rescale = bool(sel.get('rescale', False))

            # Fix: Ensure size_multiplier defaults to 1.0 and handle None/empty values
            size_mult = sel.get('size_multiplier')
            if size_mult is None or size_mult == '' or size_mult == 0:
                plan_item.size_multiplier = 1.0
            else:
                plan_item.size_multiplier = float(size_mult)

            plan_item.style_patch = sel.get('style_patch')
            plan_item.user_modified_path = sel.get('user_modified_path')
            plan_item.sync_to = sel.get('sync_to')
            plan_item.correction_source = sel.get('correction_source')
            plan_item.custom_lang = sel.get('custom_lang', '')  # Preserve custom language
            plan_item.custom_name = sel.get('custom_name', '')  # Preserve custom name

            # NEW: Handle generated track fields
            plan_item.is_generated = bool(sel.get('is_generated', False))
            plan_item.generated_source_track_id = sel.get('generated_source_track_id')
            plan_item.generated_source_path = sel.get('generated_source_path')
            plan_item.generated_filter_mode = sel.get('generated_filter_mode', 'exclude')
            plan_item.generated_filter_styles = sel.get('generated_filter_styles', [])
            plan_item.generated_verify_only_lines_removed = bool(sel.get('generated_verify_only_lines_removed', True))

            items.append(plan_item)

        # --- Part 3: Process generated tracks (filter subtitle styles) ---
        runner._log_message("--- Processing Generated Tracks ---")
        generated_items = self._process_generated_tracks(items, runner, ctx.temp_dir)
        items.extend(generated_items)

        ctx.extracted_items = items
        return ctx

    def _process_generated_tracks(self, items: List[PlanItem], runner: CommandRunner, temp_dir: Path) -> List[PlanItem]:
        """
        Process generated tracks by creating filtered subtitle files.

        Args:
            items: Existing PlanItems (to find source tracks)
            runner: Command runner for logging
            temp_dir: Temporary directory for filtered files

        Returns:
            List of new PlanItems for generated tracks
        """
        from vsg_core.subtitles.style_filter import StyleFilterEngine

        generated_plan_items = []

        for item in items:
            if not item.is_generated:
                continue

            runner._log_message(f"[Generated Track] Creating filtered track from {item.track.source} Track {item.generated_source_track_id}...")

            # Find the source track's extracted path
            source_path = item.extracted_path
            if not source_path or not source_path.exists():
                runner._log_message(f"[ERROR] Source file not found for generated track: {source_path}")
                continue

            # Create filtered subtitle file
            try:
                # Create unique filename for filtered file
                original_stem = source_path.stem
                filtered_filename = f"{original_stem}_generated_{id(item)}.{source_path.suffix.lstrip('.')}"
                filtered_path = temp_dir / filtered_filename

                # Copy the source file to the filtered path first
                shutil.copy(source_path, filtered_path)

                # Apply the style filter
                filter_engine = StyleFilterEngine(str(filtered_path))
                result = filter_engine.filter_by_styles(
                    styles=item.generated_filter_styles,
                    mode=item.generated_filter_mode,
                    output_path=None  # Overwrites the copied file
                )

                # Log the results
                mode_text = "excluded" if item.generated_filter_mode == 'exclude' else "included"
                runner._log_message(
                    f"  Filtered {result['removed_count']} events "
                    f"({mode_text} styles: {', '.join(result['styles_found'])})"
                )

                # Check verification
                if not result['verification_passed']:
                    if item.generated_verify_only_lines_removed:
                        # User wants verification - fail on verification issues
                        runner._log_message(f"[ERROR] Verification failed for generated track:")
                        for issue in result['verification_issues']:
                            runner._log_message(f"  - {issue}")
                        continue
                    else:
                        # Just warn
                        runner._log_message(f"[WARNING] Verification issues detected:")
                        for issue in result['verification_issues']:
                            runner._log_message(f"  - {issue}")

                # Check if any styles were missing
                if result['styles_missing']:
                    runner._log_message(
                        f"  [WARNING] Some styles not found in source: {', '.join(result['styles_missing'])}"
                    )

                # Update the PlanItem's extracted_path to point to the filtered file
                item.extracted_path = filtered_path

                runner._log_message(f"  ✓ Generated track created: {filtered_path.name}")

            except Exception as e:
                runner._log_message(f"[ERROR] Failed to create generated track: {e}")
                import traceback
                runner._log_message(traceback.format_exc())
                continue

        return []  # We modified items in place, no new items to return
