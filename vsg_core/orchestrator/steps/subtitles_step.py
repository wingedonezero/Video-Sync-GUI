# vsg_core/orchestrator/steps/subtitles_step.py
"""
Unified subtitle processing step using SubtitleData.

Flow:
1. Video-verified preprocessing (if enabled, once per source)
2. For each subtitle track:
   - OCR (if needed)
   - Process through SubtitleData pipeline (or bypass)
   - Apply operations: stepping, sync, styles
   - Save once at end (single rounding point)

All timing is float ms internally - rounding only at final save.

This step is a pure coordinator - all business logic is in subtitle modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


class SubtitlesStep:
    """
    Unified subtitle processing step - pure coordinator.

    Delegates to specialized subtitle modules for all business logic.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        source1_file_str = ctx.sources.get("Source 1")
        source1_file = Path(source1_file_str) if source1_file_str else None
        if not source1_file:
            runner._log_message(
                "[WARN] No Source 1 file found for subtitle processing reference."
            )

        items_to_add = []

        # ================================================================
        # Video-Verified Pre-Processing (once per source)
        # ================================================================
        # If video-verified mode is enabled, run frame matching once per
        # unique source and update ctx.subtitle_delays_ms. This ensures all subtitle
        # tracks (text, bitmap, OCR'd, preserved) use the corrected delay.
        subtitle_sync_mode = ctx.settings.subtitle_sync_mode
        if subtitle_sync_mode == "video-verified" and source1_file:
            from vsg_core.subtitles.sync_mode_plugins.video_verified.preprocessing import (
                run_per_source_preprocessing,
            )

            run_per_source_preprocessing(ctx, runner, source1_file)

        # ================================================================
        # Process Each Subtitle Track
        # ================================================================
        for item in ctx.extracted_items:
            if item.track.type != "subtitles":
                continue

            # NOTE: user_modified_path is NOT used during job execution
            # Style editor temp files are only for preview during editing
            # Job execution uses fresh extraction + style_patch via SubtitleData

            # ================================================================
            # OCR Processing (if needed)
            # ================================================================
            ocr_subtitle_data = None
            if item.perform_ocr and item.extracted_path:
                from vsg_core.subtitles.ocr.wrapper import (
                    process_ocr_with_preservation,
                )

                ocr_subtitle_data = process_ocr_with_preservation(
                    item, ctx, runner, items_to_add
                )
                if ocr_subtitle_data is None:
                    continue  # OCR failed, skip this track

            # ================================================================
            # Check if we can skip SubtitleData processing for time-based mode
            # This matches old behavior where time-based + mkvmerge just passed
            # the file through unchanged
            # ================================================================
            if self._should_bypass_processing(item, ctx, ocr_subtitle_data):
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
            if item.extracted_path:
                ext = item.extracted_path.suffix.lower()
                supported_formats = [".ass", ".ssa", ".srt", ".vtt"]

                if ext in supported_formats or ocr_subtitle_data is not None:
                    try:
                        from vsg_core.subtitles.track_processor import (
                            process_subtitle_track,
                        )

                        process_subtitle_track(
                            item=item,
                            ctx=ctx,
                            runner=runner,
                            source1_file=source1_file,
                            ocr_subtitle_data=ocr_subtitle_data,
                            items_to_add=items_to_add,
                        )
                    except Exception as e:
                        runner._log_message(
                            f"[Subtitles] ERROR processing track {item.track.id}: {e}"
                        )
                        raise
                # PGS bitmap subtitles - shift PTSes in-app and audit.
                # mkvmerge gets --sync 0 because timing is baked into the file.
                elif ext == ".sup":
                    _shift_pgs_track(item, ctx, runner)
                # Other bitmap subtitles (VobSub) - can't process with unified flow
                # but CAN use video-verified mode for frame-corrected delays.
                # Phase 2 will replace this with an in-app VobSub shifter.
                elif subtitle_sync_mode == "video-verified":
                    from vsg_core.subtitles.sync_mode_plugins.video_verified.preprocessing import (
                        apply_for_bitmap_subtitle,
                    )

                    apply_for_bitmap_subtitle(item, ctx, runner, source1_file)
                else:
                    runner._log_message(
                        f"[Subtitles] Track {item.track.id}: Bitmap format {ext} - using mkvmerge --sync for delay"
                    )

        if items_to_add:
            ctx.extracted_items.extend(items_to_add)

        return ctx

    def _should_bypass_processing(self, item, ctx, ocr_subtitle_data) -> bool:
        """
        Check if we can bypass SubtitleData processing.

        Bypass conditions:
        - Time-based sync mode with bypass enabled
        - No OCR, style operations, stepping, or format conversion needed
        - Text-based subtitle format (not bitmap)

        Returns True if track can bypass SubtitleData processing.
        """
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

        # Can bypass if: no processing needed AND bypass enabled AND time-based mode
        return (
            not needs_subtitle_data
            and bypass_subtitle_data
            and subtitle_sync_mode == "time-based"
        )


# ============================================================================
# Bitmap shifter helpers (Phase 1: PGS only)
# ============================================================================


