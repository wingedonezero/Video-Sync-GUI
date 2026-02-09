# vsg_core/subtitles/track_processor.py
"""
Subtitle track processing pipeline.

Processes a single subtitle track through the unified SubtitleData flow:
1. Load into SubtitleData (or use provided from OCR)
2. Apply style filtering (if generated track)
3. Apply stepping
4. Apply sync mode
5. Apply style operations (font, patch, rescale, size)
6. Save JSON + ASS/SRT (single rounding point)

All operations modify SubtitleData in place and return OperationResult.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context
    from vsg_core.subtitles.data import SubtitleData

from vsg_core.models.media import StreamProps, Track
from vsg_core.subtitles.diagnostics import (
    check_timestamp_precision,
    parse_ass_time_str,
    read_raw_ass_timestamps,
)
from vsg_core.subtitles.sync_dispatcher import apply_sync_mode


def process_subtitle_track(
    item,
    ctx: Context,
    runner: CommandRunner,
    source1_file: Path | None,
    ocr_subtitle_data: SubtitleData | None,
    items_to_add: list,
    scene_cache: dict[str, Any] | None = None,
) -> None:
    """
    Process a subtitle track using the unified SubtitleData flow.

    1. Load into SubtitleData (or use provided SubtitleData from OCR)
    2. Apply stepping (if applicable)
    3. Apply sync mode
    4. Apply style operations
    5. Save (single rounding point)

    Args:
        item: ExtractedItem for the subtitle track
        ctx: Context with settings, delays, etc.
        runner: CommandRunner for logging
        source1_file: Target video file (Source 1)
        ocr_subtitle_data: Optional pre-loaded SubtitleData (from OCR).
                          If provided, skips file loading step.
        items_to_add: List to append generated items to
        scene_cache: Scene detection cache (unused currently)

    Updates:
        item: Updates extracted_path, track codec, flags in place
    """
    from vsg_core.subtitles.data import SubtitleData as SubtitleDataClass

    if scene_cache is None:
        scene_cache = {}

    subtitle_sync_mode = ctx.settings.subtitle_sync_mode

    # ================================================================
    # STEP 1: Load into SubtitleData (or use provided)
    # ================================================================
    if ocr_subtitle_data is not None:
        # SubtitleData provided (from OCR)
        subtitle_data = ocr_subtitle_data
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
            raw_timestamps_before = read_raw_ass_timestamps(
                item.extracted_path, max_events=3
            )
            if raw_timestamps_before:
                runner._log_message("[DIAG] Original file first 3 event timestamps:")
                for i, (start_str, end_str, style) in enumerate(raw_timestamps_before):
                    start_ms = parse_ass_time_str(start_str)
                    end_ms = parse_ass_time_str(end_str)
                    start_precision = check_timestamp_precision(start_str)
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
                    raw_start = parse_ass_time_str(start_str)
                    raw_end = parse_ass_time_str(end_str)
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
            runner._log_message(f"[SubtitleData] Style filter failed: {result.error}")

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
                runner._log_message(f"[SubtitleData] Stepping failed: {result.error}")

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
        sync_result = apply_sync_mode(
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
        result = subtitle_data.apply_font_replacement(item.font_replacements, runner)
        if result.success:
            runner._log_message(f"[SubtitleData] Font replacement: {result.summary}")

    # Style patches
    if item.style_patch:
        runner._log_message("[SubtitleData] Applying style patch...")
        result = subtitle_data.apply_style_patch(item.style_patch, runner)
        if result.success:
            runner._log_message(f"[SubtitleData] Style patch: {result.summary}")

    # Rescale
    if item.rescale and source1_file:
        runner._log_message("[SubtitleData] Applying rescale...")
        target_res = _get_video_resolution(source1_file, runner, ctx)
        if target_res:
            result = subtitle_data.apply_rescale(target_res, runner)
            if result.success:
                runner._log_message(f"[SubtitleData] Rescale: {result.summary}")

    # Size multiplier
    size_mult = float(item.size_multiplier) if hasattr(item, "size_multiplier") else 1.0
    if abs(size_mult - 1.0) > 1e-6:
        if 0.5 <= size_mult <= 3.0:
            runner._log_message(
                f"[SubtitleData] Applying size multiplier: {size_mult}x"
            )
            result = subtitle_data.apply_size_multiplier(size_mult, runner)
            if result.success:
                runner._log_message(f"[SubtitleData] Size multiplier: {result.summary}")
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
        ocr_debug_dir = _get_ocr_debug_dir(item, ctx)
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
            saved_timestamps = read_raw_ass_timestamps(output_path, max_events=3)
            if saved_timestamps:
                runner._log_message("[DIAG] Post-save file first 3 event timestamps:")
                for i, (start_str, end_str, style) in enumerate(saved_timestamps):
                    start_ms = parse_ass_time_str(start_str)
                    end_ms = parse_ass_time_str(end_str)
                    runner._log_message(
                        f"[DIAG]   Event {i}: start='{start_str}'({start_ms}ms) end='{end_str}'({end_ms}ms)"
                    )

                # Compare with pre-save values
                if subtitle_data.events:
                    for i, (start_str, end_str, _) in enumerate(
                        saved_timestamps[: min(3, len(subtitle_data.events))]
                    ):
                        saved_start_ms = parse_ass_time_str(start_str)
                        saved_end_ms = parse_ass_time_str(end_str)
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


def _get_video_resolution(video_path: Path, runner, ctx) -> tuple | None:
    """Get video resolution for rescaling."""
    try:
        from vsg_core.subtitles.frame_utils import get_video_properties

        props = get_video_properties(str(video_path), runner, ctx.tool_paths)
        if props:
            return (props.get("width", 1920), props.get("height", 1080))
    except Exception as e:
        runner._log_message(f"[Rescale] WARNING: Could not get video resolution: {e}")
    return None


def _get_ocr_debug_dir(item, ctx: Context) -> Path | None:
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
