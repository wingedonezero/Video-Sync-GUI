# vsg_core/subtitles/frame_utils/frame_audit.py
"""
Frame alignment audit for subtitle synchronization.

Analyzes subtitle timing after sync offset is applied but before save,
to detect cases where centisecond rounding would cause frame drift.

This is a diagnostic tool - it does not modify any timing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path  # noqa: TC003 - Used at runtime in write_audit_report
from typing import TYPE_CHECKING

from ..utils.timestamps import format_display_timestamp

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data import SubtitleData


@dataclass(slots=True)
class FrameAuditIssue:
    """Single frame alignment issue detected."""

    line_index: int
    text_preview: str  # First 40 chars of subtitle text
    timestamp_display: str  # Human-readable timestamp (e.g., "00:01:47.12")

    # Start time analysis
    exact_start_ms: float
    rounded_start_ms: int  # After centisecond rounding
    target_start_frame: int  # Frame the exact time falls in
    actual_start_frame: int  # Frame after rounding
    start_drift: int  # Frames off (negative = early, positive = late)
    start_fix_needed_ms: int  # Adjustment needed to fix

    # End time analysis
    exact_end_ms: float
    rounded_end_ms: int
    target_end_frame: int
    actual_end_frame: int
    end_drift: int
    end_fix_needed_ms: int

    # Duration
    original_duration_ms: float
    rounded_duration_ms: int
    duration_delta_ms: int

    @property
    def issue_type(self) -> str:
        """Categorize the issue."""
        if self.start_drift != 0 and self.end_drift != 0:
            return "BOTH_DRIFT"
        elif self.start_drift < 0:
            return "START_EARLY"
        elif self.start_drift > 0:
            return "START_LATE"
        elif self.end_drift < 0:
            return "END_EARLY"
        elif self.end_drift > 0:
            return "END_LATE"
        return "OK"


@dataclass(slots=True)
class FrameAuditResult:
    """Complete audit result for a sync job."""

    job_name: str
    fps: float
    frame_duration_ms: float
    rounding_mode: str
    offset_applied_ms: float
    total_events: int
    audit_timestamp: datetime

    # Start time stats
    start_ok: int = 0
    start_early: int = 0  # Rounded to earlier frame
    start_late: int = 0  # Rounded to later frame

    # End time stats
    end_ok: int = 0
    end_early: int = 0
    end_late: int = 0

    # Frame span stats
    span_ok: int = 0
    span_changed: int = 0

    # Duration stats
    duration_unchanged: int = 0  # 0ms delta
    duration_delta_10ms: int = 0  # ±10ms
    duration_delta_20ms: int = 0  # ±20ms
    duration_delta_large: int = 0  # >±20ms

    # Issues list (only events with problems)
    issues: list[FrameAuditIssue] = field(default_factory=list)

    # Rounding mode comparison
    floor_issues: int = 0
    round_issues: int = 0
    ceil_issues: int = 0

    @property
    def total_start_issues(self) -> int:
        return self.start_early + self.start_late

    @property
    def total_end_issues(self) -> int:
        return self.end_early + self.end_late

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0


def _time_to_frame(time_ms: float, frame_duration_ms: float) -> int:
    """Convert time to frame number (floor-based)."""
    epsilon = 1e-6
    return int((time_ms + epsilon) / frame_duration_ms)


def _round_to_centisecond(ms: float, mode: str) -> int:
    """Round milliseconds to centiseconds (10ms precision)."""
    value = ms / 10.0
    if mode == "ceil":
        return int(math.ceil(value)) * 10
    elif mode == "round":
        return int(round(value)) * 10
    else:  # floor (default)
        return int(math.floor(value)) * 10


def _find_minimal_fix(
    exact_ms: float,
    target_frame: int,
    frame_duration_ms: float,
    rounding_mode: str,
) -> int:
    """Find minimal centisecond adjustment to land in target frame.

    Returns the adjustment in ms needed (can be negative).
    """
    # Frame boundaries
    frame_start_ms = target_frame * frame_duration_ms
    frame_end_ms = (target_frame + 1) * frame_duration_ms

    # Current rounded value
    rounded = _round_to_centisecond(exact_ms, rounding_mode)
    actual_frame = _time_to_frame(rounded, frame_duration_ms)

    if actual_frame == target_frame:
        return 0  # Already correct

    # Find the first centisecond that lands in the target frame
    # Try rounding up (ceil) to get into frame
    ceil_cs = int(math.ceil(frame_start_ms / 10.0)) * 10
    if _time_to_frame(ceil_cs, frame_duration_ms) == target_frame:
        return ceil_cs - rounded

    # Try rounding down from frame end
    floor_cs = int(math.floor((frame_end_ms - 0.1) / 10.0)) * 10
    if _time_to_frame(floor_cs, frame_duration_ms) == target_frame:
        return floor_cs - rounded

    # Fallback: just report difference to frame start
    return int(frame_start_ms - rounded)


def run_frame_audit(
    subtitle_data: SubtitleData,
    fps: float,
    rounding_mode: str,
    offset_ms: float,
    job_name: str,
    log: Callable[[str], None] | None = None,
) -> FrameAuditResult:
    """
    Audit frame alignment for all subtitle events.

    This analyzes the current timing (after sync offset applied) and checks
    whether centisecond rounding will cause any events to land on wrong frames.

    Args:
        subtitle_data: SubtitleData with sync already applied
        fps: Target video FPS
        rounding_mode: Rounding mode that will be used at save ("floor", "round", "ceil")
        offset_ms: The sync offset that was applied (for reporting)
        job_name: Job identifier for the report
        log: Optional logging function

    Returns:
        FrameAuditResult with complete analysis
    """
    frame_duration_ms = 1000.0 / fps

    result = FrameAuditResult(
        job_name=job_name,
        fps=fps,
        frame_duration_ms=frame_duration_ms,
        rounding_mode=rounding_mode,
        offset_applied_ms=offset_ms,
        total_events=len(subtitle_data.events),
        audit_timestamp=datetime.now(),
    )

    if log:
        log(f"[FrameAudit] Starting audit: {len(subtitle_data.events)} events")
        log(f"[FrameAudit] FPS: {fps:.3f}, Frame duration: {frame_duration_ms:.3f}ms")
        log(f"[FrameAudit] Rounding mode: {rounding_mode}")

    for idx, event in enumerate(subtitle_data.events):
        if event.is_comment:
            continue

        # Current timing (after sync offset applied)
        exact_start = event.start_ms
        exact_end = event.end_ms

        # What frames should these land on?
        target_start_frame = _time_to_frame(exact_start, frame_duration_ms)
        target_end_frame = _time_to_frame(exact_end, frame_duration_ms)
        target_span = target_end_frame - target_start_frame

        # What will rounding produce?
        rounded_start = _round_to_centisecond(exact_start, rounding_mode)
        rounded_end = _round_to_centisecond(exact_end, rounding_mode)

        # What frames do rounded times land on?
        actual_start_frame = _time_to_frame(rounded_start, frame_duration_ms)
        actual_end_frame = _time_to_frame(rounded_end, frame_duration_ms)
        actual_span = actual_end_frame - actual_start_frame

        # Calculate drift
        start_drift = actual_start_frame - target_start_frame
        end_drift = actual_end_frame - target_end_frame

        # Duration analysis
        original_duration = exact_end - exact_start
        rounded_duration = rounded_end - rounded_start
        duration_delta = rounded_duration - int(original_duration)

        # Count stats
        if start_drift == 0:
            result.start_ok += 1
        elif start_drift < 0:
            result.start_early += 1
        else:
            result.start_late += 1

        if end_drift == 0:
            result.end_ok += 1
        elif end_drift < 0:
            result.end_early += 1
        else:
            result.end_late += 1

        if actual_span == target_span:
            result.span_ok += 1
        else:
            result.span_changed += 1

        if duration_delta == 0:
            result.duration_unchanged += 1
        elif abs(duration_delta) <= 10:
            result.duration_delta_10ms += 1
        elif abs(duration_delta) <= 20:
            result.duration_delta_20ms += 1
        else:
            result.duration_delta_large += 1

        # Check what other rounding modes would do
        for mode, counter_attr in [
            ("floor", "floor_issues"),
            ("round", "round_issues"),
            ("ceil", "ceil_issues"),
        ]:
            alt_rounded_start = _round_to_centisecond(exact_start, mode)
            alt_start_frame = _time_to_frame(alt_rounded_start, frame_duration_ms)
            if alt_start_frame != target_start_frame:
                setattr(result, counter_attr, getattr(result, counter_attr) + 1)

        # Record issue if there's drift
        if start_drift != 0 or end_drift != 0:
            text_preview = (
                event.text[:40] + "..." if len(event.text) > 40 else event.text
            )
            # Remove newlines for display
            text_preview = text_preview.replace("\n", " ").replace("\\N", " ")

            issue = FrameAuditIssue(
                line_index=idx,
                text_preview=text_preview,
                timestamp_display=format_display_timestamp(exact_start),
                exact_start_ms=exact_start,
                rounded_start_ms=rounded_start,
                target_start_frame=target_start_frame,
                actual_start_frame=actual_start_frame,
                start_drift=start_drift,
                start_fix_needed_ms=_find_minimal_fix(
                    exact_start, target_start_frame, frame_duration_ms, rounding_mode
                ),
                exact_end_ms=exact_end,
                rounded_end_ms=rounded_end,
                target_end_frame=target_end_frame,
                actual_end_frame=actual_end_frame,
                end_drift=end_drift,
                end_fix_needed_ms=_find_minimal_fix(
                    exact_end, target_end_frame, frame_duration_ms, rounding_mode
                ),
                original_duration_ms=original_duration,
                rounded_duration_ms=rounded_duration,
                duration_delta_ms=duration_delta,
            )
            result.issues.append(issue)

    if log:
        log(f"[FrameAudit] Audit complete: {len(result.issues)} issues found")

    return result


def write_audit_report(
    result: FrameAuditResult,
    output_dir: Path,
    log: Callable[[str], None] | None = None,
) -> Path:
    """
    Write the audit report to a file.

    Args:
        result: FrameAuditResult from run_frame_audit
        output_dir: Directory to write the report (will be created if needed)
        log: Optional logging function

    Returns:
        Path to the written report file
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp_str = result.audit_timestamp.strftime("%Y%m%d_%H%M%S")
    safe_job_name = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in result.job_name
    )
    filename = f"{safe_job_name}_{timestamp_str}_frame_audit.txt"
    output_path = output_dir / filename

    lines = []

    # Header
    lines.append("=" * 70)
    lines.append("FRAME ALIGNMENT AUDIT REPORT")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Job: {result.job_name}")
    lines.append(f"Audit time: {result.audit_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Sync offset applied: {result.offset_applied_ms:+.3f}ms")
    lines.append(
        f"Target FPS: {result.fps:.3f} (frame duration: {result.frame_duration_ms:.3f}ms)"
    )
    lines.append(f"Rounding mode: {result.rounding_mode}")
    lines.append(f"Total events: {result.total_events}")
    lines.append("")

    # Summary
    lines.append("=" * 70)
    lines.append("SUMMARY")
    lines.append("=" * 70)
    lines.append("")

    total = result.total_events
    if total > 0:
        lines.append("Start times:")
        lines.append(
            f"  Correct frame:     {result.start_ok:4d} ({100 * result.start_ok / total:.1f}%)"
        )
        lines.append(
            f"  1+ frame early:    {result.start_early:4d} ({100 * result.start_early / total:.1f}%)"
        )
        lines.append(
            f"  1+ frame late:     {result.start_late:4d} ({100 * result.start_late / total:.1f}%)"
        )
        lines.append("")

        lines.append("End times:")
        lines.append(
            f"  Correct frame:     {result.end_ok:4d} ({100 * result.end_ok / total:.1f}%)"
        )
        lines.append(
            f"  1+ frame early:    {result.end_early:4d} ({100 * result.end_early / total:.1f}%)"
        )
        lines.append(
            f"  1+ frame late:     {result.end_late:4d} ({100 * result.end_late / total:.1f}%)"
        )
        lines.append("")

        lines.append("Frame span:")
        lines.append(
            f"  Correct span:      {result.span_ok:4d} ({100 * result.span_ok / total:.1f}%)"
        )
        lines.append(
            f"  Span changed:      {result.span_changed:4d} ({100 * result.span_changed / total:.1f}%)"
        )
        lines.append("")

        lines.append("Duration delta:")
        lines.append(
            f"  Unchanged (0ms):   {result.duration_unchanged:4d} ({100 * result.duration_unchanged / total:.1f}%)"
        )
        lines.append(
            f"  +/-10ms:           {result.duration_delta_10ms:4d} ({100 * result.duration_delta_10ms / total:.1f}%)"
        )
        lines.append(
            f"  +/-20ms:           {result.duration_delta_20ms:4d} ({100 * result.duration_delta_20ms / total:.1f}%)"
        )
        lines.append(
            f"  >+/-20ms:          {result.duration_delta_large:4d} ({100 * result.duration_delta_large / total:.1f}%)"
        )
        lines.append("")

        # Rounding mode comparison
        lines.append("Rounding mode comparison (start time issues):")
        lines.append(f"  Floor:             {result.floor_issues:4d} issues")
        lines.append(f"  Round:             {result.round_issues:4d} issues")
        lines.append(f"  Ceil:              {result.ceil_issues:4d} issues")

        best_mode = min(
            [
                ("floor", result.floor_issues),
                ("round", result.round_issues),
                ("ceil", result.ceil_issues),
            ],
            key=lambda x: x[1],
        )
        lines.append(f"  Suggested mode:    {best_mode[0]} (fewest issues)")
        lines.append("")

    # Issues section
    if result.issues:
        lines.append("=" * 70)
        lines.append(f"ISSUES ({len(result.issues)} events with frame drift)")
        lines.append("=" * 70)
        lines.append("")

        # Sort issues by type for readability
        sorted_issues = sorted(
            result.issues, key=lambda i: (i.issue_type, i.line_index)
        )

        for issue in sorted_issues:
            lines.append(
                f"[{issue.issue_type}] Line {issue.line_index} @ {issue.timestamp_display}"
            )
            lines.append(f'  Text: "{issue.text_preview}"')

            if issue.start_drift != 0:
                direction = "EARLY" if issue.start_drift < 0 else "LATE"
                lines.append(
                    f"  Start: {issue.exact_start_ms:.2f}ms -> {issue.rounded_start_ms}ms "
                    f"(frame {issue.target_start_frame} -> {issue.actual_start_frame}) "
                    f"{abs(issue.start_drift)} FRAME {direction}"
                )
                lines.append(
                    f"  Would need: {issue.start_fix_needed_ms:+d}ms to fix start"
                )
            else:
                lines.append(f"  Start OK: frame {issue.target_start_frame}")

            if issue.end_drift != 0:
                direction = "EARLY" if issue.end_drift < 0 else "LATE"
                lines.append(
                    f"  End: {issue.exact_end_ms:.2f}ms -> {issue.rounded_end_ms}ms "
                    f"(frame {issue.target_end_frame} -> {issue.actual_end_frame}) "
                    f"{abs(issue.end_drift)} FRAME {direction}"
                )
                lines.append(f"  Would need: {issue.end_fix_needed_ms:+d}ms to fix end")
            else:
                lines.append(f"  End OK: frame {issue.target_end_frame}")

            if issue.duration_delta_ms != 0:
                lines.append(
                    f"  Duration: {issue.original_duration_ms:.1f}ms -> {issue.rounded_duration_ms}ms ({issue.duration_delta_ms:+d}ms)"
                )

            lines.append("")
    else:
        lines.append("=" * 70)
        lines.append("NO ISSUES DETECTED")
        lines.append("=" * 70)
        lines.append("")
        lines.append(
            "All subtitle events will land on their correct frames after rounding."
        )
        lines.append("")

    # Footer
    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    # Write file
    output_path.write_text("\n".join(lines), encoding="utf-8")

    if log:
        log(f"[FrameAudit] Report written to: {output_path}")

    return output_path
