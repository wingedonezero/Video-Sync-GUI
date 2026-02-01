# vsg_core/orchestrator/steps/subtitles_step.py
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
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context
    from vsg_core.subtitles.data import SubtitleData

from vsg_core.models.enums import TrackType
from vsg_core.models.media import StreamProps, Track


def _read_raw_ass_timestamps(
    file_path: Path, max_events: int = 5
) -> list[tuple[str, str, str]]:
    """
    Read raw timestamp strings from an ASS file without full parsing.

    Returns list of (start_str, end_str, style) tuples for first N events.
    Reads both Dialogue and Comment lines to match SubtitleData.events order.
    Used for diagnostics to compare original file timestamps with parsed values.
    """
    results = []
    try:
        # Try to detect encoding
        encodings = ["utf-8-sig", "utf-8", "utf-16", "cp1252", "latin1"]
        content = None
        for enc in encodings:
            try:
                with open(file_path, encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if not content:
            return results

        # Pattern: Dialogue/Comment: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        # Match both Dialogue and Comment lines to align with SubtitleData.events
        pattern = re.compile(
            r"^(?:Dialogue|Comment):\s*\d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),([^,]*),",
            re.MULTILINE,
        )

        for match in pattern.finditer(content):
            if len(results) >= max_events:
                break
            start_str = match.group(1)
            end_str = match.group(2)
            style = match.group(3)
            results.append((start_str, end_str, style))
    except Exception:
        pass
    return results


def _check_timestamp_precision(timestamp_str: str) -> int:
    """
    Check the precision of a timestamp string (number of fractional digits).

    Standard ASS uses centiseconds (2 digits: "0:00:00.00").
    Some tools may output milliseconds (3 digits: "0:00:00.000").

    Returns number of fractional digits.
    """
    try:
        parts = timestamp_str.split(".")
        if len(parts) == 2:
            return len(parts[1])
    except Exception:
        pass
    return 2  # Default assumption


def _parse_ass_time_str(time_str: str) -> float:
    """Parse ASS timestamp string to float ms (same logic as SubtitleData)."""
    try:
        parts = time_str.strip().split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_cs = parts[2].split(".")
            seconds = int(seconds_cs[0])
            centiseconds = int(seconds_cs[1]) if len(seconds_cs) > 1 else 0
            total_ms = (
                hours * 3600000 + minutes * 60000 + seconds * 1000 + centiseconds * 10
            )
            return float(total_ms)
    except (ValueError, IndexError):
        pass
    return 0.0


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
            runner._log_message(
                "[WARN] No Source 1 file found for subtitle processing reference."
            )

        items_to_add = []
        _any_no_scene_fallback = False

        # Cache for scene detection results per source
        _scene_detection_cache = {}

        # ================================================================
        # Video-Verified Pre-Processing (once per source)
        # ================================================================
        # If video-verified mode is enabled, run frame matching once per
        # unique source and update ctx.delays. This ensures all subtitle
        # tracks (text, bitmap, OCR'd, preserved) use the corrected delay.
        subtitle_sync_mode = ctx.settings.subtitle_sync_mode
        if subtitle_sync_mode == "video-verified" and source1_file:
            self._run_video_verified_per_source(ctx, runner, source1_file)

        for item in ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            # NOTE: user_modified_path is NOT used during job execution
            # Style editor temp files are only for preview during editing
            # Job execution uses fresh extraction + style_patch via SubtitleData

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
            # Check if we can skip SubtitleData processing for time-based mode
            # This matches old behavior where time-based + mkvmerge just passed
            # the file through unchanged
            # ================================================================
            subtitle_sync_mode = ctx.settings.subtitle_sync_mode
            use_raw_values = ctx.settings.time_based_use_raw_values
            bypass_subtitle_data = ctx.settings.time_based_bypass_subtitle_data

            # Determine if we need SubtitleData processing
            needs_subtitle_data = (
                ocr_subtitle_data is not None  # OCR requires SubtitleData
                or item.perform_ocr  # OCR pending
                or item.style_patch  # Style operations need SubtitleData
                or item.font_replacements  # Font operations need SubtitleData
                or item.rescale  # Rescale needs SubtitleData
                or (
                    hasattr(item, "size_multiplier")
                    and abs(float(item.size_multiplier or 1.0) - 1.0) > 1e-6
                )  # Size multiplier
                or item.convert_to_ass  # Format conversion needs SubtitleData
                or item.is_generated  # Generated tracks need style filtering
                or (
                    subtitle_sync_mode != "time-based"
                )  # Non-time-based modes need SubtitleData
                or use_raw_values  # Raw values mode applies delay in SubtitleData
                or (
                    item.track.source in ctx.stepping_edls
                    and ctx.settings.stepping_adjust_subtitles
                )  # Stepping needs SubtitleData
            )

            if (
                not needs_subtitle_data
                and bypass_subtitle_data
                and subtitle_sync_mode == "time-based"
            ):
                # BYPASS: Time-based mode with no other processing needed
                # Pass subtitle file through unchanged - mkvmerge --sync handles delay
                runner._log_message(
                    f"[Subtitles] Track {item.track.id}: BYPASS mode - passing through unchanged for mkvmerge --sync"
                )
                runner._log_message(
                    "[Subtitles]   (No OCR, style ops, stepping, or format conversion needed)"
                )
                continue  # Skip to next track - file is already in item.extracted_path

            # ================================================================
            # Unified SubtitleData Processing
            # ================================================================
            if ocr_subtitle_data is not None:
                # OCR already gave us SubtitleData - use it directly
                try:
                    self._process_track_unified(
                        item,
                        ctx,
                        runner,
                        source1_file,
                        _scene_detection_cache,
                        items_to_add,
                        subtitle_data=ocr_subtitle_data,
                    )
                except Exception as e:
                    runner._log_message(
                        f"[Subtitles] ERROR processing track {item.track.id}: {e}"
                    )
                    raise
            elif item.extracted_path:
                ext = item.extracted_path.suffix.lower()
                supported_formats = [".ass", ".ssa", ".srt", ".vtt"]

                if ext in supported_formats:
                    try:
                        self._process_track_unified(
                            item,
                            ctx,
                            runner,
                            source1_file,
                            _scene_detection_cache,
                            items_to_add,
                        )
                    except Exception as e:
                        runner._log_message(
                            f"[Subtitles] ERROR processing track {item.track.id}: {e}"
                        )
                        raise
                # Bitmap subtitles (VobSub, PGS) - can't process with unified flow
                # but CAN use video-verified mode for frame-corrected delays
                elif subtitle_sync_mode == "video-verified":
                    self._apply_video_verified_for_bitmap(
                        item, ctx, runner, source1_file
                    )
                else:
                    runner._log_message(
                        f"[Subtitles] Track {item.track.id}: Bitmap format {ext} - using mkvmerge --sync for delay"
                    )

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
        source1_file: Path | None,
        scene_cache: dict[str, Any],
        items_to_add: list,
        subtitle_data: SubtitleData | None = None,
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

        subtitle_sync_mode = ctx.settings.subtitle_sync_mode
        Path(ctx.settings.logs_folder or ctx.temp_dir)

        # ================================================================
        # STEP 1: Load into SubtitleData (or use provided)
        # ================================================================
        if subtitle_data is not None:
            # SubtitleData provided (from OCR)
            runner._log_message(
                f"[SubtitleData] Using OCR SubtitleData for track {item.track.id}"
            )
            runner._log_message(
                f"[SubtitleData] {len(subtitle_data.events)} events, OCR metadata preserved"
            )
        else:
            # Load from file
            runner._log_message(
                f"[SubtitleData] Loading track {item.track.id}: {item.extracted_path.name}"
            )

            # DIAGNOSTIC: Read raw timestamps from original file BEFORE parsing
            raw_timestamps_before = []
            if item.extracted_path.suffix.lower() in (".ass", ".ssa"):
                raw_timestamps_before = _read_raw_ass_timestamps(
                    item.extracted_path, max_events=3
                )
                if raw_timestamps_before:
                    runner._log_message(
                        "[DIAG] Original file first 3 event timestamps:"
                    )
                    for i, (start_str, end_str, style) in enumerate(
                        raw_timestamps_before
                    ):
                        start_ms = _parse_ass_time_str(start_str)
                        end_ms = _parse_ass_time_str(end_str)
                        start_precision = _check_timestamp_precision(start_str)
                        runner._log_message(
                            f"[DIAG]   Event {i}: start='{start_str}'({start_ms}ms) end='{end_str}'({end_ms}ms) style='{style}'"
                        )

                        # Warn about non-standard precision (3+ digits = milliseconds instead of centiseconds)
                        if start_precision != 2:
                            runner._log_message(
                                f"[DIAG] WARNING: Non-standard timestamp precision detected! "
                                f"Found {start_precision} fractional digits (expected 2 for centiseconds)"
                            )
                            runner._log_message(
                                "[DIAG] This could cause timing loss during load/save cycle!"
                            )

            try:
                subtitle_data = SubtitleDataClass.from_file(item.extracted_path)
                runner._log_message(
                    f"[SubtitleData] Loaded {len(subtitle_data.events)} events, {len(subtitle_data.styles)} styles"
                )

                # DIAGNOSTIC: Compare parsed timestamps with raw file timestamps
                if raw_timestamps_before and subtitle_data.events:
                    runner._log_message(
                        "[DIAG] Parsed SubtitleData first 3 event timestamps:"
                    )
                    for i, event in enumerate(subtitle_data.events[:3]):
                        runner._log_message(
                            f"[DIAG]   Event {i}: start={event.start_ms}ms end={event.end_ms}ms style='{event.style}'"
                        )

                    # Check for differences
                    for i, (start_str, end_str, _) in enumerate(
                        raw_timestamps_before[: min(3, len(subtitle_data.events))]
                    ):
                        raw_start = _parse_ass_time_str(start_str)
                        raw_end = _parse_ass_time_str(end_str)
                        parsed_start = subtitle_data.events[i].start_ms
                        parsed_end = subtitle_data.events[i].end_ms
                        if (
                            abs(raw_start - parsed_start) > 0.001
                            or abs(raw_end - parsed_end) > 0.001
                        ):
                            runner._log_message(
                                f"[DIAG] WARNING: Timestamp mismatch at event {i}!"
                            )
                            runner._log_message(
                                f"[DIAG]   Raw: start={raw_start}ms, end={raw_end}ms"
                            )
                            runner._log_message(
                                f"[DIAG]   Parsed: start={parsed_start}ms, end={parsed_end}ms"
                            )

                # === AUDIT: Record parsed subtitle info ===
                if ctx.audit and subtitle_data.events:
                    track_key = (
                        f"track_{item.track.id}_{item.track.source.replace(' ', '_')}"
                    )
                    ctx.audit.record_subtitle_parsed(
                        track_key=track_key,
                        event_count=len(subtitle_data.events),
                        first_event_start_ms=subtitle_data.events[0].start_ms,
                        last_event_end_ms=subtitle_data.events[-1].end_ms,
                        style_count=len(subtitle_data.styles),
                        source_path=str(item.extracted_path),
                    )
            except Exception as e:
                runner._log_message(f"[SubtitleData] ERROR: Failed to load: {e}")
                raise

        # ================================================================
        # STEP 1b: Apply Style Filtering (for generated tracks)
        # ================================================================
        filter_cfg = item.filter_config or {}
        filter_styles = filter_cfg.get("filter_styles", [])
        forced_include = filter_cfg.get("forced_include", [])
        forced_exclude = filter_cfg.get("forced_exclude", [])

        if item.is_generated and (filter_styles or forced_include or forced_exclude):
            runner._log_message(
                f"[SubtitleData] Applying style filter for generated track "
                f"(forced keep: {len(forced_include)}, forced remove: {len(forced_exclude)})..."
            )
            result = subtitle_data.filter_by_styles(
                styles=filter_styles,
                mode=filter_cfg.get("filter_mode", "exclude"),
                forced_include=forced_include,
                forced_exclude=forced_exclude,
                runner=runner,
            )
            if result.success:
                runner._log_message(f"[SubtitleData] Style filter: {result.summary}")
                # Check for missing styles (validation already happened, just warn)
                if result.details and result.details.get("styles_missing"):
                    runner._log_message(
                        f"[SubtitleData] WARNING: Filter styles not found: "
                        f"{', '.join(result.details['styles_missing'])}"
                    )
            else:
                runner._log_message(
                    f"[SubtitleData] Style filter failed: {result.error}"
                )

        # ================================================================
        # STEP 2: Apply Stepping (if applicable)
        # ================================================================
        if ctx.settings.stepping_adjust_subtitles:
            source_key = item.track.source
            if source_key in ctx.stepping_edls:
                runner._log_message("[SubtitleData] Applying stepping correction...")

                result = subtitle_data.apply_stepping(
                    edl_segments=ctx.stepping_edls[source_key],
                    boundary_mode=ctx.settings.stepping_boundary_mode,
                    runner=runner,
                )

                if result.success:
                    runner._log_message(f"[SubtitleData] Stepping: {result.summary}")
                    # Only set stepping_adjusted if events were actually modified.
                    # If all offsets were 0, events_affected=0 and we shouldn't
                    # skip sync or prevent mkvmerge from applying delays.
                    if result.events_affected > 0:
                        item.stepping_adjusted = True
                else:
                    runner._log_message(
                        f"[SubtitleData] Stepping failed: {result.error}"
                    )

        # ================================================================
        # STEP 3: Apply Sync Mode
        # ================================================================
        # For non-frame-locked modes with stepping already applied, skip sync
        should_apply_sync = True
        if item.stepping_adjusted and subtitle_sync_mode not in [
            "timebase-frame-locked-timestamps"
        ]:
            should_apply_sync = False
            runner._log_message(
                f"[SubtitleData] Skipping {subtitle_sync_mode} - stepping already applied"
            )

        if should_apply_sync:
            sync_result = self._apply_sync_unified(
                item,
                subtitle_data,
                ctx,
                runner,
                source1_file,
                subtitle_sync_mode,
                scene_cache,
            )

            if sync_result and sync_result.success:
                # Only set frame_adjusted if sync actually modified subtitle events.
                # Time-based mode (default) returns events_affected=0 because it
                # delegates to mkvmerge --sync. Setting frame_adjusted=True would
                # cause options_builder to return delay=0, preventing any sync.
                if sync_result.events_affected > 0:
                    item.frame_adjusted = True

                    # Check for negative timestamps that will be clamped to 0 when written
                    # (ASS/SRT formats cannot represent negative times)
                    negative_events = [
                        e
                        for e in subtitle_data.events
                        if e.start_ms < 0 and not e.is_comment
                    ]
                    if negative_events:
                        delay_applied = (
                            sync_result.details.get("final_offset_ms", 0)
                            if sync_result.details
                            else 0
                        )
                        min_time = min(e.start_ms for e in negative_events)
                        max_time = max(e.start_ms for e in negative_events)
                        runner._log_message(
                            f"[Sync] Warning: {len(negative_events)} event(s) have negative timestamps "
                            f"({min_time:.0f}ms to {max_time:.0f}ms), will be clamped to 0ms"
                        )
                        # Store for auditor reporting
                        item.clamping_info = {
                            "events_clamped": len(negative_events),
                            "delay_ms": delay_applied,
                            "min_time_ms": min_time,
                            "max_time_ms": max_time,
                        }

                if hasattr(sync_result, "details"):
                    item.framelocked_stats = sync_result.details

        # ================================================================
        # STEP 4: Apply SRT to ASS Conversion (if needed)
        # ================================================================
        output_format = ".ass"
        if item.convert_to_ass and item.extracted_path.suffix.lower() == ".srt":
            # Conversion happens at save - SubtitleData can save to any format
            runner._log_message("[SubtitleData] Will convert SRT to ASS at save")
            output_format = ".ass"
        else:
            output_format = item.extracted_path.suffix.lower()

        # ================================================================
        # STEP 5: Apply Style Operations
        # ================================================================

        # Font replacements
        if item.font_replacements:
            runner._log_message("[SubtitleData] Applying font replacements...")
            result = subtitle_data.apply_font_replacement(
                item.font_replacements, runner
            )
            if result.success:
                runner._log_message(
                    f"[SubtitleData] Font replacement: {result.summary}"
                )

        # Style patches
        if item.style_patch:
            runner._log_message("[SubtitleData] Applying style patch...")
            result = subtitle_data.apply_style_patch(item.style_patch, runner)
            if result.success:
                runner._log_message(f"[SubtitleData] Style patch: {result.summary}")

        # Rescale
        if item.rescale and source1_file:
            runner._log_message("[SubtitleData] Applying rescale...")
            target_res = self._get_video_resolution(source1_file, runner, ctx)
            if target_res:
                result = subtitle_data.apply_rescale(target_res, runner)
                if result.success:
                    runner._log_message(f"[SubtitleData] Rescale: {result.summary}")

        # Size multiplier
        size_mult = (
            float(item.size_multiplier) if hasattr(item, "size_multiplier") else 1.0
        )
        if abs(size_mult - 1.0) > 1e-6:
            if 0.5 <= size_mult <= 3.0:
                runner._log_message(
                    f"[SubtitleData] Applying size multiplier: {size_mult}x"
                )
                result = subtitle_data.apply_size_multiplier(size_mult, runner)
                if result.success:
                    runner._log_message(
                        f"[SubtitleData] Size multiplier: {result.summary}"
                    )
            else:
                runner._log_message(
                    f"[SubtitleData] WARNING: Ignoring unreasonable size multiplier {size_mult:.2f}x"
                )

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
        if item.perform_ocr and ctx.settings.ocr_debug_output:
            ocr_debug_dir = self._get_ocr_debug_dir(item, ctx)
            if ocr_debug_dir:
                ocr_json_path = ocr_debug_dir / "subtitle_data.json"
                try:
                    subtitle_data.save_json(ocr_json_path)
                    runner._log_message(
                        f"[SubtitleData] OCR debug JSON saved: {ocr_json_path}"
                    )
                except Exception as e:
                    runner._log_message(
                        f"[SubtitleData] WARNING: Could not save OCR debug JSON: {e}"
                    )

        # ================================================================
        # STEP 7: Save ASS/SRT (SINGLE ROUNDING POINT)
        # ================================================================
        output_path = item.extracted_path.with_suffix(output_format)

        runner._log_message(f"[SubtitleData] Saving to {output_path.name}...")
        try:
            rounding_mode = ctx.settings.subtitle_rounding

            # DIAGNOSTIC: Log timestamps BEFORE save (what SubtitleData has in memory)
            if subtitle_data.events:
                runner._log_message(
                    f"[DIAG] Pre-save SubtitleData first 3 events (rounding_mode={rounding_mode}):"
                )
                for i, event in enumerate(subtitle_data.events[:3]):
                    runner._log_message(
                        f"[DIAG]   Event {i}: start={event.start_ms}ms end={event.end_ms}ms"
                    )

            subtitle_data.save(output_path, rounding=rounding_mode)
            item.extracted_path = output_path
            runner._log_message(
                f"[SubtitleData] Saved successfully ({len(subtitle_data.events)} events)"
            )

            # DIAGNOSTIC: Read back saved file timestamps to verify
            if output_path.suffix.lower() in (".ass", ".ssa"):
                saved_timestamps = _read_raw_ass_timestamps(output_path, max_events=3)
                if saved_timestamps:
                    runner._log_message(
                        "[DIAG] Post-save file first 3 event timestamps:"
                    )
                    for i, (start_str, end_str, style) in enumerate(saved_timestamps):
                        start_ms = _parse_ass_time_str(start_str)
                        end_ms = _parse_ass_time_str(end_str)
                        runner._log_message(
                            f"[DIAG]   Event {i}: start='{start_str}'({start_ms}ms) end='{end_str}'({end_ms}ms)"
                        )

                    # Compare with pre-save values
                    if subtitle_data.events:
                        for i, (start_str, end_str, _) in enumerate(
                            saved_timestamps[: min(3, len(subtitle_data.events))]
                        ):
                            saved_start_ms = _parse_ass_time_str(start_str)
                            saved_end_ms = _parse_ass_time_str(end_str)
                            pre_start_ms = subtitle_data.events[i].start_ms
                            pre_end_ms = subtitle_data.events[i].end_ms

                            # Calculate expected saved value based on rounding mode
                            if rounding_mode == "ceil":
                                expected_start_cs = int(math.ceil(pre_start_ms / 10))
                                expected_end_cs = int(math.ceil(pre_end_ms / 10))
                            elif rounding_mode == "round":
                                expected_start_cs = int(round(pre_start_ms / 10))
                                expected_end_cs = int(round(pre_end_ms / 10))
                            else:  # floor (default)
                                expected_start_cs = int(math.floor(pre_start_ms / 10))
                                expected_end_cs = int(math.floor(pre_end_ms / 10))

                            expected_start_ms = expected_start_cs * 10
                            expected_end_ms = expected_end_cs * 10

                            if (
                                abs(saved_start_ms - expected_start_ms) > 0.001
                                or abs(saved_end_ms - expected_end_ms) > 0.001
                            ):
                                runner._log_message(
                                    f"[DIAG] WARNING: Save rounding mismatch at event {i}!"
                                )
                                runner._log_message(
                                    f"[DIAG]   Pre-save: start={pre_start_ms}ms, end={pre_end_ms}ms"
                                )
                                runner._log_message(
                                    f"[DIAG]   Expected: start={expected_start_ms}ms, end={expected_end_ms}ms"
                                )
                                runner._log_message(
                                    f"[DIAG]   Actual saved: start={saved_start_ms}ms, end={saved_end_ms}ms"
                                )
        except Exception as e:
            runner._log_message(f"[SubtitleData] ERROR: Failed to save: {e}")
            raise

        # Update track codec if format changed
        if output_path.suffix.lower() == ".ass":
            item.track = Track(
                source=item.track.source,
                id=item.track.id,
                type=item.track.type,
                props=StreamProps(
                    codec_id="S_TEXT/ASS",
                    lang=item.track.props.lang,
                    name=item.track.props.name,
                ),
            )

        # Log summary
        runner._log_message(
            f"[SubtitleData] Track {item.track.id} complete: {len(subtitle_data.operations)} operations applied"
        )

    def _apply_sync_unified(
        self,
        item,
        subtitle_data,
        ctx: Context,
        runner: CommandRunner,
        source1_file: Path | None,
        sync_mode: str,
        scene_cache: dict[str, Any],
    ):
        """Apply sync mode using unified SubtitleData flow."""
        from vsg_core.subtitles.sync_modes import get_sync_plugin

        # Get source and delays
        source_key = (
            item.sync_to if item.track.source == "External" else item.track.source
        )
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
        runner._log_message(
            f"[Sync] Delay: {total_delay_ms:+.3f}ms (global: {global_shift_ms:+.3f}ms)"
        )

        # Check if video-verified was already computed for this source
        # If so, use the pre-computed delay and apply it directly (skip re-running frame matching)
        if sync_mode == "video-verified" and source_key in ctx.video_verified_sources:
            cached = ctx.video_verified_sources[source_key]
            runner._log_message(
                f"[Sync] Using pre-computed video-verified delay for {source_key}"
            )
            runner._log_message(
                f"[Sync]   Delay: {cached['corrected_delay_ms']:+.1f}ms"
            )

            # Apply the delay directly to subtitle events (like time-based mode)
            from vsg_core.subtitles.data import OperationResult, SyncEventData

            # Check if frame remap is enabled and we have the required data
            details: dict = cached.get("details", {})
            raw_frame_offset = details.get("frame_offset")
            raw_fps = details.get("fps")
            frame_offset: int | None = None
            fps: float | None = None
            if isinstance(raw_frame_offset, int | float):
                frame_offset = int(raw_frame_offset)
            if isinstance(raw_fps, int | float):
                fps = float(raw_fps)
            use_frame_remap = (
                ctx.settings.video_verified_frame_remap
                and frame_offset is not None
                and fps is not None
            )

            if use_frame_remap:
                from vsg_core.subtitles.frame_utils import apply_sync_with_frame_remap

                # Type narrowing: we know these are not None due to use_frame_remap check
                assert frame_offset is not None
                assert fps is not None
                runner._log_message(
                    f"[Sync] Using frame remap: offset={frame_offset:+d} frames, fps={fps:.3f}"
                )

                events_synced = 0
                for event in subtitle_data.events:
                    if event.is_comment:
                        continue
                    original_start = event.start_ms
                    original_end = event.end_ms

                    # Use frame remap to preserve centisecond position within frames
                    start_result, end_result = apply_sync_with_frame_remap(
                        original_start, original_end, frame_offset, fps
                    )
                    event.start_ms = start_result.target_ms
                    event.end_ms = end_result.target_ms
                    event.sync = SyncEventData(
                        original_start_ms=original_start,
                        original_end_ms=original_end,
                        start_adjustment_ms=start_result.target_ms - original_start,
                        end_adjustment_ms=end_result.target_ms - original_end,
                        snapped_to_frame=True,
                        target_frame_start=start_result.target_frame,
                        target_frame_end=end_result.target_frame,
                    )
                    events_synced += 1

                runner._log_message(
                    f"[Sync] Frame remap applied to {events_synced} events "
                    f"(offset={frame_offset:+d} frames)"
                )
            else:
                # Standard delay application
                events_synced = 0
                for event in subtitle_data.events:
                    if event.is_comment:
                        continue
                    original_start = event.start_ms
                    original_end = event.end_ms
                    event.start_ms += cached["corrected_delay_ms"]
                    event.end_ms += cached["corrected_delay_ms"]
                    event.sync = SyncEventData(
                        original_start_ms=original_start,
                        original_end_ms=original_end,
                        start_adjustment_ms=cached["corrected_delay_ms"],
                        end_adjustment_ms=cached["corrected_delay_ms"],
                        snapped_to_frame=False,
                    )
                    events_synced += 1
                runner._log_message(
                    f"[Sync] Applied {cached['corrected_delay_ms']:+.1f}ms to {events_synced} events"
                )
            item.frame_adjusted = True
            return OperationResult(
                success=True,
                operation="sync",
                events_affected=events_synced,
                summary=f"Video-verified (pre-computed): {cached['corrected_delay_ms']:+.1f}ms applied to {events_synced} events"
                + (" (frame remap)" if use_frame_remap else ""),
            )

        # For video-verified mode: Source 1 is the reference - no frame matching needed
        # (Source 1 would compare against itself which produces incorrect results)
        # Just apply the delay directly (which is just global_shift for Source 1)
        if sync_mode == "video-verified" and source_key == "Source 1":
            from vsg_core.subtitles.data import OperationResult, SyncEventData

            runner._log_message(
                "[Sync] Source 1 is reference - applying delay directly without frame matching"
            )

            events_synced = 0
            for event in subtitle_data.events:
                if event.is_comment:
                    continue
                original_start = event.start_ms
                original_end = event.end_ms
                event.start_ms += total_delay_ms
                event.end_ms += total_delay_ms
                event.sync = SyncEventData(
                    original_start_ms=original_start,
                    original_end_ms=original_end,
                    start_adjustment_ms=total_delay_ms,
                    end_adjustment_ms=total_delay_ms,
                    snapped_to_frame=False,
                )
                events_synced += 1

            runner._log_message(
                f"[Sync] Applied {total_delay_ms:+.1f}ms to {events_synced} events (reference)"
            )
            if events_synced > 0 and abs(total_delay_ms) > 0.001:
                item.frame_adjusted = True
            return OperationResult(
                success=True,
                operation="sync",
                events_affected=events_synced,
                summary=f"Video-verified (Source 1 reference): {total_delay_ms:+.1f}ms applied to {events_synced} events",
            )

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
                config=ctx.settings.to_dict(),
                temp_dir=ctx.temp_dir,
                sync_exclusion_styles=getattr(item, "sync_exclusion_styles", None),
                sync_exclusion_mode=getattr(item, "sync_exclusion_mode", "exclude"),
            )

            if result.success:
                runner._log_message(f"[Sync] {result.summary}")
            else:
                runner._log_message(f"[Sync] WARNING: {result.error or 'Sync failed'}")

            # === AUDIT: Record sync operation details ===
            if ctx.audit:
                track_key = (
                    f"track_{item.track.id}_{item.track.source.replace(' ', '_')}"
                )
                rounded_delay = (
                    ctx.delays.source_delays_ms.get(source_key, 0) if ctx.delays else 0
                )
                ctx.audit.record_subtitle_sync(
                    track_key=track_key,
                    sync_mode=sync_mode,
                    delay_from_context_raw_ms=total_delay_ms,
                    delay_from_context_rounded_ms=rounded_delay,
                    global_shift_raw_ms=global_shift_ms,
                    source_key=source_key,
                    plugin_name=plugin.name,
                    events_modified=result.events_affected
                    if hasattr(result, "events_affected")
                    else 0,
                    stepping_adjusted_before=item.stepping_adjusted,
                    stepping_adjusted_after=item.stepping_adjusted,
                    frame_adjusted_before=item.frame_adjusted,
                    frame_adjusted_after=item.frame_adjusted,  # Updated in caller
                )

            return result

        else:
            # All sync modes should have plugins - unknown mode
            from vsg_core.subtitles.data import OperationResult

            runner._log_message(f"[Sync] ERROR: Unknown sync mode: {sync_mode}")
            return OperationResult(
                success=False, operation="sync", error=f"Unknown sync mode: {sync_mode}"
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

        ocr_work_dir = ctx.temp_dir / "ocr"
        logs_dir = Path(ctx.settings.logs_folder or ctx.temp_dir)

        if ctx.settings.ocr_run_in_subprocess:
            subtitle_data = self._run_ocr_subprocess(
                item=item,
                ctx=ctx,
                runner=runner,
                ocr_work_dir=ocr_work_dir,
                logs_dir=logs_dir,
            )
        else:
            subtitle_data = run_ocr_unified(
                str(item.extracted_path.with_suffix(".idx")),
                item.track.props.lang,
                runner,
                ctx.tool_paths,
                ctx.settings,
                work_dir=ocr_work_dir,
                logs_dir=logs_dir,
                track_id=item.track.id,
            )

        if subtitle_data is None:
            runner._log_message(f"[OCR] ERROR: OCR failed for track {item.track.id}")
            runner._log_message("[OCR] Keeping original image-based subtitle")
            item.perform_ocr = False
            return None

        # Check if we got valid events
        if not subtitle_data.events:
            runner._log_message(
                f"[OCR] WARNING: OCR produced no events for track {item.track.id}"
            )
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
                name=f"{original_props.name} (Original)"
                if original_props.name
                else "Original",
            ),
        )
        items_to_add.append(preserved_item)

        # Update item to reflect OCR output
        # Set expected output path for later save
        item.extracted_path = item.extracted_path.with_suffix(".ass")
        item.track = Track(
            source=item.track.source,
            id=item.track.id,
            type=item.track.type,
            props=StreamProps(
                codec_id="S_TEXT/ASS",
                lang=original_props.lang,
                name=original_props.name,
            ),
        )

        return subtitle_data

    def _run_ocr_subprocess(
        self, item, ctx, runner, ocr_work_dir: Path, logs_dir: Path
    ):
        from vsg_core.subtitles.data import SubtitleData

        config_path = ctx.temp_dir / f"ocr_config_track_{item.track.id}.json"
        output_json = ctx.temp_dir / f"subtitle_data_track_{item.track.id}.json"

        try:
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(
                    ctx.settings.to_dict(), config_file, indent=2, ensure_ascii=False
                )
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to write OCR config: {e}")
            return None

        cmd = [
            sys.executable,
            "-m",
            "vsg_core.subtitles.ocr.unified_subprocess",
            "--subtitle-path",
            str(item.extracted_path.with_suffix(".idx")),
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

        runner._log_message(
            f"[OCR] Running OCR in subprocess for track {item.track.id}..."
        )

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to start OCR subprocess: {e}")
            return None

        json_payload = None
        json_prefix = "__VSG_UNIFIED_OCR_JSON__ "

        if process.stdout:
            for line in process.stdout:
                line = line.rstrip("\n")
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
                line = line.rstrip("\n")
                if line:
                    runner._log_message(f"[OCR] {line}")

        if return_code != 0:
            error_detail = None
            if json_payload and not json_payload.get("success"):
                error_detail = json_payload.get("error")
            runner._log_message(
                f"[OCR] ERROR: OCR subprocess failed (code {return_code})"
            )
            if error_detail:
                runner._log_message(f"[OCR] ERROR: {error_detail}")
            return None

        if not json_payload or not json_payload.get("success"):
            runner._log_message("[OCR] ERROR: OCR subprocess returned no result")
            return None

        json_path = json_payload.get("json_path")
        if not json_path:
            runner._log_message("[OCR] ERROR: OCR subprocess returned no JSON path")
            return None

        try:
            return SubtitleData.from_json(json_path)
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to load SubtitleData JSON: {e}")
            return None

    def _get_video_resolution(self, video_path: Path, runner, ctx) -> tuple | None:
        """Get video resolution for rescaling."""
        try:
            from vsg_core.subtitles.frame_utils import get_video_properties

            props = get_video_properties(str(video_path), runner, ctx.tool_paths)
            if props:
                return (props.get("width", 1920), props.get("height", 1080))
        except Exception as e:
            runner._log_message(
                f"[Rescale] WARNING: Could not get video resolution: {e}"
            )
        return None

    def _get_ocr_debug_dir(self, item, ctx) -> Path | None:
        """
        Get OCR debug directory for a track if it exists.

        Looks for the debug folder created by OCR pipeline:
        {logs_dir}/{base_name}_ocr_debug_{timestamp}/
        """
        logs_dir = Path(ctx.settings.logs_folder or ctx.temp_dir)

        # Find existing OCR debug directory for this track
        # Format: track_{id}_ocr_debug_* or similar
        try:
            base_name = (
                item.extracted_path.stem
                if item.extracted_path
                else f"track_{item.track.id}"
            )

            # Look for directories matching OCR debug pattern
            for path in logs_dir.iterdir():
                if path.is_dir() and "_ocr_debug_" in path.name:
                    # Check if this is the right track's debug dir
                    if base_name in path.name or f"track_{item.track.id}" in str(path):
                        return path

            # Also check temp_dir/ocr for debug output
            ocr_dir = ctx.temp_dir / "ocr"
            if ocr_dir.exists():
                for path in ocr_dir.iterdir():
                    if path.is_dir() and "debug" in path.name.lower():
                        return path

        except Exception:
            pass

        return None

    def _run_video_verified_per_source(
        self, ctx: Context, runner: CommandRunner, source1_file: Path
    ) -> None:
        """
        Run video-verified frame matching once per unique source.

        This pre-computes the frame-corrected delays for all sources that have
        subtitle tracks, updating ctx.delays so that ALL subtitle tracks from
        each source (text, bitmap, OCR'd, preserved) use the corrected delay.

        Only runs in video-verified mode.
        """
        from pathlib import Path

        from vsg_core.subtitles.sync_mode_plugins.video_verified import (
            calculate_video_verified_offset,
        )

        runner._log_message(
            "[VideoVerified] ═══════════════════════════════════════════════════════"
        )
        runner._log_message("[VideoVerified] Video-to-Video Frame Alignment")
        runner._log_message(
            "[VideoVerified] ═══════════════════════════════════════════════════════"
        )
        runner._log_message(
            f"[VideoVerified] Reference: Source 1 ({Path(source1_file).name})"
        )

        # Find unique sources that have subtitle tracks
        sources_with_subs = set()
        for item in ctx.extracted_items:
            if item.track.type == TrackType.SUBTITLES:
                source_key = (
                    item.sync_to
                    if item.track.source == "External"
                    else item.track.source
                )
                # Skip Source 1 - it's the reference, delay is always 0 + global_shift
                if source_key != "Source 1":
                    sources_with_subs.add(source_key)

        if not sources_with_subs:
            runner._log_message(
                "[VideoVerified] No subtitle tracks from other sources, skipping"
            )
            return

        runner._log_message(
            f"[VideoVerified] Aligning: {', '.join(sorted(sources_with_subs))} → Source 1"
        )

        # Process each source
        for source_key in sorted(sources_with_subs):
            source_video = ctx.sources.get(source_key)
            if not source_video:
                runner._log_message(
                    f"[VideoVerified] WARNING: No video file for {source_key}, skipping"
                )
                continue

            runner._log_message(f"\n[VideoVerified] ─── {source_key} vs Source 1 ───")

            # Get delays for this source
            total_delay_ms = 0.0
            global_shift_ms = 0.0
            if ctx.delays:
                if source_key in ctx.delays.raw_source_delays_ms:
                    total_delay_ms = ctx.delays.raw_source_delays_ms[source_key]
                global_shift_ms = ctx.delays.raw_global_shift_ms

            original_delay = total_delay_ms

            try:
                # Calculate frame-corrected delay
                corrected_delay_ms, details = calculate_video_verified_offset(
                    source_video=str(source_video),
                    target_video=str(source1_file),
                    total_delay_ms=total_delay_ms,
                    global_shift_ms=global_shift_ms,
                    settings=ctx.settings,
                    runner=runner,
                    temp_dir=ctx.temp_dir,
                )

                if corrected_delay_ms is not None and ctx.delays:
                    # Update both raw and rounded delays
                    if source_key in ctx.delays.source_delays_ms:
                        ctx.delays.source_delays_ms[source_key] = round(
                            corrected_delay_ms
                        )
                    if source_key in ctx.delays.raw_source_delays_ms:
                        ctx.delays.raw_source_delays_ms[source_key] = corrected_delay_ms

                    # Store that we've processed this source
                    ctx.video_verified_sources[source_key] = {
                        "original_delay_ms": original_delay,
                        "corrected_delay_ms": corrected_delay_ms,
                        "details": details,
                    }

                    # Report the result with precise values
                    if abs(corrected_delay_ms - original_delay) > 1:
                        runner._log_message(
                            f"[VideoVerified] ✓ {source_key} → Source 1: {original_delay:+.3f}ms → {corrected_delay_ms:+.3f}ms applied"
                        )
                    else:
                        runner._log_message(
                            f"[VideoVerified] ✓ {source_key} → Source 1: {corrected_delay_ms:+.3f}ms (no frame correction needed)"
                        )
                else:
                    runner._log_message(
                        f"[VideoVerified] ✗ {source_key}: frame matching failed, using audio correlation"
                    )

            except Exception as e:
                runner._log_message(f"[VideoVerified] ✗ {source_key}: ERROR - {e}")

        runner._log_message(
            "\n[VideoVerified] ═══════════════════════════════════════════════════════"
        )
        runner._log_message("[VideoVerified] Frame alignment complete")
        runner._log_message(
            "[VideoVerified] ═══════════════════════════════════════════════════════\n"
        )

    def _apply_video_verified_for_bitmap(
        self, item, ctx: Context, runner: CommandRunner, source1_file: Path | None
    ) -> None:
        """
        Apply video-verified frame matching for bitmap subtitles (VobSub, PGS).

        NOTE: This method is now mostly a fallback. The main video-verified
        processing happens in _run_video_verified_per_source() which runs
        once per source at the start of the subtitles step.

        Since bitmap subtitles can't be loaded into SubtitleData, we use the
        video-verified logic to calculate the correct delay, then store it
        so mkvmerge can apply it via --sync.

        This provides frame-accurate sync for image-based subtitle formats
        without requiring OCR.
        """
        ext = item.extracted_path.suffix.lower() if item.extracted_path else "unknown"
        source_key = (
            item.sync_to if item.track.source == "External" else item.track.source
        )

        # Source 1 is the reference - no frame matching needed
        # (Would compare against itself which is meaningless)
        if source_key == "Source 1":
            runner._log_message(
                f"[VideoVerified] Bitmap track {item.track.id} ({ext}): Source 1 is reference, skipping frame matching"
            )
            return

        # Check if this source was already processed in the per-source pre-processing step
        if source_key in ctx.video_verified_sources:
            cached = ctx.video_verified_sources[source_key]
            runner._log_message(
                f"[VideoVerified] Bitmap track {item.track.id} ({ext}): using pre-computed delay for {source_key}"
            )
            runner._log_message(
                f"[VideoVerified]   Delay: {cached['corrected_delay_ms']:+.1f}ms (was {cached['original_delay_ms']:+.1f}ms)"
            )
            item.video_verified_bitmap = True
            item.video_verified_details = cached["details"]
            return

        # Fallback: run frame matching for this track if not pre-processed
        # This shouldn't normally happen, but provides a safety net
        from vsg_core.subtitles.sync_mode_plugins.video_verified import (
            calculate_video_verified_offset,
        )

        runner._log_message(
            f"[VideoVerified] Processing bitmap subtitle track {item.track.id} ({ext}) (fallback mode)"
        )

        source_video = ctx.sources.get(source_key)
        target_video = source1_file

        if not source_video or not target_video:
            runner._log_message(
                f"[VideoVerified] Missing videos for track {item.track.id}, using correlation delay"
            )
            return

        # Get delays
        total_delay_ms = 0.0
        global_shift_ms = 0.0
        if ctx.delays:
            if source_key in ctx.delays.raw_source_delays_ms:
                total_delay_ms = ctx.delays.raw_source_delays_ms[source_key]
            global_shift_ms = ctx.delays.raw_global_shift_ms

        runner._log_message(
            f"[VideoVerified] Bitmap sub: Correlation delay = {total_delay_ms:+.3f}ms"
        )

        try:
            # Calculate frame-corrected delay using video matching
            corrected_delay_ms, details = calculate_video_verified_offset(
                source_video=str(source_video),
                target_video=str(target_video),
                total_delay_ms=total_delay_ms,
                global_shift_ms=global_shift_ms,
                settings=ctx.settings,
                runner=runner,
                temp_dir=ctx.temp_dir,
            )

            if corrected_delay_ms is not None:
                # Store the corrected delay for mkvmerge
                # Update the delay in the context so options_builder uses it
                if ctx.delays and source_key in ctx.delays.source_delays_ms:
                    old_delay = ctx.delays.source_delays_ms[source_key]
                    ctx.delays.source_delays_ms[source_key] = round(corrected_delay_ms)

                    # Also update raw delays for consistency
                    if source_key in ctx.delays.raw_source_delays_ms:
                        ctx.delays.raw_source_delays_ms[source_key] = corrected_delay_ms

                    runner._log_message(
                        f"[VideoVerified] Bitmap sub delay updated: {old_delay}ms → {round(corrected_delay_ms)}ms"
                    )

                    # Mark that we applied video-verified correction
                    item.video_verified_bitmap = True
                    item.video_verified_details = details

                    if abs(corrected_delay_ms - total_delay_ms) > 1:
                        runner._log_message(
                            f"[VideoVerified] ⚠ Frame correction changed delay by {corrected_delay_ms - total_delay_ms:+.1f}ms"
                        )
            else:
                runner._log_message(
                    "[VideoVerified] Frame matching returned None, using correlation delay"
                )
                runner._log_message(
                    f"[VideoVerified] Reason: {details.get('reason', 'unknown')}"
                )

        except Exception as e:
            runner._log_message(f"[VideoVerified] ERROR during frame matching: {e}")
            runner._log_message(
                f"[VideoVerified] Falling back to correlation delay for track {item.track.id}"
            )
