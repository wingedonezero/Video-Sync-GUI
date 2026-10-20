# vsg_core/subtitles/frame_utils/frame_table.py
"""
Real frame grid read from the video's own timestamps.

:class:`FrameClock` *computes* where frames should be (``n * 1000 / fps``,
frame 0 at 0 ms). That model is exact for clean Blu-ray remuxes but silently
wrong elsewhere: some encodes report a frame rate that is not their real one
(``2997/100`` on a 23.976 file), start their first frame at 66/83 ms, round
half-milliseconds the other way, carry soft-telecine 33/50 ms frames, or have
holes. MPEG-2 DVDs fail it for the same reasons.

:class:`FrameTable` *reads* where the frames are: the presentation time of
every frame as stored in the container — the same values the player uses to
decide which frame a subtitle appears on. The times come from the ffms2 index,
the same cached index the sliding matcher builds, so both see one timeline.

Both satisfy :class:`FrameGrid`, the only interface surgical rounding and the
frame audit need: "which frame is this time on" and "when does frame N start".
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class FrameGrid(Protocol):
    """A video's frame grid: which frame a time renders on, and frame start times."""

    def frame_of(self, time_ms: float) -> int:
        """Index of the first frame at or after ``time_ms``."""
        ...

    def frame_ms(self, n: int) -> float:
        """Presentation time (ms) of frame ``n``."""
        ...

    @property
    def frame_duration_ms(self) -> float:
        """Nominal frame period — for logging/reporting only, never grid math."""
        ...

    @property
    def label(self) -> str:
        """Short human-readable description for logs and reports."""
        ...


@dataclass(frozen=True, slots=True)
class FrameTable:
    """Exact frame grid from real per-frame presentation timestamps.

    ``times_ms`` is sorted and strictly increasing (presentation order).
    Build it with :meth:`from_timestamps`, which validates the input.
    """

    times_ms: tuple[float, ...]
    nominal_frame_ms: float  # average frame period, for display only
    origin: str  # where the timestamps came from, e.g. "ffms2 index"

    @classmethod
    def from_timestamps(cls, times_ms: Sequence[float], origin: str) -> FrameTable:
        """Validate and build a table from per-frame presentation times (ms).

        Raises:
            ValueError: fewer than two frames, or duplicate timestamps (two
                frames at one instant means the input is not a frame list).
        """
        ordered = tuple(sorted(float(t) for t in times_ms))
        if len(ordered) < 2:
            raise ValueError(f"need at least 2 frame timestamps, got {len(ordered)}")
        intervals = [b - a for a, b in pairwise(ordered)]
        if min(intervals) <= 0:
            dup = intervals.index(min(intervals))
            raise ValueError(
                f"duplicate frame timestamp {ordered[dup]} ms at frame {dup + 1}"
            )
        # Average period over the cadence, ignoring holes: container times are
        # whole ms, so a median would report 33 ms (30.303 fps) for 29.97.
        median = statistics.median(intervals)
        cadence = [p for p in intervals if p <= 2 * median]
        return cls(
            times_ms=ordered,
            nominal_frame_ms=statistics.fmean(cadence),
            origin=origin,
        )

    @property
    def num_frames(self) -> int:
        return len(self.times_ms)

    def frame_of(self, time_ms: float) -> int:
        """Index of the first frame whose presentation time is >= ``time_ms``.

        This is the frame a timestamp renders against: a player shows a subtitle
        on frames at or after its start, and an exclusive end clears on this
        same boundary. Times before the first frame map to frame 0; times after
        the last frame map to ``num_frames`` (the virtual frame after the end).
        """
        return bisect.bisect_left(self.times_ms, time_ms)

    def frame_ms(self, n: int) -> float:
        """Presentation time of frame ``n``.

        Outside the stored frames the grid is extended with the edge frame
        period, so callers asking for a neighbour of the first/last frame get a
        sensible value instead of an exception.
        """
        last = len(self.times_ms) - 1
        if 0 <= n <= last:
            return self.times_ms[n]
        if n > last:
            tail = self.times_ms[last] - self.times_ms[last - 1]
            return self.times_ms[last] + (n - last) * tail
        head = self.times_ms[1] - self.times_ms[0]
        return self.times_ms[0] + n * head

    @property
    def frame_duration_ms(self) -> float:
        return self.nominal_frame_ms

    @property
    def label(self) -> str:
        return (
            f"real timestamps ({self.num_frames} frames, "
            f"~{1000.0 / self.nominal_frame_ms:.3f} fps, {self.origin})"
        )


