# vsg_core/audio_processing/frames.py
"""mkvmerge's packet rules for raw audio elementary streams.

A track that keeps its codec can only be cut on the boundaries mkvmerge will
see when it muxes the file. Each parser here walks a raw file (as mkvextract
writes it) the way MKVToolNix 103.0's reader + packetizer do, and returns
mkvmerge's packets ("units"): byte position, size, sample count in the
packetizer's clock, and whether a decoder can start on it. Anything mkvmerge
would skip, resync over or mis-time is a problem, never guessed around.

Sources (MKVToolNix 103.0, unchanged in MKVToolNix-Mod): common/ac3.cpp,
output/p_ac3.cpp, common/truehd.cpp, output/p_truehd.cpp, common/dts.cpp,
output/p_dts.cpp, common/aac.cpp, output/p_aac.cpp, common/mp3.cpp,
output/p_mp3.cpp. Checked against mkvmerge's own packetization on 448 tracks
(Tests/audio_negative_sync/harness, sweep 3).
"""

from __future__ import annotations

import mmap
import struct
from array import array
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# Byte-sliced codec families (one parser each).
FrameFamily = Literal["ac3", "truehd", "dts", "aac", "mpa"]

# Buffer type the parsers accept: bytes in tests, an mmap for real files.
Buffer = bytes | bytearray | mmap.mmap


@dataclass(frozen=True, slots=True)
class FrameMap:
    """mkvmerge's packets of one raw stream.

    Unit ``i`` covers bytes ``pos[i] : pos[i] + size[i]`` and lasts
    ``samples[i]`` samples at ``rate``. ``entry[i]`` is 1 when a decoder can
    start on it (and mkvmerge times a file that starts there correctly).
    """

    family: FrameFamily
    rate: int
    pos: array[int]
    size: array[int]
    samples: array[int]
    entry: bytearray
    problems: tuple[str, ...]
    file_size: int

    def __len__(self) -> int:
        return len(self.pos)

    @property
    def end(self) -> int:
        """Byte offset one past the last complete unit."""
        return self.pos[-1] + self.size[-1] if len(self.pos) else 0


@dataclass(slots=True)
class _Builder:
    family: FrameFamily
    rate: int = 0
    pos: array[int] = field(default_factory=lambda: array("q"))
    size: array[int] = field(default_factory=lambda: array("q"))
    samples: array[int] = field(default_factory=lambda: array("q"))
    entry: bytearray = field(default_factory=bytearray)
    problems: list[str] = field(default_factory=list)

    def add(self, pos: int, size: int, samples: int, entry: bool) -> None:
        self.pos.append(pos)
        self.size.append(size)
        self.samples.append(samples)
        self.entry.append(1 if entry else 0)

    def done(self, file_size: int) -> FrameMap:
        return FrameMap(
            self.family,
            self.rate,
            self.pos,
            self.size,
            self.samples,
            self.entry,
            tuple(self.problems),
            file_size,
        )


def _be16(b: Buffer, p: int) -> int:
    return (b[p] << 8) | b[p + 1]


def _be32(b: Buffer, p: int) -> int:
    return int(struct.unpack_from(">I", b, p)[0])


