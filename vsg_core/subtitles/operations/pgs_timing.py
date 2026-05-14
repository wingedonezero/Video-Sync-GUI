"""
PGS (.sup) timing-only parser and shifter.

Operates on PGS subtitle files at the segment-header level only — no
bitmap decoding, palette parsing, or RLE work. The parser produces
two views:

* ``walk_segments`` returns one record per segment with its byte
  range, PTS / DTS ticks, and type.
* ``extract_events`` pairs each "display" PCS with the next
  non-palette-update PCS to produce ``(start_pts_ticks, end_pts_ticks)``
  windows, suitable for the bitmap timing auditor.

``apply_constant_shift`` rewrites every segment's PTS (and DTS when
non-zero) by a single rounded-millisecond delay and returns the new
bytes. This matches what mkvmerge does internally when given
``--sync 0:<ms>`` on a PGS track, but lets the pipeline keep
ownership of the shift so we can:

* Drop entire display events whose start would go negative (instead of
  letting mkvmerge clamp / bunch silently).
* Audit every event start/end against the target video's frame grid.
* Pass the shifted file to mkvmerge with ``--sync 0`` for a passthrough.

PGS segment header (13 bytes):
    0-1   "PG" magic
    2-5   PTS  (big-endian uint32, 90 kHz)
    6-9   DTS  (big-endian uint32, 90 kHz; typically 0)
    10    segment type
    11-12 payload length (big-endian uint16)
    13+   payload

PCS payload bytes used for event classification:
    8     palette_update_flag (0x80 bit set = palette update only)
    10    number of composition objects (0 = "clear", >0 = "display")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Segment types
SEG_PDS = 0x14
SEG_ODS = 0x15
SEG_PCS = 0x16
SEG_WDS = 0x17
SEG_END = 0x80

PG_MAGIC = b"PG"
HEADER_SIZE = 13
PTS_CLOCK_HZ = 90_000


@dataclass(frozen=True, slots=True)
class PgsSegment:
    """One PGS segment located in a .sup buffer."""

    index: int  # 0-based segment number
    header_offset: int  # byte offset of "PG" magic
    payload_offset: int  # header_offset + 13
    end_offset: int  # payload_offset + payload_length
    pts_ticks: int  # 90 kHz
    dts_ticks: int  # 90 kHz; 0 for typical files
    seg_type: int  # SEG_PCS / SEG_WDS / SEG_PDS / SEG_ODS / SEG_END
    payload_length: int


@dataclass(frozen=True, slots=True)
class PgsDisplayEvent:
    """A single visible-subtitle window between two PCS boundaries.

    ``end_pts_ticks`` is ``None`` for an open-ended trailing display
    (no clearing PCS before EOF).
    """

    start_pts_ticks: int
    end_pts_ticks: int | None
    start_segment_index: int
    end_segment_index: int  # last segment index belonging to this event
    composition_object_count: int


@dataclass(frozen=True, slots=True)
class PgsShiftResult:
    """Outcome of ``apply_constant_shift``."""

    segments_scanned: int
    segments_shifted: int
    segments_dropped: int
    events_dropped: int
    requested_delay_ms: float
    applied_delay_ms: int
    delta_ticks: int
    invalid_segments: int  # PG-magic resyncs encountered
    earliest_pts_ms: float  # pre-shift
    latest_pts_ms: float  # pre-shift


def walk_segments(data: bytes | bytearray) -> tuple[list[PgsSegment], int]:
    """Walk a .sup buffer and return ``(segments, invalid_resyncs)``.

    Resyncs on a missing PG magic (counted in ``invalid_resyncs``).
    Stops cleanly at EOF or when no further magic is found.
    """
    segments: list[PgsSegment] = []
    invalid = 0
    pos = 0
    n = len(data)
    while pos + HEADER_SIZE <= n:
        if bytes(data[pos : pos + 2]) != PG_MAGIC:
            nxt = bytes(data).find(PG_MAGIC, pos + 1)
            if nxt < 0:
                invalid += 1
                break
            invalid += 1
            pos = nxt
            continue
        pts = int.from_bytes(data[pos + 2 : pos + 6], "big")
        dts = int.from_bytes(data[pos + 6 : pos + 10], "big")
        seg_type = data[pos + 10]
        seg_len = int.from_bytes(data[pos + 11 : pos + 13], "big")
        payload_offset = pos + HEADER_SIZE
        end_offset = payload_offset + seg_len
        if end_offset > n:
            # Truncated final segment; stop.
            break
        segments.append(
            PgsSegment(
                index=len(segments),
                header_offset=pos,
                payload_offset=payload_offset,
                end_offset=end_offset,
                pts_ticks=pts,
                dts_ticks=dts,
                seg_type=seg_type,
                payload_length=seg_len,
            )
        )
        pos = end_offset
    return segments, invalid


def _read_pcs_classification(
    data: bytes | bytearray, seg: PgsSegment
) -> tuple[bool, int]:
    """Return ``(is_palette_update_only, composition_object_count)`` for a PCS.

    Returns ``(False, 0)`` if the payload is too short to classify.
    """
    if seg.payload_length < 11:
        return False, 0
    flag_byte = data[seg.payload_offset + 8]
    obj_count = data[seg.payload_offset + 10]
    is_palette_update = (flag_byte & 0x80) != 0
    return is_palette_update, obj_count


def extract_events(
    segments: list[PgsSegment], data: bytes | bytearray
) -> list[PgsDisplayEvent]:
    """Pair display PCS segments with their terminating PCS.

    A display event starts at a PCS whose ``composition_object_count > 0``
    and ends at the next PCS whose ``palette_update_flag`` is NOT set
    (palette-update PCSes change colors mid-display and are not event
    boundaries). The terminating PCS may itself be a clear (count == 0)
    or the start of a new display (count > 0); either way, the prior
    display ends at its PTS.

    Each event's ``end_segment_index`` is the index of the last segment
    belonging to that event in the .sup byte stream (typically an END
    segment carrying the same PTS).
    """
    events: list[PgsDisplayEvent] = []
    current_start_pts: int | None = None
    current_start_idx: int | None = None
    current_obj_count = 0
    last_seg_in_event: int | None = None

    for i, seg in enumerate(segments):
        if seg.seg_type != SEG_PCS:
            last_seg_in_event = i
            continue
        is_palette_update, obj_count = _read_pcs_classification(data, seg)
        if is_palette_update:
            # Mid-display palette swap; shift along but not an event boundary.
            last_seg_in_event = i
            continue
        # This PCS closes any in-progress display event.
        if current_start_pts is not None and current_start_idx is not None:
            events.append(
                PgsDisplayEvent(
                    start_pts_ticks=current_start_pts,
                    end_pts_ticks=seg.pts_ticks,
                    start_segment_index=current_start_idx,
                    end_segment_index=last_seg_in_event
                    if last_seg_in_event is not None
                    else current_start_idx,
                    composition_object_count=current_obj_count,
                )
            )
            current_start_pts = None
            current_start_idx = None
            current_obj_count = 0
        # If this PCS opens a new display, remember it.
        if obj_count > 0:
            current_start_pts = seg.pts_ticks
            current_start_idx = i
            current_obj_count = obj_count
        last_seg_in_event = i

    # Trailing open-ended display (no closing PCS before EOF).
    if current_start_pts is not None and current_start_idx is not None:
        events.append(
            PgsDisplayEvent(
                start_pts_ticks=current_start_pts,
                end_pts_ticks=None,
                start_segment_index=current_start_idx,
                end_segment_index=last_seg_in_event
                if last_seg_in_event is not None
                else current_start_idx,
                composition_object_count=current_obj_count,
            )
        )

    return events


def apply_constant_shift(
    data: bytes | bytearray,
    delay_ms: float,
    *,
    drop_negative: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[bytes, PgsShiftResult]:
    """Rewrite every segment's PTS by ``round(delay_ms)`` ms.

    Parameters
    ----------
    data
        Raw .sup buffer.
    delay_ms
        Requested shift in milliseconds (float accepted; rounded to int
        ms to match mkvmerge's --sync precision and Matroska's default
        1 ms timestamp scale).
    drop_negative
        When ``True`` (default), drop any display event whose start_pts
        would go below zero after the shift. ``False`` clamps to zero
        (legacy behavior; not recommended — produces overlapping events
        bunched at t=0).
    log
        Optional log callback.

    Returns
    -------
    ``(new_data, result)`` where ``new_data`` is a fresh bytes object
    with PTS / DTS fields rewritten in place (and dropped segments
    omitted) and ``result`` carries the shift statistics.
    """

    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    segments, invalid = walk_segments(data)
    if not segments:
        return bytes(data), PgsShiftResult(
            segments_scanned=0,
            segments_shifted=0,
            segments_dropped=0,
            events_dropped=0,
            requested_delay_ms=delay_ms,
            applied_delay_ms=0,
            delta_ticks=0,
            invalid_segments=invalid,
            earliest_pts_ms=0.0,
            latest_pts_ms=0.0,
        )

    applied_ms = int(round(delay_ms))
    delta_ticks = applied_ms * (PTS_CLOCK_HZ // 1000)  # 90 ticks per ms

    earliest_pts = min(s.pts_ticks for s in segments)
    latest_pts = max(s.pts_ticks for s in segments)

    # Identify segment indices to drop (events whose start_pts goes negative).
    dropped_segments: set[int] = set()
    events_dropped = 0
    if delta_ticks < 0:
        events = extract_events(segments, data)
        for ev in events:
            if ev.start_pts_ticks + delta_ticks < 0:
                if drop_negative:
                    for i in range(ev.start_segment_index, ev.end_segment_index + 1):
                        dropped_segments.add(i)
                    events_dropped += 1
                    _log(
                        f"[PGSTiming] dropping event @ "
                        f"{ev.start_pts_ticks / 90.0:.3f} ms "
                        f"(would shift to {(ev.start_pts_ticks + delta_ticks) / 90.0:.3f} ms)"
                    )
        # Any segments OUTSIDE event boundaries (rare — typically only the
        # leading PCS clear before the first display event) we leave in
        # place; their PTS will be clamped to 0 below.

    out = bytearray()
    shifted = 0
    for seg in segments:
        if seg.index in dropped_segments:
            continue
        seg_bytes = bytearray(data[seg.header_offset : seg.end_offset])
        # Clamp to zero for orphan segments outside display events (e.g.,
        # a leading clear PCS at t=0). Display-event segments going
        # negative were already filtered into ``dropped_segments`` above.
        new_pts = max(seg.pts_ticks + delta_ticks, 0)
        seg_bytes[2:6] = new_pts.to_bytes(4, "big")
        if seg.dts_ticks > 0:
            new_dts = max(seg.dts_ticks + delta_ticks, 0)
            seg_bytes[6:10] = new_dts.to_bytes(4, "big")
        out.extend(seg_bytes)
        shifted += 1

    result = PgsShiftResult(
        segments_scanned=len(segments),
        segments_shifted=shifted,
        segments_dropped=len(dropped_segments),
        events_dropped=events_dropped,
        requested_delay_ms=delay_ms,
        applied_delay_ms=applied_ms,
        delta_ticks=delta_ticks,
        invalid_segments=invalid,
        earliest_pts_ms=earliest_pts / 90.0,
        latest_pts_ms=latest_pts / 90.0,
    )

    _log(
        f"[PGSTiming] shifted {shifted}/{len(segments)} segments by "
        f"{applied_ms:+d} ms (requested {delay_ms:+.3f} ms), "
        f"dropped {events_dropped} event(s) / {len(dropped_segments)} segment(s), "
        f"invalid {invalid}"
    )

    return bytes(out), result
