# vsg_core/subtitles/sync_dispatcher.py
"""
Sync mode dispatcher for subtitle processing.

Coordinates sync mode application with optimizations:
- Video-verified caching (avoid redundant frame matching)
- Source 1 reference handling (skip frame matching for reference)
- Plugin dispatch for all sync modes
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context
    from vsg_core.subtitles.data import OperationResult, SubtitleData
    from vsg_core.subtitles.frame_utils.frame_clock import FrameClock
    from vsg_core.subtitles.frame_utils.frame_table import (
        FrameGrid,
        FrameGridNote,
        FrameTable,
    )

from vsg_core.subtitles.sync_modes import get_sync_plugin


def apply_sync_mode(
    item,
    subtitle_data: SubtitleData,
    ctx: Context,
    runner: CommandRunner,
    source1_file: Path | None,
    sync_mode: str,
    scene_cache: dict[str, Any],
) -> OperationResult:
    """
    Apply sync mode to subtitle data.

    Handles:
    - Video-verified caching (use pre-computed delays)
    - Video-verified Source 1 reference case
    - Plugin dispatch for all sync modes

    Args:
        item: ExtractedItem being processed
        subtitle_data: SubtitleData to sync (modified in place)
        ctx: Context with delays and settings
        runner: CommandRunner for logging
        source1_file: Target video file (Source 1)
        sync_mode: Sync mode name
        scene_cache: Scene detection cache (unused currently)

    Returns:
        OperationResult with success/failure and statistics
    """
    # Get source and delays
    source_key = item.sync_to if item.track.source == "External" else item.track.source
    source_video = ctx.sources.get(source_key)
    target_video = source1_file

    # Get delays
    # PRIORITY: Check if this source has a subtitle-specific delay (e.g., from video-verified)
    # Otherwise, use the correlation delay from analysis
    total_delay_ms = 0.0
    global_shift_ms = 0.0
    if ctx.delays:
        if source_key in ctx.subtitle_delays_ms:
            # Subtitle-specific delay (e.g., video-verified frame-corrected delay)
            total_delay_ms = ctx.subtitle_delays_ms[source_key]
        elif source_key in ctx.delays.raw_source_delays_ms:
            # Default: correlation delay from analysis
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

    # Exact CFR frame clock for the target. None for VFR / MPEG-2 / interlaced,
    # in which case rounding falls back to plain floor (no surgical, no audit) —
    # the same effective behaviour those paths already have.
    target_clock = _detect_target_clock(ctx, target_video, runner)

    # Frame grid for save-time rounding and the frame audit: Source 1's real
    # frame timestamps. Whole-frame shifts (FrameShift) still use target_clock.
    frame_grid = _resolve_frame_grid(ctx, target_video, target_clock, runner)

    runner._log_message(f"[Sync] Mode: {sync_mode}")
    runner._log_message(
        f"[Sync] Delay: {total_delay_ms:+.3f}ms (global: {global_shift_ms:+.3f}ms)"
    )

    # OPTIMIZATION 1: Check if video-verified was already computed for this source
    # If so, use the pre-computed delay and apply it directly (skip re-running frame matching)
    if sync_mode == "video-verified" and source_key in ctx.video_verified_sources:
        return _apply_cached_video_verified(
            subtitle_data=subtitle_data,
            ctx=ctx,
            source_key=source_key,
            runner=runner,
            target_fps=target_fps,
            target_video=target_video,
            item=item,
            target_clock=target_clock,
            frame_grid=frame_grid,
            global_shift_ms=global_shift_ms,
        )

    # OPTIMIZATION 2: For video-verified mode, Source 1 is the reference
    # No frame matching needed (Source 1 would compare against itself which is incorrect)
    # Just apply the delay directly (which is just global_shift for Source 1)
    if sync_mode == "video-verified" and source_key == "Source 1":
        return _apply_video_verified_reference(
            subtitle_data=subtitle_data,
            total_delay_ms=total_delay_ms,
            runner=runner,
            target_fps=target_fps,
            target_video=target_video,
            item=item,
            ctx=ctx,
            frame_grid=frame_grid,
        )

    # NORMAL PATH: Use sync plugin
    plugin = get_sync_plugin(sync_mode)

    if plugin:
        # Use unified plugin
        runner._log_message(f"[Sync] Using plugin: {plugin.name}")

        result = plugin.apply(
            subtitle_data=subtitle_data,
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            target_fps=target_fps,
            source_video=str(source_video) if source_video else None,
            target_video=str(target_video) if target_video else None,
            runner=runner,
            settings=ctx.settings,
            temp_dir=ctx.temp_dir,
            sync_exclusion_styles=item.sync_exclusion_styles,
            sync_exclusion_mode=item.sync_exclusion_mode,
            track_label=_build_track_label(item),
            debug_paths=ctx.debug_paths,
            ctx=ctx,
            frame_clock=target_clock,
            frame_grid=frame_grid,
        )

        if result.success:
            runner._log_message(f"[Sync] {result.summary}")
        else:
            runner._log_message(f"[Sync] WARNING: {result.error or 'Sync failed'}")

        # === AUDIT: Record sync operation details ===
        if ctx.audit:
            track_key = f"track_{item.track.id}_{item.track.source.replace(' ', '_')}"
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
                events_modified=result.events_affected,
                stepping_adjusted_before=item.stepping_adjusted,
                stepping_adjusted_after=item.stepping_adjusted,
                frame_adjusted_before=item.frame_adjusted,
                frame_adjusted_after=item.frame_adjusted,  # Updated in caller
            )

        return result

    else:
        # Unknown sync mode
        from vsg_core.subtitles.data import OperationResult

        runner._log_message(f"[Sync] ERROR: Unknown sync mode: {sync_mode}")
        return OperationResult(
            success=False, operation="sync", error=f"Unknown sync mode: {sync_mode}"
        )


def _apply_cached_video_verified(
    subtitle_data: SubtitleData,
    ctx: Context,
    source_key: str,
    runner: CommandRunner,
    target_fps: float | None,
    target_video: Path | None,
    item,
    target_clock: FrameClock | None = None,
    frame_grid: FrameGrid | None = None,
    global_shift_ms: float = 0.0,
) -> OperationResult:
    """
    Apply video-verified sync using cached pre-computed delay.

    This is an optimization to avoid re-running frame matching
    for every subtitle track from the same source.
    """
    from vsg_core.subtitles.data import OperationResult
    from vsg_core.subtitles.sync_utils import apply_delay_to_events, build_frame_shift

    cached = ctx.video_verified_sources[source_key]
    if cached.get("fallback"):
        runner._log_message(
            f"[Sync] Using audio correlation fallback for {source_key} (frame matching failed)"
        )
    else:
        runner._log_message(
            f"[Sync] Using pre-computed video-verified delay for {source_key}"
        )
    runner._log_message(f"[Sync]   Delay: {cached['corrected_delay_ms']:+.1f}ms")

    # Build an exact whole-frame shift when this is a real CFR frame match with
    # no sub-frame component; otherwise events take the flat delay (unchanged).
    frame_shift = build_frame_shift(
        target_clock,
        cached.get("details") or {},
        global_shift_ms,
        fallback=bool(cached.get("fallback")),
    )
    if frame_shift is not None:
        runner._log_message(
            f"[Sync]   Exact frame snap: {frame_shift.frames:+d} frames "
            f"@ {frame_shift.clock.num}/{frame_shift.clock.den}"
        )

    # Apply the delay directly to subtitle events (like time-based mode)
    events_synced = apply_delay_to_events(
        subtitle_data, cached["corrected_delay_ms"], frame_shift=frame_shift
    )

    runner._log_message(
        f"[Sync] Applied {cached['corrected_delay_ms']:+.1f}ms to {events_synced} events"
    )

    # Run frame audit if enabled (shortcut path bypasses plugin where audit normally runs)
    job_name = _build_audit_job_name(target_video, item)
    _run_frame_audit_if_enabled(
        subtitle_data=subtitle_data,
        clock=frame_grid,
        offset_ms=cached["corrected_delay_ms"],
        job_name=job_name,
        ctx=ctx,
        runner=runner,
    )

    # Carry the frame grid in details for surgical rounding at save time
    details = dict(cached["details"]) if cached.get("details") else {}
    details["target_fps"] = target_fps
    details["frame_grid"] = frame_grid

    return OperationResult(
        success=True,
        operation="sync",
        events_affected=events_synced,
        summary=(
            f"Audio correlation fallback: {cached['corrected_delay_ms']:+.1f}ms applied to {events_synced} events"
            if cached.get("fallback")
            else f"Video-verified (pre-computed): {cached['corrected_delay_ms']:+.1f}ms applied to {events_synced} events"
        ),
        details=details,
    )


def _apply_video_verified_reference(
    subtitle_data: SubtitleData,
    total_delay_ms: float,
    runner: CommandRunner,
    target_fps: float | None,
    target_video: Path | None,
    item,
    ctx: Context,
    frame_grid: FrameGrid | None = None,
) -> OperationResult:
    """
    Apply video-verified for Source 1 (reference video).

    Source 1 is the reference, so no frame matching is needed.
    Just apply the delay directly (which is just global_shift for Source 1).
    The delay is a global shift (often sub-frame), not a whole-frame offset, so
    events take the flat delay; the frame grid is only used for save-time
    rounding and the frame audit.
    """
    from vsg_core.subtitles.data import OperationResult
    from vsg_core.subtitles.sync_utils import apply_delay_to_events

    runner._log_message(
        "[Sync] Source 1 is reference - applying delay directly without frame matching"
    )

    events_synced = apply_delay_to_events(subtitle_data, total_delay_ms)

    runner._log_message(
        f"[Sync] Applied {total_delay_ms:+.1f}ms to {events_synced} events (reference)"
    )

    # Run frame audit if enabled (shortcut path bypasses plugin where audit normally runs)
    job_name = _build_audit_job_name(target_video, item)
    _run_frame_audit_if_enabled(
        subtitle_data=subtitle_data,
        clock=frame_grid,
        offset_ms=total_delay_ms,
        job_name=job_name,
        ctx=ctx,
        runner=runner,
    )

    return OperationResult(
        success=True,
        operation="sync",
        events_affected=events_synced,
        summary=f"Video-verified (Source 1 reference): {total_delay_ms:+.1f}ms applied to {events_synced} events",
        details={"target_fps": target_fps, "frame_grid": frame_grid},
    )


def _run_frame_audit_if_enabled(
    subtitle_data: SubtitleData,
    clock: FrameGrid | None,
    offset_ms: float,
    job_name: str,
    ctx: Context,
    runner: CommandRunner,
) -> None:
    """
    Run frame alignment audit for video-verified sync.

    Runs only when the target has a frame grid (``clock`` is not None): its
    real frame timestamps, or the CFR formula if those could not be read.
    Without a grid the audit is skipped — matching the plain-rounding save
    path (multi-source jobs onto an MPEG-2/interlaced/VFR Source 1). The summary
    is always logged; the detailed per-line report file is only written when the
    debug setting (video_verified_frame_audit) is enabled.

    This is called from shortcut paths (cached video-verified, Source 1 reference)
    that bypass the plugin's apply() method where the audit would normally run.
    """
    if clock is None:
        runner._log_message(
            "[FrameAudit] Skipped: no frame grid for target "
            "(multi-source job onto VFR/MPEG-2/interlaced Source 1)"
        )
        return

    try:
        from vsg_core.subtitles.frame_utils.frame_audit import (
            run_frame_audit,
            write_audit_report,
        )

        runner._log_message("[FrameAudit] Running frame alignment audit...")

        # Get rounding mode from settings
        rounding_mode = ctx.settings.subtitle_rounding or "floor"

        # Run the audit
        result = run_frame_audit(
            subtitle_data=subtitle_data,
            clock=clock,
            rounding_mode=rounding_mode,
            offset_ms=offset_ms,
            job_name=job_name,
            log=runner._log_message,
        )

        # Store result on context for the final auditor
        ctx.frame_audit_results[job_name] = result

        # Write detailed report only when debug setting is enabled
        if ctx.settings.video_verified_frame_audit:
            # Determine output directory
            # Use debug_paths if available (new organized structure), fallback to old location
            if ctx.debug_paths and ctx.debug_paths.frame_audit_dir:
                config_dir = ctx.debug_paths.frame_audit_dir
            else:
                config_dir = Path.cwd() / ".config" / "sync_checks"

            report_path = write_audit_report(result, config_dir, runner._log_message)
            runner._log_message(f"[FrameAudit] Report saved: {report_path}")

        # Log summary (always)
        total = result.total_events
        if total > 0:
            start_pct = 100 * result.start_ok / total
            end_pct = 100 * result.end_ok / total
            runner._log_message(
                f"[FrameAudit] Start times OK: {result.start_ok}/{total} ({start_pct:.1f}%)"
            )
            runner._log_message(
                f"[FrameAudit] End times OK: {result.end_ok}/{total} ({end_pct:.1f}%)"
            )

            if result.has_issues:
                # Find best rounding mode
                modes = [
                    ("floor", result.floor_issues),
                    ("round", result.round_issues),
                    ("ceil", result.ceil_issues),
                ]
                best_mode = min(modes, key=lambda x: x[1])[0]
                runner._log_message(
                    f"[FrameAudit] Issues found: {len(result.issues)} events with frame drift"
                )
                runner._log_message(
                    f"[FrameAudit] Suggested rounding mode: {best_mode}"
                )
                if result.predicted_corrections > 0:
                    runner._log_message(
                        f"[FrameAudit] Surgical rounding will correct: "
                        f"{result.predicted_corrections} timing points "
                        f"({result.predicted_correction_events} events)"
                    )
            else:
                runner._log_message("[FrameAudit] No frame drift issues detected")

    except Exception as e:
        runner._log_message(f"[FrameAudit] WARNING: Audit failed - {e}")


def _detect_target_clock(
    ctx: Context, target_video: Path | None, runner: CommandRunner
) -> FrameClock | None:
    """Exact CFR frame clock for the target (Source 1), or None for VFR/MPEG-2.

    Reuses Source 1 properties cached by the video-verified preprocessing step
    when available, else probes the target. None means "no trustworthy grid" —
    callers fall back to plain rounding with no surgical pass and no audit.
    """
    if target_video is None:
        return None
    from vsg_core.subtitles.frame_utils import (
        detect_frame_clock,
        frame_clock_from_props,
    )

    props = ctx.video_properties.get("Source 1") if ctx.video_properties else None
    if props:
        return frame_clock_from_props(props)
    try:
        return detect_frame_clock(str(target_video), runner)
    except Exception as e:
        runner._log_message(f"[Sync] WARNING: Could not build frame clock: {e}")
        return None


def _resolve_frame_grid(
    ctx: Context,
    target_video: Path | None,
    target_clock: FrameClock | None,
    runner: CommandRunner,
) -> FrameGrid | None:
    """Frame grid for save-time rounding and the frame audit.

    Source 1's real frame timestamps replace the CFR formula wherever a grid is
    used today (progressive targets, any job). They are also used for MPEG-2 /
    interlaced / VFR targets in single-source jobs (remux / OCR), where Source
    1's own tracks are the only subtitles — multi-source jobs onto such a target
    keep plain rounding until frame matching supports them. If the timestamps
    cannot be read, the old behaviour stands (formula, or no grid).
    """
    if target_video is None:
        return target_clock
    single_source = len(ctx.sources) == 1
    if target_clock is None and not single_source:
        return None
    table = _source1_frame_table(ctx, target_video, target_clock, runner)
    return table if table is not None else target_clock


def _source1_frame_table(
    ctx: Context,
    target_video: Path,
    target_clock: FrameClock | None,
    runner: CommandRunner,
) -> FrameTable | None:
    """Source 1's real frame timestamps, read once per job and cached on ctx.

    The first read also checks the timeline (holes, first frame not at 0) and,
    for progressive targets, whether the CFR formula agreed with reality —
    findings are logged and kept for the final frame-alignment audit.
    """
    key = str(target_video)
    if key in ctx.frame_tables:
        return ctx.frame_tables[key]

    from vsg_core.subtitles.frame_utils.frame_table import (
        FrameGridNote,
        build_frame_table,
        check_timeline,
    )

    log = runner._log_message
    log("[FrameGrid] Reading Source 1 frame timestamps (ffms2 index)...")
    table = build_frame_table(str(target_video), ctx.temp_dir, log)
    ctx.frame_tables[key] = table
    if table is None:
        fallback = target_clock.label if target_clock else "plain rounding"
        log(f"[FrameGrid] Falling back to {fallback}")
        return None
    log(f"[FrameGrid] Source 1: {table.label}")

    notes: list[FrameGridNote] = []
    timeline = check_timeline(table)
    if timeline.first_frame_ms > 0:
        notes.append(
            FrameGridNote(
                "info",
                f"Source 1 first video frame is at {timeline.first_frame_ms:.0f} ms "
                f"(not 0) - real timestamps account for it",
            )
        )
    for gap in timeline.gaps:
        notes.append(
            FrameGridNote(
                "warning",
                f"Source 1 video timeline jumps {gap.jump_ms:.0f} ms at "
                f"{_format_clock(gap.before_ms)} (frame {gap.frame}; regular frame "
                f"period <= {timeline.regular_max_ms:.0f} ms) - a hole in the stream; "
                f"check subtitles around it",
            )
        )
    if target_clock is not None:
        notes.extend(_compare_formula(table, target_clock))
    else:
        notes.append(
            FrameGridNote(
                "info",
                "Source 1 has no CFR frame formula (MPEG-2/interlaced/VFR); "
                "single-source job - rounding uses its real frame timestamps",
            )
        )

    for note in notes:
        prefix = "⚠ " if note.severity == "warning" else ""
        log(f"[FrameGrid] {prefix}{note.message}")
    ctx.frame_grid_notes.extend(notes)
    return table


def _compare_formula(table: FrameTable, clock: FrameClock) -> list[FrameGridNote]:
    """Compare the CFR formula with the real timestamps it used to stand in for."""
    from vsg_core.subtitles.frame_utils.frame_table import FrameGridNote

    mismatches = [
        n
        for n, real in enumerate(table.times_ms)
        if abs(real - clock.frame_ms(n)) >= 0.5
    ]
    if not mismatches:
        return [
            FrameGridNote(
                "info",
                f"{clock.label} matches the real timestamps on all "
                f"{table.num_frames} frames - output identical to formula rounding",
            )
        ]
    first = mismatches[0]
    return [
        FrameGridNote(
            "warning",
            f"{clock.label} disagrees with the real timestamps on "
            f"{len(mismatches)} of {table.num_frames} frames (first: frame {first} "
            f"real {table.times_ms[first]:.0f} ms vs formula {clock.frame_ms(first)} "
            f"ms) - real timestamps used for rounding",
        )
    ]


def _format_clock(ms: float) -> str:
    """H:MM:SS.mmm for log lines."""
    total = int(ms)
    h, rem = divmod(total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{msec:03d}"


def _build_track_label(item) -> str:
    """Build a unique label for a track (used in audit report filenames)."""
    track_id = item.track.id
    source = item.track.source.replace(" ", "")
    if item.is_generated:
        return f"{source}_t{track_id}_gen"
    return f"{source}_t{track_id}"


def _build_audit_job_name(target_video: Path | None, item) -> str:
    """
    Build a unique job name for frame audit reports.

    Combines target video stem with track label to prevent
    reports from different tracks overwriting each other.
    """
    video_stem = Path(target_video).stem if target_video else "unknown"
    track_label = _build_track_label(item)
    return f"{video_stem}_{track_label}"