class _Bits:
    """MSB-first bit reader over a buffer."""

    def __init__(self, b: Buffer, byte_pos: int) -> None:
        self._b = b
        self._bit = byte_pos * 8

    def get(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self._b[self._bit >> 3]
            v = (v << 1) | ((byte >> (7 - (self._bit & 7))) & 1)
            self._bit += 1
        return v


# --- AC-3 / E-AC-3: common/ac3.cpp frame_c::decode_header*, parser_c::parse -----------

_AC3_RATES = (48000, 44100, 32000)
_EAC3_RATES = (48000, 44100, 32000, 24000, 22050, 16000)
_EAC3_SAMPLES = (256, 512, 768, 1536)
_AC3_FRAME_WORDS = (
    (64, 69, 96), (64, 70, 96), (80, 87, 120), (80, 88, 120), (96, 104, 144),
    (96, 105, 144), (112, 121, 168), (112, 122, 168), (128, 139, 192),
    (128, 140, 192), (160, 174, 240), (160, 175, 240), (192, 208, 288),
    (192, 209, 288), (224, 243, 336), (224, 244, 336), (256, 278, 384),
    (256, 279, 384), (320, 348, 480), (320, 349, 480), (384, 417, 576),
    (384, 418, 576), (448, 487, 672), (448, 488, 672), (512, 557, 768),
    (512, 558, 768), (640, 696, 960), (640, 697, 960), (768, 835, 1152),
    (768, 836, 1152), (896, 975, 1344), (896, 976, 1344), (1024, 1114, 1536),
    (1024, 1115, 1536), (1152, 1253, 1728), (1152, 1254, 1728),
    (1280, 1393, 1920), (1280, 1394, 1920),
)  # fmt: skip
_AC3_HEADER_BYTES = 18
_AC3_SYNC = 0x0B77
_EAC3_DEPENDENT = 1
_EAC3_RESERVED = 3


@dataclass(frozen=True, slots=True)
class Ac3Header:
    """The fields of an AC-3 / E-AC-3 sync frame header the cut needs."""

    size: int
    samples: int
    rate: int
    frame_type: int  # 0 independent, 1 dependent, 2 converted from AC-3
    substream_id: int
    is_eac3: bool


def ac3_header(b: Buffer, pos: int) -> Ac3Header | None:
    """Decode the header at ``pos`` as mkvmerge does, or None."""
    if pos + _AC3_HEADER_BYTES > len(b) or _be16(b, pos) != _AC3_SYNC:
        return None
    bsid = b[pos + 5] >> 3
    if bsid <= 8:  # regular AC-3 (bsid 9/10 are rejected by mkvmerge's dispatch)
        fscod, frmsizecod = b[pos + 4] >> 6, b[pos + 4] & 0x3F
        if fscod == 3 or frmsizecod >= len(_AC3_FRAME_WORDS):
            return None
        size = _AC3_FRAME_WORDS[frmsizecod][fscod] * 2
        return Ac3Header(size, 1536, _AC3_RATES[fscod], 0, 0, False)
    if 10 < bsid <= 16:
        frame_type = b[pos + 2] >> 6
        if frame_type == _EAC3_RESERVED:
            return None
        size = ((((b[pos + 2] & 7) << 8) | b[pos + 3]) + 1) * 2
        fscod, fscod2 = b[pos + 4] >> 6, (b[pos + 4] >> 4) & 3
        if fscod == 3 and fscod2 == 3:
            return None
        rate = _EAC3_RATES[3 + fscod2] if fscod == 3 else _EAC3_RATES[fscod]
        samples = 1536 if fscod == 3 else _EAC3_SAMPLES[fscod2]
        return Ac3Header(size, samples, rate, frame_type, (b[pos + 2] >> 3) & 7, True)
    return None


def parse_ac3(b: Buffer) -> FrameMap:
    """One unit = an independent frame plus the dependent frames after it."""
    out = _Builder("ac3")
    pos = 0
    unit: list[int] | None = None  # [pos, size, samples, entry]
    while pos + _AC3_HEADER_BYTES <= len(b):
        if _be16(b, pos) == 0x770B:
            out.problems.append(f"byte-swapped AC-3 at byte {pos}")
            return out.done(len(b))
        f = ac3_header(b, pos)
        if f is None:
            out.problems.append(
                f"no valid AC-3 header at byte {pos} (mkvmerge would skip it)"
            )
            return out.done(len(b))
        if pos + f.size > len(b):
            out.problems.append(f"truncated last frame at byte {pos}")
            break
        dependent = f.frame_type == _EAC3_DEPENDENT
        if not out.rate:
            out.rate = f.rate
        elif not dependent and f.rate != out.rate:
            out.problems.append(f"sample rate changes at byte {pos}")
            return out.done(len(b))
        if unit is None or not dependent:
            if unit is not None:
                out.add(unit[0], unit[1], unit[2], bool(unit[3]))
            if not dependent and f.substream_id != 0:
                out.problems.append(
                    f"independent substream {f.substream_id} at byte {pos} "
                    "(mkvmerge mis-times these)"
                )
                return out.done(len(b))
            unit = [pos, f.size, f.samples, 1 if f.frame_type in (0, 2) else 0]
        else:
            unit[1] += f.size
        pos += f.size
    if unit is not None:
        out.add(unit[0], unit[1], unit[2], bool(unit[3]))
    if pos != len(b):
        out.problems.append(f"{len(b) - pos} trailing bytes")
    return out.done(len(b))


# --- TrueHD / MLP: common/truehd.cpp frame_t::parse_header, parser_c::parse ------------

_MLP_MAJOR_SYNCS = (0xF8726FBA, 0xF8726FBB)  # TrueHD, MLP


def _mlp_rate(bits: int) -> int:
    return 0 if bits == 0xF else (44100 if bits & 8 else 48000) << (bits & 7)


def parse_truehd(b: Buffer) -> FrameMap:
    """One unit = one access unit; a decoder can start only on a major sync."""
    out = _Builder("truehd")
    pos = 0
    samples_per_au = 0
    while pos + 6 <= len(b):
        word = _be16(b, pos)
        sync = _be32(b, pos + 4) if pos + 8 <= len(b) else 0
        major = sync in _MLP_MAJOR_SYNCS
        if not major and word == _AC3_SYNC:
            out.problems.append(
                f"embedded AC-3 frame at byte {pos} (mkvmerge drops it)"
            )
            return out.done(len(b))
        size = (word & 0xFFF) * 2
        if size < 8:
            out.problems.append(
                f"invalid access unit length at byte {pos} (mkvmerge would resync)"
            )
            return out.done(len(b))
        if pos + size > len(b):
            out.problems.append(f"truncated last access unit at byte {pos}")
            break
        if major:
            rate_bits = (
                (b[pos + 8] >> 4) if sync == _MLP_MAJOR_SYNCS[0] else (b[pos + 9] >> 4)
            )
            rate = _mlp_rate(rate_bits)
            if not rate:
                out.problems.append(f"invalid sample rate at byte {pos}")
                return out.done(len(b))
            if not out.rate:
                out.rate = rate
            elif rate != out.rate:
                out.problems.append(f"sample rate changes at byte {pos}")
                return out.done(len(b))
            samples_per_au = 40 << (rate_bits & 7)
        elif not samples_per_au:
            out.problems.append(
                "stream does not start on a major sync (mkvmerge resyncs and restamps)"
            )
            return out.done(len(b))
        out.add(pos, size, samples_per_au, major)
        pos += size
    if pos != len(b):
        out.problems.append(f"{len(b) - pos} trailing bytes")
    return out.done(len(b))


# --- DTS: common/dts.cpp find_header / decode_core_header / decode_exss_header ---------

_DTS_CORE = 0x7FFE8001
_DTS_EXSS = 0x64582025
_DTS_X96 = 0x1D95F262
_DTS_XLL = 0x41A29547
_DTS_LBR = 0x0A801921
_LBR_SYNC_ONLY = 1
_LBR_DECODER_INIT = 2
_DTS_CORE_RATES = (
    0, 8000, 16000, 32000, 0, 0, 11025, 22050, 44100, 0, 0, 12000, 24000, 48000, 0, 0,
)  # fmt: skip
_DTS_REF_CLOCKS = (32000, 44100, 48000)


@dataclass(frozen=True, slots=True)
class _Exss:
    size: int
    header_size: int
    duration: int | None  # frame duration in reference-clock samples
    clock: int | None


def _dts_exss(b: Buffer, pos: int) -> _Exss:
    r = _Bits(b, pos)
    r.get(32)  # sync
    r.get(8)  # user defined
    r.get(2)  # substream index
    wide = r.get(1)
    header_size = r.get(12 if wide else 8) + 1
    size = r.get(20 if wide else 16) + 1
    if r.get(1):  # static fields present
        clock = r.get(2)
        duration = (r.get(3) + 1) * 512
        return _Exss(
            size, header_size, duration, _DTS_REF_CLOCKS[clock] if clock < 3 else None
        )
    return _Exss(size, header_size, None, None)


def parse_dts(b: Buffer) -> FrameMap:
    """One unit = a core frame plus the extension substream right after it, or
    one extension substream for a coreless stream (pure lossless XLL, or DTS
    Express, where every packet must carry a decoder-init header)."""
    out = _Builder("dts")
    pos = 0
    first_kind: str | None = None
    while pos + 15 <= len(b):
        sync = _be32(b, pos)
        if sync == _DTS_CORE:
            r = _Bits(b, pos + 4)
            normal = r.get(1)
            deficit = (r.get(5) + 1) % 32
            r.get(1)  # crc present
            nblks = r.get(7) + 1
            fsize = r.get(14) + 1
            r.get(6)  # amode
            rate = _DTS_CORE_RATES[r.get(4)]
            if fsize < 96 or not rate:
                out.problems.append(f"invalid DTS core header at byte {pos}")
                return out.done(len(b))
            samples = nblks * 32
            if not normal:  # termination frame
                samples -= min(samples, deficit)
            size = fsize
            if pos + size + 4 <= len(b):
                nxt = _be32(b, pos + size)
                if nxt == _DTS_EXSS:
                    size += _dts_exss(b, pos + size).size
                elif nxt == _DTS_X96:
                    out.problems.append(
                        f"X96 extension after the core at byte {pos} "
                        "(mkvmerge rejects that header)"
                    )
                    return out.done(len(b))
            kind = "core"
        elif sync == _DTS_EXSS:
            exss = _dts_exss(b, pos)
            if exss.duration is None or exss.clock is None:
                out.problems.append(
                    f"coreless DTS packet without a frame duration at byte {pos}"
                )
                return out.done(len(b))
            asset = pos + exss.header_size
            asset_sync = _be32(b, asset) if asset + 4 <= len(b) else 0
            if asset_sync == _DTS_LBR:
                # DTS Express: only a packet whose LBR header is "decoder init"
                # (format code 2) can start a decoder, and it is what gives
                # mkvmerge the sample rate; a "sync only" packet (code 1) can't.
                code = b[asset + 4] if asset + 5 <= len(b) else 0
                if code == _LBR_SYNC_ONLY:
                    out.problems.append(
                        f"DTS Express packet without a decoder-init header at byte {pos} "
                        "(mkvmerge's timing of these is not verified on a real sample)"
                    )
                    return out.done(len(b))
                if code != _LBR_DECODER_INIT:
                    out.problems.append(
                        f"unknown DTS Express header {code} at byte {pos}"
                    )
                    return out.done(len(b))
                kind = "lbr"
            elif asset_sync == _DTS_XLL:
                kind = "xll"
            else:
                out.problems.append(
                    f"coreless DTS packet at byte {pos} does not start with XLL or "
                    "DTS Express data"
                )
                return out.done(len(b))
            size, samples, rate = exss.size, exss.duration, exss.clock
        else:
            out.problems.append(f"no DTS sync at byte {pos} (mkvmerge would skip it)")
            return out.done(len(b))
        if first_kind is None:
            first_kind = kind
        elif kind != first_kind:
            out.problems.append(
                f"stream switches between core and coreless packets at byte {pos}"
            )
            return out.done(len(b))
        if pos + size > len(b):
            out.problems.append(f"truncated last packet at byte {pos}")
            break
        if not out.rate:
            out.rate = rate
        elif rate != out.rate:
            out.problems.append(f"sample rate changes at byte {pos}")
            return out.done(len(b))
        out.add(pos, size, samples, True)
        pos += size
    if pos != len(b):
        out.problems.append(f"{len(b) - pos} trailing bytes")
    return out.done(len(b))


# --- AAC (ADTS): common/aac.cpp parser_c::decode_adts_header, output/p_aac.cpp ---------

_AAC_RATES = (
    96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025,
    8000, 7350, 0, 0, 0,
)  # fmt: skip


def parse_aac(b: Buffer) -> FrameMap:
    """One unit = one ADTS frame (1024 samples at the ADTS rate)."""
    out = _Builder("aac")
    pos = 0
    while pos + 7 <= len(b):
        if b[pos] != 0xFF or (b[pos + 1] & 0xF6) != 0xF0:
            out.problems.append(
                f"no ADTS header at byte {pos} (mkvmerge would skip it)"
            )
            return out.done(len(b))
        rate = _AAC_RATES[(b[pos + 2] >> 2) & 0xF]
        length = ((b[pos + 3] & 3) << 11) | (b[pos + 4] << 3) | (b[pos + 5] >> 5)
        raw_blocks = b[pos + 6] & 3
        header_len = 7 if b[pos + 1] & 1 else 9
        if raw_blocks:
            out.problems.append(
                f"ADTS frame with {raw_blocks + 1} raw data blocks at byte {pos} "
                "(mkvmerge times it as one)"
            )
            return out.done(len(b))
        if not rate or length <= header_len:
            out.problems.append(f"invalid ADTS header at byte {pos}")
            return out.done(len(b))
        if pos + length > len(b):
            out.problems.append(f"truncated last frame at byte {pos}")
            break
        if not out.rate:
            out.rate = rate
        elif rate != out.rate:
            out.problems.append(f"sample rate changes at byte {pos}")
            return out.done(len(b))
        out.add(pos, length, 1024, True)
        pos += length
    if pos != len(b):
        out.problems.append(f"{len(b) - pos} trailing bytes")
    return out.done(len(b))


# --- MPEG-1/2 audio layers I-III: common/mp3.cpp decode_mp3_header, output/p_mp3.cpp ---

_MPA_BITRATES_V1 = (
    (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0),
    (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0),
    (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
)
_MPA_BITRATES_V2 = (
    (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0),
    (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
)
_MPA_RATES = (
    (44100, 48000, 32000, 0),
    (22050, 24000, 16000, 0),
    (11025, 12000, 8000, 0),
)
_MPA_SAMPLES = ((384, 1152, 1152), (384, 1152, 576), (384, 1152, 576))


def _mpa_header(b: Buffer, pos: int) -> tuple[int, int, int] | None:
    """(frame size, samples per channel, sample rate) or None."""
    if pos + 4 > len(b):
        return None
    hdr = _be32(b, pos)
    if (hdr & 0xFFE00000) != 0xFFE00000:
        return None
    version_bits = (hdr >> 19) & 3
    layer = 4 - ((hdr >> 17) & 3)
    if version_bits == 1 or layer == 4:
        return None
    version = 3 if version_bits == 0 else 1 if version_bits == 3 else version_bits
    bitrates = _MPA_BITRATES_V1 if version == 1 else _MPA_BITRATES_V2
    bitrate = bitrates[layer - 1][(hdr >> 12) & 15]
    rate = _MPA_RATES[version - 1][(hdr >> 10) & 3]
    if not bitrate or not rate:
        return None
    padding = (hdr >> 9) & 1
    if layer == 3:
        size = (144000 if version == 1 else 72000) * bitrate // rate + padding
    elif layer == 2:
        size = 144000 * bitrate // rate + padding
    else:
        size = (12000 * bitrate // rate + padding) * 4
    return size, _MPA_SAMPLES[version - 1][layer - 1], rate


def parse_mpa(b: Buffer) -> FrameMap:
    """One unit = one MPEG audio frame (a LAME/Xing info frame counts, as in mkvmerge)."""
    out = _Builder("mpa")
    if b[:3] in (b"ID3", b"TAG"):
        out.problems.append("tag at the start of the raw stream (mkvmerge skips it)")
        return out.done(len(b))
    pos = 0
    samples_per_frame = 0
    end = len(b)
    while pos + 4 <= end:
        if b[pos : pos + 3] == b"TAG" and end - pos == 128:
            out.problems.append("ID3v1 tag at the end")
            end = pos
            break
        h = _mpa_header(b, pos)
        if h is None:
            out.problems.append(
                f"no MPEG audio header at byte {pos} (mkvmerge would skip it)"
            )
            return out.done(len(b))
        size, spf, rate = h
        if pos + size > end:
            out.problems.append(f"truncated last frame at byte {pos}")
            break
        if not out.rate:
            # mkvmerge fixes samples-per-frame from the first header
            out.rate, samples_per_frame = rate, spf
        elif rate != out.rate:
            out.problems.append(f"sample rate changes at byte {pos}")
            return out.done(len(b))
        out.add(pos, size, samples_per_frame, True)
        pos += size
    if pos != end:
        out.problems.append(f"{end - pos} trailing bytes")
    return out.done(len(b))


_PARSERS: dict[FrameFamily, Callable[[Buffer], FrameMap]] = {
    "ac3": parse_ac3,
    "truehd": parse_truehd,
    "dts": parse_dts,
    "aac": parse_aac,
    "mpa": parse_mpa,
}


def parse_buffer(family: FrameFamily, data: Buffer) -> FrameMap:
    return _PARSERS[family](data)


def parse_file(family: FrameFamily, path: Path) -> FrameMap:
    """Parse a raw file without reading it into memory."""
    size = path.stat().st_size
    if size == 0:
        return FrameMap(
            family,
            0,
            array("q"),
            array("q"),
            array("q"),
            bytearray(),
            ("empty file",),
            0,
        )
    with path.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        return parse_buffer(family, mm)