def _resolve_bitmap_delay(item, ctx) -> tuple[float, str]:
    """Pick the delay and tier classification for a bitmap subtitle track.

    Returns ``(delay_ms, kind)``. ``kind`` is used by the auditor to
    decide whether to run Tier 2 frame-alignment as corrective signal
    or informational diagnostic.
    """
    tr = item.track
    source_key = item.sync_to if tr.source == "External" else tr.source
    if source_key in (None, "Source 1"):
        return 0.0, "zero"

    vv = ctx.video_verified_sources.get(source_key)
    if vv is not None:
        corrected = float(vv.get("corrected_delay_ms", 0.0))
        if vv.get("fallback"):
            return corrected, "vv-correlation-fallback"
        return corrected, "vv-frame"

    # Time-based or no VV preprocessing — fall back to raw correlation.
    if ctx.delays and source_key in ctx.delays.raw_source_delays_ms:
        return float(ctx.delays.raw_source_delays_ms[source_key]), "correlation"
    if ctx.delays and source_key in ctx.delays.source_delays_ms:
        return float(ctx.delays.source_delays_ms[source_key]), "correlation"
    return 0.0, "zero"


def _shift_pgs_track(item, ctx, runner) -> None:
    """Apply a constant delay to a PGS track in-app and audit the result."""
    from vsg_core.subtitles.operations.bitmap_audit import (
        BitmapAuditResult,
        BitmapEvent,
        tier1_sanity,
        tier2_frame_alignment,
    )
    from vsg_core.subtitles.operations.pgs_timing import (
        PTS_CLOCK_HZ,
        apply_constant_shift,
        extract_events,
        walk_segments,
    )

    tr = item.track
    track_label = f"{tr.source} / track {tr.id} / PGS / {tr.props.lang or 'und'}"

    delay_ms, kind = _resolve_bitmap_delay(item, ctx)

    runner._log_message(
        f"[BitmapShifter] {track_label}: delay = {delay_ms:+.3f} ms ({kind})"
    )

    if item.extracted_path is None:
        runner._log_message(
            f"[BitmapShifter] {track_label}: no extracted path — skipping"
        )
        return

    src_path = item.extracted_path
    out_path = src_path.parent / f"bitmap_shifted_{src_path.name}"
    try:
        raw = src_path.read_bytes()
        new_bytes, shift_res = apply_constant_shift(
            raw, delay_ms, drop_negative=True, log=runner._log_message
        )
        out_path.write_bytes(new_bytes)
    except Exception as exc:  # pragma: no cover - defensive
        runner._log_message(
            f"[BitmapShifter] {track_label}: shift failed ({exc}) — "
            "falling back to mkvmerge --sync"
        )
        return

    # Build event list for audit from the shifted bytes.
    segments_after, _ = walk_segments(new_bytes)
    events_after = extract_events(segments_after, new_bytes)
    bitmap_events = [
        BitmapEvent(
            start_ms=ev.start_pts_ticks / (PTS_CLOCK_HZ / 1000),
            end_ms=(
                ev.end_pts_ticks / (PTS_CLOCK_HZ / 1000)
                if ev.end_pts_ticks is not None
                else None
            ),
            source_tag=f"pcs#{ev.start_segment_index}",
        )
        for ev in events_after
    ]

    # Tier 1 sanity (always). Detect Source 1 properties on demand so
    # time-based mode gets the same audit coverage as video-verified.
    _lookup_source1_properties(ctx, runner)
    video_duration_ms = _lookup_video_duration_ms(ctx)
    tier1 = tier1_sanity(
        bitmap_events,
        video_duration_ms=video_duration_ms,
        events_dropped_pre_shift=shift_res.events_dropped,
    )

    # Tier 2 frame alignment (whenever a target fps is available).
    fps = _lookup_target_fps(ctx)
    tier2 = None
    if fps is not None and fps > 0:
        tier2 = tier2_frame_alignment(bitmap_events, fps)

    result = BitmapAuditResult(
        track_label=track_label,
        format_tag="PGS",
        delay_source_kind=kind,  # type: ignore[arg-type]  # Literal narrowed by helper
        requested_delay_ms=delay_ms,
        applied_delay_ms=shift_res.applied_delay_ms,
        target_fps=fps,
        tier1=tier1,
        tier2=tier2,
    )
    audit_key = f"{tr.source}_t{tr.id}"
    ctx.bitmap_audit_results[audit_key] = result

    item.extracted_path = out_path
    item.frame_adjusted = True  # signals options_builder to emit --sync 0

    runner._log_message(
        f"[BitmapShifter] {track_label}: shifted {shift_res.segments_shifted} "
        f"segment(s), dropped {shift_res.events_dropped} event(s); "
        f"audit stored as {audit_key}"
    )


def _lookup_source1_properties(ctx, runner) -> dict | None:
    """Return Source 1's detected video properties, fetching on demand.

    Caches into ``ctx.video_properties`` so the time-based path gets
    the same FPS/duration coverage as the video-verified path without
    duplicating ffprobe calls.
    """
    if ctx.video_properties.get("Source 1"):
        return ctx.video_properties["Source 1"]
    src1 = ctx.sources.get("Source 1") if ctx.sources else None
    if not src1:
        return None
    try:
        from vsg_core.subtitles.frame_utils import detect_video_properties

        props = detect_video_properties(str(src1), runner)
    except Exception:
        return None
    if props:
        ctx.video_properties["Source 1"] = props
    return props or None


def _lookup_video_duration_ms(ctx) -> float | None:
    """Pull Source 1's video duration in ms from ``ctx.video_properties`` if cached."""
    props = ctx.video_properties.get("Source 1") if ctx.video_properties else None
    if not props:
        return None
    dur = props.get("duration_ms")
    if isinstance(dur, (int, float)) and dur > 0:
        return float(dur)
    return None


def _lookup_target_fps(ctx) -> float | None:
    """Pull Source 1's fps from ``ctx.video_properties`` if cached."""
    props = ctx.video_properties.get("Source 1") if ctx.video_properties else None
    if not props:
        return None
    fps = props.get("fps")
    if isinstance(fps, (int, float)) and fps > 0:
        return float(fps)
    return None