@dataclass(frozen=True, slots=True)
class FrameShift:
    """An exact whole-frame move from the source's frames to Source 1's.

    A subtitle time sitting exactly on source frame ``k`` (the video it was
    timed on) moves to the time of target frame ``k + frames`` (Source 1) —
    landing dead on the frame showing the same picture, whatever either file's
    start offset or millisecond rounding. Times not on a source frame
    (mid-frame VobSub, native ASS) and frames past either end of a real
    timeline take the flat millisecond delay, exactly as without a frame shift.

    Normally both grids are real timelines (``FrameTable``); the CFR formula
    (``FrameClock``) is the reported fallback when real times are unreadable.
    Built only by ``sync_utils.build_frame_shift``.
    """

    source: FrameGrid
    target: FrameGrid
    frames: int

    def shifted_ms(self, time_ms: float, flat_delay_ms: float) -> float:
        """Exact-snap ``time_ms`` when it is on a source frame, else the flat delay."""
        k = frame_at(self.source, time_ms)
        if k is not None:
            dest = k + self.frames
            if _in_range(self.target, dest):
                return float(self.target.frame_ms(dest))
        return time_ms + flat_delay_ms


def _in_range(grid: FrameGrid, n: int) -> bool:
    """Real timelines end; the CFR formula extends forever (as it always did)."""
    if isinstance(grid, FrameTable):
        return 0 <= n < grid.num_frames
    return True


def frame_at(grid: FrameGrid, time_ms: float) -> int | None:
    """The frame ``time_ms`` sits exactly on, or None when it is mid-frame.

    Subtitle times are stored in whole milliseconds. With whole-ms frame times
    (MKV) a time is on frame k iff it equals that frame's time — the original
    rule, unchanged. Containers can store finer frame times (MP4/M2TS,
    timestamp maps); a whole-ms subtitle time then records the frame's time
    floored or rounded to the millisecond, and is on that frame either way.
    """
    k = grid.frame_of(time_ms)
    if _in_range(grid, k) and grid.frame_ms(k) == round(time_ms):
        return k
    whole_ms = round(time_ms)
    for cand in (k, k - 1):
        if not _in_range(grid, cand):
            continue
        frame_time = grid.frame_ms(cand)
        if frame_time != math.floor(frame_time) and whole_ms in (
            math.floor(frame_time),
            math.floor(frame_time + 0.5),
        ):
            return cand
    return None


# ── Timeline check (gaps / start offset) ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TimelineGap:
    """A jump in the frame timeline longer than any regular frame period."""

    frame: int  # index of the first frame after the gap
    before_ms: float  # presentation time of the frame before the gap
    after_ms: float  # presentation time of the frame after the gap

    @property
    def jump_ms(self) -> float:
        return self.after_ms - self.before_ms


@dataclass(frozen=True, slots=True)
class TimelineCheck:
    """Integrity summary of a frame table's timeline."""

    first_frame_ms: float
    regular_max_ms: float  # longest frame period that is part of the cadence
    gaps: tuple[TimelineGap, ...]


# A frame period counts as part of the cadence when at least this share of all
# periods has it (soft telecine's 50 ms frames, 33/34 ms rounding pairs, ...).
_REGULAR_SHARE = 0.01
# A jump is a gap when it exceeds the longest regular period by this factor:
# one dropped frame doubles the period, soft telecine only reaches 1.5x.
_GAP_FACTOR = 1.75


