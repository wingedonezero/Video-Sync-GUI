"""Unit tests for vsg_core.subtitles.operations.vobsub_timing.

Fixture pair ``tests/fixtures/vobsub_small.{idx,sub}`` is a small English
VobSub track extracted from Starship Operators (R1 US DVD source 2,
track 4). The .idx has 39 entries; the .sub is 182 KB of MPEG-PS
subtitle data.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vsg_core.subtitles.operations.vobsub_timing import (  # noqa: E402
    _DELAY_LINE_RE,
    _ms_to_idx_timestamp,
    apply_constant_shift,
    extract_stop_display_delay_ms,
    infer_end_times,
    parse_idx,
)

FIXTURE_IDX = PROJECT_ROOT / "tests" / "fixtures" / "vobsub_small.idx"
FIXTURE_SUB = PROJECT_ROOT / "tests" / "fixtures" / "vobsub_small.sub"

FPS_NTSC_VIDEO = 30000.0 / 1001.0  # 29.97, the actual DVD fps


def test_ms_to_idx_timestamp_round_trip() -> None:
    """Format integer ms back to the HH:MM:SS:MMM form mkvmerge expects."""
    assert _ms_to_idx_timestamp(0) == "00:00:00:000"
    assert _ms_to_idx_timestamp(1) == "00:00:00:001"
    assert _ms_to_idx_timestamp(1234) == "00:00:01:234"
    assert _ms_to_idx_timestamp(60_000) == "00:01:00:000"
    assert _ms_to_idx_timestamp(3_600_000) == "01:00:00:000"


def test_parse_idx_finds_all_entries() -> None:
    """Starship small track has 39 timestamp entries — verify count and order."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    entries = parse_idx(text)
    assert len(entries) == 39
    # First entry's known values from earlier empirical inspection.
    assert entries[0].timestamp_ms == 17184  # 00:00:17:184
    assert entries[0].filepos == 0x000000000
    # Sorted by file order.
    for i in range(1, len(entries)):
        assert entries[i].line_start > entries[i - 1].line_start


def test_parse_idx_preserves_header_byte_offsets() -> None:
    """Line offsets must point at valid 'timestamp:' line starts."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    entries = parse_idx(text)
    for ent in entries:
        # The text between line_start and line_end is the original line.
        line = text[ent.line_start : ent.line_end]
        assert line.lstrip().startswith("timestamp:")


def test_apply_constant_shift_zero_idx_unchanged_except_filepos_format() -> None:
    """A zero shift must produce equivalent .idx content (timestamp
    values unchanged, filepos hex re-normalized to 9-digit lowercase)."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    new_text, res = apply_constant_shift(text, None, 0.0)
    assert res.applied_delay_ms == 0
    assert res.entries_total == 39
    assert res.entries_shifted == 39
    assert res.entries_dropped == 0
    # Every timestamp value preserved.
    src_entries = parse_idx(text)
    out_entries = parse_idx(new_text)
    assert len(src_entries) == len(out_entries)
    for s, o in zip(src_entries, out_entries):
        assert s.timestamp_ms == o.timestamp_ms
        assert s.filepos == o.filepos


def test_apply_constant_shift_negative_uniform() -> None:
    """The actual Starship Operators delay (-6 ms) should shift every
    entry by exactly -6 ms."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    new_text, res = apply_constant_shift(text, None, -5.674)
    # Float -5.674 rounds to int -6 ms (mkvmerge's behavior).
    assert res.applied_delay_ms == -6
    assert res.entries_dropped == 0
    src_entries = parse_idx(text)
    out_entries = parse_idx(new_text)
    for s, o in zip(src_entries, out_entries):
        assert o.timestamp_ms == s.timestamp_ms - 6


def test_apply_constant_shift_drops_negative() -> None:
    """A shift large enough to push the first entry below zero must
    drop that entry."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    # First entry is at 17184 ms; -20000 ms pushes it to -2816 ms.
    new_text, res = apply_constant_shift(text, None, -20000.0)
    assert res.applied_delay_ms == -20000
    assert res.entries_dropped >= 1
    out_entries = parse_idx(new_text)
    for ent in out_entries:
        assert ent.timestamp_ms >= 0


def test_extract_stop_display_delay_present() -> None:
    """First Starship subtitle has a stop-display command in its SPU
    — verify duration is reasonable (a few seconds, not 0 or absurd)."""
    sub = FIXTURE_SUB.read_bytes()
    entries = parse_idx(FIXTURE_IDX.read_text(encoding="latin-1"))
    end_ms, sources = infer_end_times(entries, sub)
    # At least the first entry should have an SPU-derived end.
    spu_sources = sum(1 for s in sources.values() if s == "spu")
    assert spu_sources > 0, "expected at least one SPU stop-display to be parsed"
    # Durations should be plausible (200 ms to 8000 ms typical).
    for ent in entries:
        dur = end_ms[ent.index] - ent.timestamp_ms
        assert 0 < dur < 30_000, f"entry {ent.index} duration {dur} ms out of range"


def test_audit_runs_on_29_97_fps() -> None:
    """With target_fps=29.97 and a -6 ms shift, the frame audit must
    populate Tier 2 results."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    sub = FIXTURE_SUB.read_bytes()
    _, res = apply_constant_shift(
        text,
        sub,
        -5.674,
        target_fps=FPS_NTSC_VIDEO,
        frame_alignment_audit=True,
    )
    assert res.tier2 is not None
    t2 = res.tier2
    assert t2.starts_total == 39
    # Drift can happen on 29.97 with -6 ms shift (it's non-integer-frame);
    # we just check the audit reports something coherent.
    assert t2.starts_on_target + t2.starts_drifted == t2.starts_total
    assert t2.ends_on_target + t2.ends_drifted == t2.ends_total


def test_delay_lines_stripped_from_output() -> None:
    """If the input .idx has a 'delay:' directive, it must be stripped."""
    src = FIXTURE_IDX.read_text(encoding="latin-1")
    # Inject a delay line right after the first timestamp.
    injected = src.replace(
        "timestamp: 00:00:17:184",
        "delay: 00:00:01:000\ntimestamp: 00:00:17:184",
        1,
    )
    assert _DELAY_LINE_RE.search(injected) is not None
    out, res = apply_constant_shift(injected, None, 0.0)
    assert _DELAY_LINE_RE.search(out) is None
    assert res.delay_lines_stripped == 1


def test_audit_off_byte_equivalent_to_audit_on() -> None:
    """Audit must never change a single byte of the output .idx."""
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    out_noaudit, _ = apply_constant_shift(text, None, -6.0)
    out_audited, _ = apply_constant_shift(
        text,
        FIXTURE_SUB.read_bytes(),
        -6.0,
        target_fps=FPS_NTSC_VIDEO,
        frame_alignment_audit=True,
    )
    assert out_noaudit == out_audited


def test_extract_stop_display_handles_malformed_input() -> None:
    """Empty or too-short SPU bytes return 0 without raising."""
    assert extract_stop_display_delay_ms(b"") == 0
    assert extract_stop_display_delay_ms(b"\x00\x01") == 0
    # Header that points DCSQT past EOF.
    assert extract_stop_display_delay_ms(b"\x00\x10\xff\xff" + b"\x00" * 4) == 0
