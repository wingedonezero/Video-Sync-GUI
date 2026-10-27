# vsg_core/subtitles/frame_grids.py
"""
Per-job frame grids: which real frame timeline each subtitle decision uses.

Every video's frame timestamps are read once per job (ffms2 index, cached on
``ctx.frame_tables``) and shared by the text-subtitle sync/save path and the
bitmap (PGS/VobSub) shifter's audit. Source 1's first read also records
timeline findings (holes, start offset, formula disagreement) for the final
audit.

Scope rule (agreed 2026-10): Source 1's real timestamps are used wherever a
progressive target had a grid before (any job), and for MPEG-2 / interlaced /
VFR targets only in single-source jobs, until frame matching supports them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vsg_core.subtitles.frame_utils.frame_table import (
    FrameGridNote,
    FrameTable,
    build_frame_table,
    check_timeline,
)

if TYPE_CHECKING:
    from vsg_core.orchestrator.steps.context import Context
    from vsg_core.subtitles.frame_utils.frame_clock import FrameClock
    from vsg_core.subtitles.frame_utils.frame_table import FrameGrid

Log = Callable[[str], None]

# Two container timelines stored in whole milliseconds can disagree by up to
# 1 ms about the same instant (each rounds by <= 0.5 ms). A larger spread in
# the paired-frame time difference means a hole or a different frame rate.
_MS_QUANTISATION_SPREAD = 1.0


def frame_table_for(ctx: Context, video_path: str, log: Log) -> FrameTable | None:
    """Real frame timestamps of ``video_path``, read once per job (None = unusable)."""
    if video_path in ctx.frame_tables:
        return ctx.frame_tables[video_path]
    log(
        f"[FrameGrid] Reading frame timestamps of {Path(video_path).name} (ffms2 index)..."
    )
    table = build_frame_table(video_path, ctx.temp_dir, log)
    ctx.frame_tables[video_path] = table
    if table is not None:
        log(f"[FrameGrid] {Path(video_path).name}: {table.label}")
    return table


def target_grid_eligible(ctx: Context, target_clock: FrameClock | None) -> bool:
    """Whether Source 1 gets a frame grid at all (see the module scope rule)."""
    return target_clock is not None or len(ctx.sources) == 1


def resolve_target_grid(
    ctx: Context,
    target_video: Path | None,
    target_clock: FrameClock | None,
    log: Log,
) -> FrameGrid | None:
    """Source 1's frame grid for rounding and audits.

    Real timestamps when eligible and readable; otherwise the old behaviour
    (the CFR formula, or no grid).
    """
    if target_video is None:
        return target_clock
    if not target_grid_eligible(ctx, target_clock):
        return None
    table = source1_frame_table(ctx, target_video, target_clock, log)
    return table if table is not None else target_clock


def source1_frame_table(
    ctx: Context,
    target_video: Path,
    target_clock: FrameClock | None,
    log: Log,
) -> FrameTable | None:
    """Source 1's real frame timestamps; the first call also checks its timeline."""
    key = str(target_video)
    table = frame_table_for(ctx, key, log)
    if key in ctx.frame_grid_checked:
        return table
    ctx.frame_grid_checked.add(key)
    if table is None:
        fallback = target_clock.label if target_clock else "plain rounding"
        add_grid_warning(
            ctx,
            f"Could not read Source 1's real frame times - rounding fell back to "
            f"{fallback}",
            log,
        )
        return None

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
                f"{format_clock(gap.before_ms)} (frame {gap.frame}; regular frame "
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


def add_grid_warning(ctx: Context, message: str, log: Log) -> None:
    """Record a frame-grid fallback for the final audit (once per message)."""
    if any(n.message == message for n in ctx.frame_grid_notes):
        return
    log(f"[FrameGrid] ⚠ {message}")
    ctx.frame_grid_notes.append(FrameGridNote("warning", message))


@dataclass(frozen=True, slots=True)
class MatchedFrames:
    """A frame match confirmed on both real timelines: source frame k shows on
    target frame ``k + frames`` for every source frame below ``source_end``."""

    frames: int
    source_end: int