def check_timeline(table: FrameTable) -> TimelineCheck:
    """Find timeline jumps (holes in the stream) and the first frame's time.

    Gaps are judged against the file's own cadence, never an absolute
    threshold: the longest frame period that makes up >= 1% of the file is
    regular (so soft-telecine 50 ms frames are not gaps), and any jump longer
    than 1.75x that is reported. One missing frame at any rate is caught.
    """
    times = table.times_ms
    periods = [round(b - a) for a, b in pairwise(times)]
    counts = Counter(periods)
    floor_count = max(1, int(len(periods) * _REGULAR_SHARE))
    regular = [p for p, c in counts.items() if c >= floor_count]
    regular_max = float(max(regular)) if regular else table.nominal_frame_ms
    threshold = regular_max * _GAP_FACTOR
    gaps = tuple(
        TimelineGap(frame=i + 1, before_ms=times[i], after_ms=times[i + 1])
        for i in range(len(times) - 1)
        if times[i + 1] - times[i] > threshold
    )
    return TimelineCheck(first_frame_ms=times[0], regular_max_ms=regular_max, gaps=gaps)


@dataclass(frozen=True, slots=True)
class FrameGridNote:
    """A finding about Source 1's frame grid, surfaced in the final audit."""

    severity: Literal["info", "warning"]
    message: str


# ── Building from the ffms2 index ────────────────────────────────────────────


def parse_timecodes_v2(text: str) -> list[float]:
    """Parse a "timecode format v2" file (one presentation time in ms per line).

    Raises:
        ValueError: missing/unknown header or a non-numeric line.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    if not lines or not lines[0].lower().startswith("# timecode format v2"):
        raise ValueError("not a timecode format v2 file")
    times: list[float] = []
    for ln in lines[1:]:
        if not ln or ln.startswith("#"):
            continue
        times.append(float(ln))
    return times


def build_frame_table(
    video_path: str,
    temp_dir: Path | None,
    log: Callable[[str], None],
) -> FrameTable | None:
    """Read ``video_path``'s real frame timestamps from its ffms2 index.

    Reuses the job's cached index (the one the sliding matcher builds) when it
    exists, otherwise indexes the file once (~1 s per GB, disk-bound). Nothing
    is decoded. Returns None — after logging why — when VapourSynth/ffms2 is
    unavailable or the timestamps are unusable; callers then keep the old
    behaviour.
    """
    try:
        import vapoursynth as vs
    except ImportError:
        log("[FrameGrid] VapourSynth not available - cannot read real timestamps")
        return None

    from .video_reader import _get_ffms2_cache_path

    cache_path = _get_ffms2_cache_path(video_path, temp_dir)
    timecodes_path = cache_path.with_suffix(".timecodes.txt")
    core = vs.core
    try:
        try:
            clip = core.ffms2.Source(
                source=video_path,
                cachefile=str(cache_path),
                timecodes=str(timecodes_path),
            )
        except vs.Error:
            # Stale or corrupt index: rebuild once (same policy as the matcher).
            cache_path.unlink(missing_ok=True)
            clip = core.ffms2.Source(
                source=video_path,
                cachefile=str(cache_path),
                timecodes=str(timecodes_path),
            )
        num_frames = clip.num_frames
        del clip
        times = parse_timecodes_v2(Path(timecodes_path).read_text(encoding="utf-8"))
        table = FrameTable.from_timestamps(times, origin="ffms2 index")
    except (vs.Error, OSError, ValueError) as e:
        log(f"[FrameGrid] WARNING: could not read real frame timestamps: {e}")
        return None
    if table.num_frames != num_frames:
        log(
            f"[FrameGrid] WARNING: timestamp count {table.num_frames} != "
            f"{num_frames} frames in the index - not using real timestamps"
        )
        return None
    return table
