"""
VobSub (.idx + .sub) timing-only parser and shifter.

Operates exclusively on the ``.idx`` text file. The ``.sub`` binary is
read only for end-time inference (used by Tier 2 audit, never
modified). All output bytes that mkvmerge consumes come from the
``.idx`` text — mkvmerge re-derives the ``.sub`` PES PTSes from those
``.idx`` timestamps when muxing.

The shifter applies a constant integer-ms delta to every
``timestamp:`` line in the ``.idx``. This matches mkvmerge
``--sync 0:<ms>`` byte-for-byte on VobSub tracks (precision floor is
the ``.idx`` text format's ms quantum).

Tier 2 frame-alignment audit is read-only: it reports whether each
event lands on its expected ``F_src + frame_shift`` after the uniform
shift, but never rewrites a byte. End times for the audit come from
the SPU's stop-display (0x02) command in the ``.sub`` (preferred), or
fall back to the next entry's start minus a gap, or a default
duration for the last entry. None of these end-time inputs are
written anywhere — they're audit-only.

VobSub format notes:
* ``.idx`` is text, line-oriented. Header lines (palette, size,
  langidx, id, etc.) are preserved verbatim. Only ``timestamp:`` lines
  are mutated.
* Each ``timestamp:`` line is ``HH:MM:SS:MMM`` (integer ms).
* ``.sub`` is MPEG-PS with subtitle data in private_stream_1 (0xBD).
* Each Sub-Picture Unit (SPU) has its own DCSQT script. We only need
  the stop-display delay for audit's end-time inference.

We deliberately do NOT touch the ``.sub`` file. mkvmerge will rewrite
its PES PTSes automatically based on our shifted ``.idx`` — verified
empirically.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .bitmap_audit import (
    EndpointAudit,
    Tier2FrameAlignmentResult,
    frame_of,
    pick_integer_ms_in_frame,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Fallback end-time bounds (only used when SPU has no stop-display).
# Matches the OCR parser's defaults so audit numbers line up with what
# the OCR pipeline would have inferred.
MIN_GAP_MS = 24
DEFAULT_LAST_DURATION_MS = 3000

# Regex matching one ``timestamp: HH:MM:SS:MMM, filepos: ABCDEF`` line.
_TIMESTAMP_RE = re.compile(
    r"^(\s*timestamp:\s*)(\d+):(\d+):(\d+):(\d+)(\s*,\s*filepos:\s*)([0-9a-fA-F]+)(.*)$",
    re.MULTILINE,
)
# ``delay:`` lines (rare; cumulative offset directive). Stripped by the
# shifter because we already produce absolute shifted timestamps and
# don't want mkvmerge double-applying.
_DELAY_LINE_RE = re.compile(r"^\s*delay:\s*[-+]?\d+:\d+:\d+:\d+\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class IdxEntry:
    """One parsed ``.idx`` ``timestamp:`` line.

    ``timestamp_ms`` is the integer ms encoded by HH:MM:SS:MMM.
    ``line_start`` / ``line_end`` are byte offsets in the original
    ``.idx`` text so the rewriter can splice in the shifted timestamp
    while preserving every other byte (comments, whitespace, header).
    """

    index: int
    timestamp_ms: int
    filepos: int
    line_start: int  # byte offset of start of this line in idx_text
    line_end: int  # byte offset of end (exclusive)


@dataclass(frozen=True, slots=True)
class VobSubShiftResult:
    """Outcome of ``apply_constant_shift``."""

    entries_total: int
    entries_shifted: int
    entries_dropped: int  # would-be-negative entries removed
    delay_lines_stripped: int  # legacy ``delay:`` directives removed
    requested_delay_ms: float
    applied_delay_ms: int
    earliest_timestamp_ms: int  # pre-shift, 0 if no entries
    latest_timestamp_ms: int  # pre-shift, 0 if no entries
    tier2: Tier2FrameAlignmentResult | None = None
    # End-time inference tags per entry index: "spu" / "next_idx" / "default".
    end_time_sources: dict[int, str] = field(default_factory=dict)


def _ms_to_idx_timestamp(ms: int) -> str:
    """Format integer ms as the .idx ``HH:MM:SS:MMM`` text form."""
    if ms < 0:
        raise ValueError(f"Cannot format negative ms ({ms}) as .idx timestamp")
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, msec = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{msec:03d}"


def parse_idx(idx_text: str) -> list[IdxEntry]:
    """Walk the .idx text and return one IdxEntry per ``timestamp:`` line.

    Entries are returned in file order. Header / metadata / language-id
    lines are not surfaced — the rewriter preserves them by virtue of
    only touching the byte ranges of timestamp lines.
    """
    entries: list[IdxEntry] = []
    for idx, m in enumerate(_TIMESTAMP_RE.finditer(idx_text)):
        h = int(m.group(2))
        mi = int(m.group(3))
        s = int(m.group(4))
        ms = int(m.group(5))
        timestamp_ms = h * 3_600_000 + mi * 60_000 + s * 1_000 + ms
        filepos = int(m.group(7), 16)
        entries.append(
            IdxEntry(
                index=idx,
                timestamp_ms=timestamp_ms,
                filepos=filepos,
                line_start=m.start(),
                line_end=m.end(),
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Minimal SPU stop-display extraction (for audit end-time inference only)
# ---------------------------------------------------------------------------


def _read_spu_bytes_at(
    sub_data: bytes, filepos: int, max_read: int = 65536 * 10
) -> bytes:
    """Walk MPEG-PS packets starting at ``filepos`` and accumulate the
    subtitle payload bytes (private_stream_1 substream 0x20-0x3F).

    Returns the concatenated SPU bytes (starts with the 2-byte
    SPU-total-size field). Empty bytes if the location doesn't parse
    as a valid PES packet.
    """
    out = bytearray()
    pos = filepos
    read = 0
    n = len(sub_data)
    while read < max_read and pos + 4 <= n:
        start = sub_data[pos : pos + 4]
        if start == b"\x00\x00\x01\xba":
            # Pack header — 14 bytes total, plus stuffing in last byte
            # of pack header.
            if pos + 14 > n:
                break
            stuffing = sub_data[pos + 13] & 0x07
            pos += 14 + stuffing
            read += 14 + stuffing
            continue
        if start[:3] != b"\x00\x00\x01":
            break
        stream_id = start[3]
        if pos + 6 > n:
            break
        packet_length = struct.unpack(">H", sub_data[pos + 4 : pos + 6])[0]
        if packet_length == 0:
            break
        packet_data_start = pos + 6
        packet_data_end = packet_data_start + packet_length
        if packet_data_end > n:
            break
        packet_data = sub_data[packet_data_start:packet_data_end]
        pos = packet_data_end
        read += 6 + packet_length
        if stream_id == 0xB9:
            break
        if stream_id != 0xBD or len(packet_data) < 3:
            continue
        pes_header_data_length = packet_data[2]
        payload_start = 3 + pes_header_data_length
        if payload_start >= len(packet_data):
            continue
        substream_id = packet_data[payload_start]
        if not (0x20 <= substream_id <= 0x3F):
            continue
        out.extend(packet_data[payload_start + 1 :])
        # Stop once we have the whole SPU.
        if len(out) >= 2:
            spu_size = struct.unpack(">H", bytes(out[:2]))[0]
            if len(out) >= spu_size:
                break
    return bytes(out)


def extract_stop_display_delay_ms(spu_bytes: bytes) -> int:
    """Walk the SPU's DCSQT looking for command 0x02 (stop display).

    Returns the delay in milliseconds: ``(dcsq_delay_ticks * 1024) /
    90``, where ``dcsq_delay_ticks`` is the 2-byte field at the start
    of the DCSQ that contained the stop-display command.

    Returns 0 if no stop-display command is found, or if the SPU is
    malformed.
    """
    if len(spu_bytes) < 4:
        return 0
    dcsqt_offset = struct.unpack(">H", spu_bytes[2:4])[0]
    if dcsqt_offset >= len(spu_bytes):
        return 0

    pos = dcsqt_offset
    seen_offsets: set[int] = set()
    while pos + 4 <= len(spu_bytes):
        if pos in seen_offsets:
            # Self-referencing terminator — final DCSQ. Stop.
            break
        seen_offsets.add(pos)
        delay_ticks = struct.unpack(">H", spu_bytes[pos : pos + 2])[0]
        next_offset = struct.unpack(">H", spu_bytes[pos + 2 : pos + 4])[0]
        cmd_pos = pos + 4
        # Walk commands until 0xFF terminator
        while cmd_pos < len(spu_bytes):
            cmd = spu_bytes[cmd_pos]
            cmd_pos += 1
            if cmd == 0xFF:
                break
            if cmd in (0x00, 0x01):
                continue  # forced / start display — no operand
            if cmd == 0x02:
                # Stop display — the DCSQ's delay is the duration.
                return int((delay_ticks * 1024) / 90)
            if cmd in (0x03, 0x04):
                cmd_pos += 2
            elif cmd == 0x05:
                cmd_pos += 6
            elif cmd == 0x06:
                cmd_pos += 4
            elif cmd == 0x07:
                # Change color & contrast — variable-length, has a
                # 2-byte length prefix.
                if cmd_pos + 2 > len(spu_bytes):
                    break
                hli_len = struct.unpack(">H", spu_bytes[cmd_pos : cmd_pos + 2])[0]
                cmd_pos += hli_len
            else:
                # Unknown command; bail on this DCSQ.
                break
        if next_offset <= pos:
            # Last DCSQ either points to itself or backwards — done.
            break
        pos = next_offset
    return 0


def infer_end_times(
    entries: list[IdxEntry],
    sub_data: bytes | None,
) -> tuple[dict[int, int], dict[int, str]]:
    """Compute per-entry end_ms (and source tag).

    Tier A: SPU stop-display delta (preferred — actual binary-encoded
    duration).
    Tier B: next entry's start minus ``MIN_GAP_MS`` (fallback for
    encoders that didn't write stop-display).
    Tier C: ``DEFAULT_LAST_DURATION_MS`` for the trailing entry.

    Returns ``({entry_index: end_ms}, {entry_index: source_tag})``.
    ``source_tag`` is one of ``"spu"``, ``"next_idx"``, ``"default"``.
    """
    end_ms: dict[int, int] = {}
    source: dict[int, str] = {}
    for i, ent in enumerate(entries):
        spu_dur = 0
        if sub_data is not None:
            try:
                spu = _read_spu_bytes_at(sub_data, ent.filepos)
                if spu:
                    spu_dur = extract_stop_display_delay_ms(spu)
            except Exception:
                spu_dur = 0
        if spu_dur > 0:
            end_ms[ent.index] = ent.timestamp_ms + spu_dur
            source[ent.index] = "spu"
        elif i + 1 < len(entries):
            end_ms[ent.index] = entries[i + 1].timestamp_ms - MIN_GAP_MS
            source[ent.index] = "next_idx"
        else:
            end_ms[ent.index] = ent.timestamp_ms + DEFAULT_LAST_DURATION_MS
            source[ent.index] = "default"
    return end_ms, source


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def apply_constant_shift(
    idx_text: str,
    sub_data: bytes | None,
    delay_ms: float,
    *,
    target_fps: float | None = None,
    frame_alignment_audit: bool = False,
    drop_negative: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[str, VobSubShiftResult]:
    """Rewrite every ``.idx`` ``timestamp:`` line by ``round(delay_ms)`` ms.

    The shift is always uniform: every entry's timestamp moves by the
    same integer-ms delta. Output ``.idx`` text is what mkvmerge would
    produce given ``--sync 0:<ms>`` on the original ``.idx``. The
    ``.sub`` file is NOT touched by this module — mkvmerge re-derives
    its PES PTSes from our shifted ``.idx`` at mux time.

    Parameters
    ----------
    idx_text
        Original ``.idx`` text (UTF-8 / latin-1 — see encoding policy
        below).
    sub_data
        Raw ``.sub`` bytes (only read for audit end-time inference).
        Pass ``None`` to skip SPU end-time extraction; the audit will
        fall back to next-idx / default-duration heuristics for end
        times.
    delay_ms
        Requested shift in milliseconds (float accepted; rounded to int
        ms to match mkvmerge precision and ``.idx`` text format).
    target_fps
        Target video frame rate. Required together with
        ``frame_alignment_audit=True`` for the Tier 2 audit.
    frame_alignment_audit
        Enable Tier 2 frame-alignment reporting (read-only).
    drop_negative
        When ``True`` (default), drop any entry whose timestamp would
        go below zero after the shift. ``False`` clamps to zero (legal
        in ``.idx`` text, but produces bunched events).
    log
        Optional log callback.

    Returns
    -------
    ``(new_idx_text, VobSubShiftResult)``.
    """

    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    entries = parse_idx(idx_text)
    if not entries:
        return idx_text, VobSubShiftResult(
            entries_total=0,
            entries_shifted=0,
            entries_dropped=0,
            delay_lines_stripped=0,
            requested_delay_ms=delay_ms,
            applied_delay_ms=0,
            earliest_timestamp_ms=0,
            latest_timestamp_ms=0,
            tier2=None,
        )

    applied_ms = int(round(delay_ms))
    earliest_ts = min(e.timestamp_ms for e in entries)
    latest_ts = max(e.timestamp_ms for e in entries)

    # Identify which entries to drop (would-be-negative).
    dropped_indices: set[int] = set()
    if applied_ms < 0 and drop_negative:
        for ent in entries:
            if ent.timestamp_ms + applied_ms < 0:
                dropped_indices.add(ent.index)
                _log(
                    f"[VobSubTiming] dropping entry @ "
                    f"{ent.timestamp_ms} ms "
                    f"(would shift to {ent.timestamp_ms + applied_ms} ms)"
                )

    # Tier 2 audit (read-only) — runs against pre-shift entries +
    # inferred end times, with shifted PTSes computed on the fly.
    tier2: Tier2FrameAlignmentResult | None = None
    end_times: dict[int, int] = {}
    end_sources: dict[int, str] = {}
    do_frame_audit = bool(frame_alignment_audit and target_fps and target_fps > 0)
    if do_frame_audit:
        end_times, end_sources = infer_end_times(entries, sub_data)
        period_ms = 1000.0 / float(target_fps)  # type: ignore[arg-type]
        frame_shift = round(applied_ms / period_ms)

        endpoint_audits: list[EndpointAudit] = []
        starts_total = 0
        starts_on_target = 0
        ends_total = 0
        ends_on_target = 0
        max_start_drift_ms = 0
        max_end_drift_ms = 0

        for ent in entries:
            if ent.index in dropped_indices:
                continue
            # Start endpoint
            shifted_start_ms = ent.timestamp_ms + applied_ms
            f_src = frame_of(float(ent.timestamp_ms), period_ms)
            f_target = f_src + frame_shift
            f_actual = frame_of(float(shifted_start_ms), period_ms)
            on_target = f_actual == f_target
            would_corr = 0
            if not on_target:
                new_int_ms = pick_integer_ms_in_frame(
                    float(shifted_start_ms), f_target, period_ms
                )
                if new_int_ms is not None:
                    would_corr = new_int_ms - shifted_start_ms
            endpoint_audits.append(
                EndpointAudit(
                    event_index=ent.index,
                    role="start",
                    source_ms=float(ent.timestamp_ms),
                    shifted_ms=float(shifted_start_ms),
                    source_frame=f_src,
                    target_frame=f_target,
                    actual_frame=f_actual,
                    on_target=on_target,
                    would_be_correction_ms=would_corr,
                )
            )
            starts_total += 1
            if on_target:
                starts_on_target += 1
            else:
                max_start_drift_ms = max(max_start_drift_ms, abs(would_corr))

            # End endpoint (inferred from SPU/next/default).
            src_end_ms = end_times.get(ent.index)
            if src_end_ms is None:
                continue
            shifted_end_ms = src_end_ms + applied_ms
            f_src_e = frame_of(float(src_end_ms), period_ms)
            f_target_e = f_src_e + frame_shift
            f_actual_e = frame_of(float(shifted_end_ms), period_ms)
            on_target_e = f_actual_e == f_target_e
            would_corr_e = 0
            if not on_target_e:
                new_int_ms_e = pick_integer_ms_in_frame(
                    float(shifted_end_ms), f_target_e, period_ms
                )
                if new_int_ms_e is not None:
                    would_corr_e = new_int_ms_e - shifted_end_ms
            endpoint_audits.append(
                EndpointAudit(
                    event_index=ent.index,
                    role="end",
                    source_ms=float(src_end_ms),
                    shifted_ms=float(shifted_end_ms),
                    source_frame=f_src_e,
                    target_frame=f_target_e,
                    actual_frame=f_actual_e,
                    on_target=on_target_e,
                    would_be_correction_ms=would_corr_e,
                )
            )
            ends_total += 1
            if on_target_e:
                ends_on_target += 1
            else:
                max_end_drift_ms = max(max_end_drift_ms, abs(would_corr_e))

        tier2 = Tier2FrameAlignmentResult(
            target_fps=float(target_fps),  # type: ignore[arg-type]
            frame_period_ms=period_ms,
            frame_shift=frame_shift,
            starts_total=starts_total,
            starts_on_target=starts_on_target,
            ends_total=ends_total,
            ends_on_target=ends_on_target,
            starts_drifted=starts_total - starts_on_target,
            ends_drifted=ends_total - ends_on_target,
            max_start_drift_ms=max_start_drift_ms,
            max_end_drift_ms=max_end_drift_ms,
            endpoints=tuple(endpoint_audits),
        )

    # ----- Rewrite .idx text -----
    out_parts: list[str] = []
    cursor = 0
    entries_shifted = 0
    for ent in entries:
        # Copy bytes between previous cursor and this line as-is.
        out_parts.append(idx_text[cursor : ent.line_start])
        cursor = ent.line_end
        if ent.index in dropped_indices:
            # Skip this line entirely. Preserve a trailing newline if
            # the next char is one (otherwise the file would lose its
            # line break).
            if cursor < len(idx_text) and idx_text[cursor] == "\n":
                cursor += 1
            continue
        new_ts_ms = max(ent.timestamp_ms + applied_ms, 0)
        new_ts_text = _ms_to_idx_timestamp(new_ts_ms)
        new_filepos_text = f"{ent.filepos:09x}"
        new_line = f"timestamp: {new_ts_text}, filepos: {new_filepos_text}"
        out_parts.append(new_line)
        entries_shifted += 1
    # Tail after last entry.
    out_parts.append(idx_text[cursor:])
    new_idx_text = "".join(out_parts)

    # Strip any pre-existing ``delay:`` directives — our shifted
    # timestamps are already absolute, and mkvmerge would
    # double-apply these.
    delay_lines_stripped = 0
    if _DELAY_LINE_RE.search(new_idx_text):
        new_idx_text, delay_lines_stripped = _DELAY_LINE_RE.subn("", new_idx_text)
        # Also collapse the empty line that's left behind by the
        # subn replacement, if it created one.
        new_idx_text = re.sub(r"\n\n+", "\n\n", new_idx_text)
        _log(
            f"[VobSubTiming] stripped {delay_lines_stripped} pre-existing "
            "'delay:' directive(s) (we produce absolute shifted timestamps)"
        )

    result = VobSubShiftResult(
        entries_total=len(entries),
        entries_shifted=entries_shifted,
        entries_dropped=len(dropped_indices),
        delay_lines_stripped=delay_lines_stripped,
        requested_delay_ms=delay_ms,
        applied_delay_ms=applied_ms,
        earliest_timestamp_ms=earliest_ts,
        latest_timestamp_ms=latest_ts,
        tier2=tier2,
        end_time_sources=end_sources,
    )

    _log(
        f"[VobSubTiming] shifted {entries_shifted}/{len(entries)} entries by "
        f"{applied_ms:+d} ms (requested {delay_ms:+.3f} ms), "
        f"dropped {len(dropped_indices)} entry(s)"
    )
    if tier2 is not None:
        drift_total = tier2.starts_drifted + tier2.ends_drifted
        spu_count = sum(1 for s in end_sources.values() if s == "spu")
        next_count = sum(1 for s in end_sources.values() if s == "next_idx")
        default_count = sum(1 for s in end_sources.values() if s == "default")
        _log(
            f"[VobSubTiming] frame audit ({tier2.target_fps:.3f} fps, "
            f"frame_shift {tier2.frame_shift:+d}): "
            f"{tier2.starts_on_target}/{tier2.starts_total} starts on target, "
            f"{tier2.ends_on_target}/{tier2.ends_total} ends on target"
            + (
                f" — {drift_total} drifted (max start ±{tier2.max_start_drift_ms} ms, "
                f"max end ±{tier2.max_end_drift_ms} ms)"
                if drift_total > 0
                else ""
            )
        )
        _log(
            f"[VobSubTiming] end-time sources: spu={spu_count}, "
            f"next_idx={next_count}, default={default_count}"
        )

    return new_idx_text, result
