# tests/test_passthrough_cuts.py
"""Passthrough cuts: frame parsers on synthetic streams, cut planning (start
entry rule, residual rounding, end trim), the byte / PCM / Opus writers and
their checks, and the dialnorm edit.

Real-media checks (parser == mkvmerge on 448 tracks, dialnorm == mkvmerge
byte for byte, real jobs) live in the Tests harness:
Tests/audio_negative_sync/app_frames_sweep.py, dialnorm_parity.py.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from vsg_core.audio_processing import dialnorm, frames
from vsg_core.audio_processing.ogg_opus import (
    OggOpus,
    opus_packet_samples,
    read_ogg_opus,
    write_ogg_opus,
)
from vsg_core.audio_processing.passthrough import (
    PassthroughError,
    cut_passthrough,
    passthrough_kind,
    plan_frames,
    read_wav_layout,
)

if TYPE_CHECKING:
    from pathlib import Path

MS = 1_000_000

# --- synthetic streams ----------------------------------------------------------------


def _ac3_frame(
    payload_seed: int, acmod: int = 2, dialnorm_level: int = 27
) -> bytearray:
    """A 448 kb/s 48 kHz AC-3 frame (1792 bytes) with valid CRCs."""
    size = 1792
    frame = bytearray(size)
    frame[0:2] = b"\x0b\x77"
    frame[4] = (0 << 6) | 30  # fscod 48 kHz, frmsizecod 30 (448 kb/s = 896 words)
    frame[5] = (8 << 3) | 0  # bsid 8, bsmod 0
    # acmod 2 (stereo): acmod(3) dsurmod(2) lfeon(1) dialnorm(5) compre(1) ...
    value = (acmod << 13) | (dialnorm_level << 5)
    frame[6] = (value >> 8) & 0xFF
    frame[7] = value & 0xFF
    for i in range(8, size - 2):
        frame[i] = (payload_seed * 31 + i * 7) & 0xFF
    frame[size - 3] &= 0xFE
    frame[2:4] = dialnorm.ac3_crc1(frame).to_bytes(2, "big")
    frame[size - 2 : size] = dialnorm.ac3_crc2(frame).to_bytes(2, "big")
    return frame


def _eac3_frame(dependent: bool, seed: int) -> bytes:
    """An E-AC-3 frame of 6 blocks at 48 kHz, 512 bytes."""
    words = 512 // 2 - 1
    frame = bytearray(512)
    frame[0:2] = b"\x0b\x77"
    strmtyp = 1 if dependent else 0
    frame[2] = (strmtyp << 6) | (0 << 3) | ((words >> 8) & 7)
    frame[3] = words & 0xFF
    frame[4] = (
        (0 << 6) | (3 << 4) | (2 << 1) | 0
    )  # fscod 0, numblkscod 3, acmod 2, lfe 0
    frame[5] = 16 << 3  # bsid 16
    for i in range(6, 512):
        frame[i] = (seed + i) & 0xFF
    return bytes(frame)


def _truehd_au(major: bool, seed: int) -> bytes:
    """A TrueHD access unit: 64 bytes, a major sync at 48 kHz when ``major``."""
    size = 64
    au = bytearray(size)
    au[0] = 0xF0 | ((size // 2) >> 8)
    au[1] = (size // 2) & 0xFF
    if major:
        au[4:8] = b"\xf8\x72\x6f\xba"
        au[8] = 0x00  # rate bits 0 -> 48 kHz
    for i in range(10 if major else 4, size):
        au[i] = (seed + i) & 0xFF
    return bytes(au)


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


# --- codec mapping --------------------------------------------------------------------


def test_passthrough_kind() -> None:
    assert passthrough_kind("A_EAC3") == "ac3"
    assert passthrough_kind("A_AC3") == "ac3"
    assert passthrough_kind("A_TRUEHD") == "truehd"
    assert passthrough_kind("A_DTS") == "dts"
    assert passthrough_kind("A_AAC/MPEG4/LC") == "aac"
    assert passthrough_kind("A_MPEG/L3") == "mpa"
    assert passthrough_kind("A_PCM/INT/LIT") == "pcm"
    assert passthrough_kind("A_OPUS") == "opus"
    assert passthrough_kind("A_VORBIS") is None
    assert passthrough_kind("A_PCM/FLOAT/IEEE") is None
    assert passthrough_kind("A_FLAC") is None


# --- parsers --------------------------------------------------------------------------


def test_eac3_dependent_frames_join_their_independent_frame() -> None:
    data = b"".join(
        _eac3_frame(dep, i) for i, dep in enumerate([False, True, False, True, False])
    )
    fmap = frames.parse_buffer("ac3", data)
    assert not fmap.problems
    assert list(fmap.size) == [1024, 1024, 512]
    assert list(fmap.samples) == [1536, 1536, 1536]
    assert all(fmap.entry)


def test_eac3_starting_on_a_dependent_frame_is_not_an_entry() -> None:
    data = _eac3_frame(True, 0) + _eac3_frame(False, 1)
    fmap = frames.parse_buffer("ac3", data)
    assert list(fmap.entry) == [0, 1]


def test_truehd_entry_only_on_major_sync() -> None:
    data = b"".join(_truehd_au(i % 4 == 0, i) for i in range(10))
    fmap = frames.parse_buffer("truehd", data)
    assert not fmap.problems and fmap.rate == 48000
    assert [i for i, e in enumerate(fmap.entry) if e] == [0, 4, 8]
    assert set(fmap.samples) == {40}


def test_truehd_not_starting_on_major_sync_is_refused() -> None:
    data = b"".join(_truehd_au(i == 2, i) for i in range(4))
    fmap = frames.parse_buffer("truehd", data)
    assert fmap.problems and "major sync" in fmap.problems[0]


def _dts_express_packet(code: int, seed: int) -> bytes:
    """A coreless DTS extension substream carrying DTS Express (LBR), 4096 samples @48k."""
    header_size, size = 16, 400
    bits = (0 << 31) | (0 << 30) | ((header_size - 1) << 22) | ((size - 1) << 6)
    bits |= (1 << 5) | (2 << 3) | 7  # static fields, reference clock 48 kHz, 8 x 512
    packet = bytearray(size)
    packet[0:4] = bytes.fromhex("64582025")
    packet[4] = 0  # user defined
    packet[5:10] = (bits << 7).to_bytes(5, "big")  # 33 bits, MSB first
    packet[header_size : header_size + 4] = bytes.fromhex("0A801921")
    packet[header_size + 4] = code
    for i in range(header_size + 5, size):
        packet[i] = (seed + i) & 0xFF
    return bytes(packet)


def test_dts_express_needs_decoder_init_packets() -> None:
    data = b"".join(_dts_express_packet(2, i) for i in range(5))
    fmap = frames.parse_buffer("dts", data)
    assert not fmap.problems and fmap.rate == 48000
    assert list(fmap.samples) == [4096] * 5 and all(fmap.entry)
    sync_only = data + _dts_express_packet(1, 9)
    assert "decoder-init" in frames.parse_buffer("dts", sync_only).problems[0]


def test_garbage_and_truncation_are_reported() -> None:
    frame = bytes(_ac3_frame(1))
    assert frames.parse_buffer("ac3", b"\0" + frame).problems
    assert "truncated" in frames.parse_buffer("ac3", frame + frame[:100]).problems[0]


# --- planning -------------------------------------------------------------------------


def _ac3_map(n: int) -> frames.FrameMap:
    return frames.parse_buffer("ac3", b"".join(bytes(_ac3_frame(i)) for i in range(n)))


def test_plan_negative_delay_keeps_mkvmerge_rule_and_rounds_once() -> None:
    fmap = _ac3_map(400)
    plan = plan_frames(fmap, -11_010_834_586, None)
    # 345 * 32 ms = 11040 ms >= 11010.834586 ms; the first kept frame lands at
    # +29.165414 ms, rounded once -> 29.
    assert (plan.first, plan.sync_ms, plan.last) == (345, 29, 399)
    assert plan.first_kept_ns == 29_165_414


def test_plan_positive_delay_drops_nothing() -> None:
    plan = plan_frames(_ac3_map(10), 517_400_000, None)
    assert (plan.first, plan.last, plan.sync_ms) == (0, 9, 517)


def test_plan_end_keeps_units_starting_before_the_video_end() -> None:
    fmap = _ac3_map(100)
    plan = plan_frames(fmap, 0, 1000 * MS)  # frames at 0, 32, ... 992, 1024 ms
    assert plan.last == 31  # starts at 992 ms; frame 32 starts at 1024 ms
    assert plan.end_overrun_ns == 24 * MS
    exact = plan_frames(
        fmap, 0, 992 * MS
    )  # a frame starting exactly at the end is dropped
    assert exact.last == 30 and exact.end_overrun_ns == 0


def test_plan_end_uses_where_units_really_land() -> None:
    plan = plan_frames(_ac3_map(100), -10 * MS, 1000 * MS)
    # first kept frame (index 1) at 22 ms -> frames at 22 + 32 i ms; last before 1000 ms
    assert (plan.first, plan.sync_ms) == (1, 22)
    assert plan.last == 31 and plan.end_overrun_ns == (22 + 31 * 32 - 1000) * MS


def test_plan_truehd_starts_on_the_next_major_sync() -> None:
    fmap = frames.parse_buffer(
        "truehd", b"".join(_truehd_au(i % 128 == 0, i) for i in range(1000))
    )
    plan = plan_frames(fmap, -1 * MS, None)  # -1 ms: AU 2 would do, a major is needed
    assert plan.first == 128
    assert plan.sync_ms == round(128 * 40 / 48 - 1)


def test_plan_delay_removing_everything_is_an_error() -> None:
    with pytest.raises(PassthroughError):
        plan_frames(_ac3_map(3), -1000 * MS, None)


# --- writers and checks ---------------------------------------------------------------


def test_byte_cut_is_an_exact_slice(tmp_path: Path) -> None:
    raw = b"".join(bytes(_ac3_frame(i)) for i in range(50))
    src = _write(tmp_path / "a.ac3", raw)
    cut = cut_passthrough("ac3", src, -100 * MS, 1000 * MS, tmp_path / "c.ac3")
    assert cut.output is not None
    assert (cut.dropped_start, cut.sync_ms) == (4, 28)  # 128 - 100 ms
    kept = 50 - cut.dropped_start - cut.dropped_end
    assert cut.output.read_bytes() == raw[4 * 1792 : (4 + kept) * 1792]


def test_nothing_to_cut_writes_nothing(tmp_path: Path) -> None:
    src = _write(tmp_path / "a.ac3", b"".join(bytes(_ac3_frame(i)) for i in range(5)))
    cut = cut_passthrough("ac3", src, 40 * MS, None, tmp_path / "c.ac3")
    assert cut.output is None and cut.sync_ms == 40
    assert not (tmp_path / "c.ac3").exists()


def test_dialnorm_edit_matches_the_ac3_rules(tmp_path: Path) -> None:
    frame = _ac3_frame(3, dialnorm_level=27)
    assert dialnorm.checksums_ok(frame, False)
    edited = bytearray(frame)
    assert dialnorm.remove_dialnorm_frame(edited)
    assert dialnorm.checksums_ok(edited, False)
    _, positions = dialnorm.dialnorm_positions(edited)
    assert dialnorm._get_bits(edited, positions[0], 5) == dialnorm.REMOVED_LEVEL
    assert not dialnorm.remove_dialnorm_frame(edited)  # already 31: unchanged

    src = _write(tmp_path / "a.ac3", b"".join(bytes(_ac3_frame(i)) for i in range(6)))
    cut = cut_passthrough("ac3", src, 0, None, tmp_path / "c.ac3", remove_dialnorm=True)
    assert cut.output is not None and cut.dialnorm_frames == 6


def _wav(path: Path, samples: int, channels: int = 2, rate: int = 48000) -> bytes:
    data = bytes((i * 13) & 0xFF for i in range(samples * channels * 3))
    fmt = struct.pack(
        "<HHIIHH", 1, channels, rate, rate * channels * 3, channels * 3, 24
    )
    path.write_bytes(
        b"RIFF" + struct.pack("<I", 4 + 24 + 8 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data))
        + data
    )  # fmt: skip
    return data


def test_pcm_cut_is_sample_exact(tmp_path: Path) -> None:
    src = tmp_path / "a.wav"
    data = _wav(src, 48000)
    cut = cut_passthrough("pcm", src, -10_834_789, 900 * MS, tmp_path / "c.wav")
    # first kept sample: ceil(10.834789 ms * 48 kHz) = 521 -> lands at +0.0019 ms -> 0
    assert (cut.dropped_start, cut.sync_ms) == (521, 0)
    keep = 48000 - 521 - cut.dropped_end
    assert keep == 900 * 48  # samples starting before 900 ms
    assert cut.output is not None
    layout = read_wav_layout(cut.output)
    body = cut.output.read_bytes()[
        layout.data_offset : layout.data_offset + layout.data_bytes
    ]
    assert body == data[521 * 6 : (521 + keep) * 6]


def _opus_stream(path: Path, packets: int, pre_skip: int = 312) -> OggOpus:
    head = b"OpusHead" + bytes([1, 2]) + struct.pack("<HIhB", pre_skip, 48000, 0, 0)
    stream = OggOpus(head, b"OpusTags" + b"\0" * 8, 0x1234, (), ())
    pkts = tuple(
        bytes([0x08]) + bytes([i & 0xFF]) * 20 for i in range(packets)
    )  # 20 ms each
    write_ogg_opus(path, stream, pkts, pre_skip, packets * 960)
    return read_ogg_opus(path)


def test_opus_cut_is_sample_exact_through_pre_skip(tmp_path: Path) -> None:
    src = tmp_path / "a.opus"
    stream = _opus_stream(src, 200)
    assert opus_packet_samples(stream.packets[0]) == 960
    audible = 200 * 960 - 312
    cut = cut_passthrough("opus", src, -1001 * MS, 2000 * MS, tmp_path / "c.opus")
    assert cut.output is not None
    out = read_ogg_opus(cut.output)
    first = 48048  # 1001 ms
    assert (cut.dropped_start, cut.sync_ms) == (first, 0)
    keep = audible - first - cut.dropped_end
    assert keep == 2000 * 48
    assert out.final_granule - out.pre_skip == keep
    # 80 ms of pre-roll before the first kept sample
    start_decoded = first + 312
    j = (start_decoded - 3840) // 960
    assert out.pre_skip == start_decoded - j * 960
    assert out.packets[0] == stream.packets[j]