def matched_frame_offset(
    source: FrameTable,
    target: FrameTable,
    details: Mapping[str, Any],  # Any: sliding-matcher details dict (JSON-like)
    log: Log,
) -> int | None:
    """Frame offset R from a frame match: source frame k shows on target frame k+R.

    R is the matcher's frame-index offset (``index_consensus_frames`` plus the
    PTS-origin difference it subtracted). It is only returned when both real
    timelines confirm it file-wide: every paired frame (k, k+R) is the same
    wall-clock distance apart, up to whole-ms storage. A hole in either video
    or a different frame rate breaks that and returns None (flat delay).
    """
    match = matched_frame_range(source, target, details, log, allow_tail=False)
    return None if match is None else match.frames


def matched_frame_range(
    source: FrameTable,
    target: FrameTable,
    details: Mapping[str, Any],  # Any: sliding-matcher details dict (JSON-like)
    log: Log,
    *,
    allow_tail: bool,
) -> MatchedFrames | None:
    """``matched_frame_offset``, optionally confirmed only up to a break.

    With ``allow_tail``, paired frames that stop agreeing after every picture
    the matcher compared (e.g. an encode whose last frame is stamped late)
    still give the offset, valid for the source frames before the break; the
    frames from the break on take the flat delay. A break at or before a
    compared picture returns None, as file-wide.
    """
    if details.get("reason") != "sliding-matched":
        return None
    index_frames = details.get("index_consensus_frames")
    pts_delta_frames = details.get("pts_delta_frames", 0)
    if not isinstance(index_frames, int) or not isinstance(pts_delta_frames, int):
        log("[FrameGrid] Frame match has no frame-index offset - no exact snap")
        return None
    r = index_frames + pts_delta_frames
    lo = max(0, -r)
    hi = min(source.num_frames, target.num_frames - r)
    if hi - lo < 2:
        log(f"[FrameGrid] Offset {r:+d} frames leaves no overlap - no exact snap")
        return None
    diffs = [target.times_ms[k + r] - source.times_ms[k] for k in range(lo, hi)]
    agree = _agreeing_prefix(diffs)
    if agree < len(diffs):
        brk = lo + agree
        compared_end = _compared_source_end(details)
        if not allow_tail or compared_end is None or brk < compared_end:
            spread = max(diffs) - min(diffs)
            log(
                f"[FrameGrid] Paired frames drift {spread:.1f} ms over the file at "
                f"{r:+d} frames (hole or different frame rate) - no exact snap"
            )
            return None
        log(
            f"[FrameGrid] Paired frames at {r:+d} frames agree up to source frame "
            f"{brk} of {source.num_frames}, after every compared picture (last "
            f"{compared_end - 1}); source frame {brk} breaks the pairing by "
            f"{diffs[agree] - diffs[0]:+.1f} ms - exact snap before it, flat "
            "delay from it"
        )
        diffs = diffs[:agree]
        hi = brk
    video_offset = details.get("video_offset_ms")
    if isinstance(video_offset, (int, float)):
        paired = (max(diffs) + min(diffs)) / 2
        if abs(paired - video_offset) >= target.frame_duration_ms / 2:
            log(
                f"[FrameGrid] Frame offset {r:+d} ({paired:+.1f} ms) disagrees with "
                f"the matched {video_offset:+.1f} ms - no exact snap"
            )
            return None
    return MatchedFrames(frames=r, source_end=hi)


def _agreeing_prefix(diffs: list[float]) -> int:
    """How many leading paired-frame differences stay within whole-ms storage."""
    low = high = diffs[0]
    for i, d in enumerate(diffs):
        low, high = min(low, d), max(high, d)
        if high - low > _MS_QUANTISATION_SPREAD:
            return i
    return len(diffs)


def _compared_source_end(details: Mapping[str, Any]) -> int | None:
    """One past the last source frame any matcher window compared, or None."""
    ends = [
        int(p["src_start"]) + int(p["total"])
        for p in details.get("per_position_results") or []
        if isinstance(p, Mapping) and "src_start" in p and "total" in p
    ]
    return max(ends) if ends else None


def _compare_formula(table: FrameTable, clock: FrameClock) -> list[FrameGridNote]:
    """Compare the CFR formula with the real timestamps it used to stand in for."""
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


def format_clock(ms: float) -> str:
    """H:MM:SS.mmm for log lines."""
    total = int(ms)
    h, rem = divmod(total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{msec:03d}"
