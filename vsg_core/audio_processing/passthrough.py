# vsg_core/audio_processing/passthrough.py
"""Cut an audio track that keeps its codec, so mkvmerge only gets ``--sync >= 0``.

mkvmerge's own negative ``--sync`` drops whole packets by time and never checks
that the first one can start a decoder; nothing trims the end. Here the app
makes both cuts itself, on the boundaries mkvmerge will see:

- byte codecs (AC-3/E-AC-3, TrueHD/MLP, DTS, AAC, MPEG audio): whole units
  from ``frames.py``, the first kept one an entry unit (TrueHD major sync,
  E-AC-3 independent frame with its dependents, never a lone DTS extension);
- PCM (WAV): any sample;
- Opus: any sample, through the Ogg pre-skip and end granule (no re-encode).

The first kept unit lands at a whole ms (``sync_ms``), the residual of the
exact delay rounded once. Every written file is re-read and checked against
the plan before it replaces the extraction. Nothing inside a kept unit
changes, except the optional dialnorm edit (``dialnorm.py``).
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from .dialnorm import (
    REMOVED_LEVEL,
    checksums_ok_rows,
    dialnorm_positions,
    get_bits,
    remove_dialnorm_frames,
)
from .frames import FrameFamily, FrameMap, ac3_header, parse_file
from .ogg_opus import (
    OPUS_RATE,
    OggOpusError,
    opus_packet_samples,
    read_ogg_opus,
    write_ogg_opus,
)

if TYPE_CHECKING:
    from pathlib import Path

PassthroughKind = Literal["ac3", "truehd", "dts", "aac", "mpa", "pcm", "opus"]

NS = 1_000_000_000
_COPY_CHUNK = 8 * 1024 * 1024
# Units edited and checked per batch when removing dialnorm (~15 MB of AC-3).
_DIALNORM_BLOCK = 8192
# Opus decoders converge within 80 ms; RFC 7845 §4.6 recommends that much pre-roll.
_OPUS_PREROLL = 3840

# Order matters: A_EAC3 before A_AC3.
_KINDS: tuple[tuple[str, PassthroughKind], ...] = (
    ("A_EAC3", "ac3"),
    ("A_AC3", "ac3"),
    ("A_TRUEHD", "truehd"),
    ("A_MLP", "truehd"),
    ("A_DTS", "dts"),
    ("A_AAC", "aac"),
    ("A_MPEG/L", "mpa"),
    ("A_PCM/INT", "pcm"),
    ("A_MS/ACM", "pcm"),
    ("A_OPUS", "opus"),
)

UNIT_NAMES: dict[PassthroughKind, str] = {
    "ac3": "frames",
    "truehd": "access units",
    "dts": "packets",
    "aac": "frames",
    "mpa": "frames",
    "pcm": "samples",
    "opus": "samples",
}


def passthrough_kind(codec_id: str) -> PassthroughKind | None:
    """How a codec is cut, or None when the app leaves it to mkvmerge."""
    cid = (codec_id or "").upper()
    return next((kind for prefix, kind in _KINDS if cid.startswith(prefix)), None)


def frame_family(kind: PassthroughKind) -> FrameFamily:
    """The frame parser family of a byte-cut kind (not PCM or Opus)."""
    if kind in ("pcm", "opus"):
        raise ValueError(f"{kind} is not cut in byte units")
    return kind


class PassthroughError(RuntimeError):
    """The track cannot be cut safely; the caller keeps today's mkvmerge path."""


@dataclass(frozen=True, slots=True)
class PassthroughCut:
    """What the cut did to one track."""

    kind: PassthroughKind
    rate: int
    sync_ms: int  # what mkvmerge gets (>= 0)
    output: Path | None  # the file to mux; None = the extraction is muxed unchanged
    units_total: int
    dropped_start: int
    dropped_end: int
    first_kept_ns: (
        int  # exact time of the first kept unit (delay applied), before rounding
    )
    # How far the kept audio runs past the video end; None when nothing was
    # trimmed (trim off, Source 1, or the track ends before the video end).
    end_overrun_ns: int | None
    longest_unit_ns: int
    dialnorm_frames: int = 0

    @property
    def unit_name(self) -> str:
        return UNIT_NAMES[self.kind]


def _round_ms(num: int, den: int) -> int:
    """Nearest whole ms of the time num/den seconds (>= 0), halves up."""
    return (2000 * num + den) // (2 * den)


def _ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


# ---------------------------------------------------------------------------
# byte codecs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FramePlan:
    first: int
    last: int  # inclusive
    sync_ms: int
    first_kept_ns: int
    end_overrun_ns: int | None


def plan_frames(fmap: FrameMap, delay_ns: int, video_end_ns: int | None) -> FramePlan:
    """First kept unit: the first entry unit with t + delay >= 0 (mkvmerge's
    rule plus "a decoder can start here"). Last kept unit: the last one that
    starts before the video end, where the units really land (sync_ms + offset)."""
    rate = fmap.rate
    n = len(fmap)
    if not n or not rate:
        raise PassthroughError("no audio units")
    cum = 0
    first = -1
    for i in range(n):
        if fmap.entry[i] and cum * NS + delay_ns * rate >= 0:
            first = i
            break
        cum += fmap.samples[i]
    if first < 0:
        raise PassthroughError("the delay removes the whole track")
    cum_first = cum
    exact = cum_first * NS + delay_ns * rate  # (t_first + delay) * rate, in ns
    sync_ms = _round_ms(exact, rate * NS)
    first_kept_ns = exact // rate

    last = n - 1
    overrun: int | None = None
    if video_end_ns is not None:
        limit = video_end_ns * rate - sync_ms * 1_000_000 * rate
        last = -1
        offset = 0  # samples since the first kept unit
        for i in range(first, n):
            if offset * NS >= limit:
                break
            last = i
            offset += fmap.samples[i]
        if last < 0:
            raise PassthroughError("no audio is left before the video end")
        overrun = (offset * NS - limit) // rate
        if overrun < 0:  # the track ends before the video end: nothing to trim
            overrun = None
    return FramePlan(first, last, sync_ms, first_kept_ns, overrun)


def _split_frames(data: bytes) -> list[bytearray]:
    """AC-3 / E-AC-3 frames of a run of whole units."""
    frames = []
    pos = 0
    while pos < len(data):
        h = ac3_header(data, pos)
        if h is None:
            raise PassthroughError("units do not split into AC-3 frames")
        frames.append(bytearray(data[pos : pos + h.size]))
        pos += h.size
    return frames


def _unit_blocks(fmap: FrameMap, plan: FramePlan) -> list[tuple[int, int]]:
    """(start unit, byte count) of each batch of kept units."""
    blocks = []
    for i in range(plan.first, plan.last + 1, _DIALNORM_BLOCK):
        j = min(i + _DIALNORM_BLOCK, plan.last + 1)
        blocks.append((i, fmap.pos[j - 1] + fmap.size[j - 1] - fmap.pos[i]))
    return blocks


def _write_frames(
    src: Path, fmap: FrameMap, plan: FramePlan, dst: Path, dialnorm: bool
) -> int:
    start, end = fmap.pos[plan.first], fmap.pos[plan.last] + fmap.size[plan.last]
    changed = 0
    with src.open("rb") as f, dst.open("wb") as out:
        f.seek(start)
        if not dialnorm:
            left = end - start
            while left:
                chunk = f.read(min(_COPY_CHUNK, left))
                if not chunk:
                    raise PassthroughError("source ended early")
                out.write(chunk)
                left -= len(chunk)
            return 0
        for _start, nbytes in _unit_blocks(fmap, plan):
            frames = _split_frames(f.read(nbytes))
            changed += remove_dialnorm_frames(frames)
            out.write(b"".join(frames))
    return changed


def _sha256_range(path: Path, start: int, end: int) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        f.seek(start)
        left = end - start
        while left:
            chunk = f.read(min(_COPY_CHUNK, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest()


def _dialnorm_bytes(frame: bytes | bytearray) -> set[int]:
    """Byte offsets a dialnorm edit may change in one frame."""
    is_eac3, positions = dialnorm_positions(frame)
    allowed = {len(frame) - 3, len(frame) - 2, len(frame) - 1}
    if not is_eac3:
        allowed |= {2, 3}
    for p in positions:
        allowed |= {p >> 3, (p + 4) >> 3}
    return allowed


def _check_dialnorm_copy(
    src: Path, dst: Path, fmap: FrameMap, plan: FramePlan
) -> str | None:
    with src.open("rb") as a, dst.open("rb") as b:
        a.seek(fmap.pos[plan.first])
        for start, nbytes in _unit_blocks(fmap, plan):
            new = b.read(nbytes)
            groups: dict[tuple[int, bool], list[bytes]] = {}
            pos = 0
            for fo in _split_frames(a.read(nbytes)):
                size = len(fo)
                fn = new[pos : pos + size]
                expected = bytearray(fo)
                for j in _dialnorm_bytes(fo):
                    expected[j] = fn[j]
                if expected != fn:
                    return f"units from {start}: bytes other than dialnorm/CRC changed"
                is_eac3, positions = dialnorm_positions(fn)
                if any(get_bits(fn, p, 5) != REMOVED_LEVEL for p in positions):
                    return (
                        f"units from {start}: a dialnorm field is not {REMOVED_LEVEL}"
                    )
                groups.setdefault((size, is_eac3), []).append(fn)
                pos += size
            for (size, is_eac3), frames in groups.items():
                rows = np.frombuffer(b"".join(frames), dtype=np.uint8)
                if not checksums_ok_rows(
                    rows.reshape(len(frames), size), is_eac3
                ).all():
                    return (
                        f"units from {start}: a frame has a bad checksum after the edit"
                    )
    return None


def _verify_frames(
    src: Path, dst: Path, fmap: FrameMap, plan: FramePlan, dialnorm: bool
) -> None:
    again = parse_file(fmap.family, dst)
    k, m = plan.first, plan.last + 1
    problems: list[str] = list(again.problems)
    if len(again) != m - k:
        problems.append(f"{len(again)} units, planned {m - k}")
    elif again.size != fmap.size[k:m] or again.samples != fmap.samples[k:m]:
        problems.append("unit sizes or durations differ from the plan")
    elif not again.entry[0]:
        problems.append("the cut file does not start on an entry unit")
    elif fmap.family == "truehd" and again.entry != fmap.entry[k:m]:
        problems.append("major-sync positions differ from the source")
    if not problems:
        if dialnorm:
            issue = _check_dialnorm_copy(src, dst, fmap, plan)
            if issue:
                problems.append(issue)
        elif _sha256_range(dst, 0, again.end) != _sha256_range(
            src, fmap.pos[k], fmap.pos[m - 1] + fmap.size[m - 1]
        ):
            problems.append("cut file is not byte-identical to the source range")
    if problems:
        raise PassthroughError("cut file failed its check: " + "; ".join(problems))


def _cut_frames(
    kind: FrameFamily,
    src: Path,
    delay_ns: int,
    video_end_ns: int | None,
    dst: Path,
    dialnorm: bool,
) -> PassthroughCut:
    fmap = parse_file(kind, src)
    if fmap.problems:
        raise PassthroughError("; ".join(fmap.problems))
    plan = plan_frames(fmap, delay_ns, video_end_ns)
    n = len(fmap)
    rewrite = plan.first > 0 or plan.last < n - 1 or dialnorm
    changed = 0
    if rewrite:
        changed = _write_frames(src, fmap, plan, dst, dialnorm)
        _verify_frames(src, dst, fmap, plan, dialnorm)
    longest = max(fmap.samples) * NS // fmap.rate
    return PassthroughCut(
        kind,
        fmap.rate,
        plan.sync_ms,
        dst if rewrite else None,
        n,
        plan.first,
        n - 1 - plan.last,
        plan.first_kept_ns,
        plan.end_overrun_ns,
        longest,
        changed,
    )


# ---------------------------------------------------------------------------
# PCM (WAV / RF64)
# ---------------------------------------------------------------------------

_WAVE_PCM = 1
_WAVE_EXTENSIBLE = 0xFFFE
_KSDATAFORMAT_PCM = bytes.fromhex("0100000000001000800000aa00389b71")


@dataclass(frozen=True, slots=True)
class WavLayout:
    fmt_chunk: bytes  # "fmt " id + size + body, copied verbatim
    data_offset: int
    data_bytes: int
    block_align: int
    rate: int


def read_wav_layout(path: Path) -> WavLayout:
    with path.open("rb") as f:
        head = f.read(65536)
    if head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
        raise PassthroughError("not a RIFF/RF64 WAVE file")
    pos = 12
    fmt_chunk: bytes | None = None
    ds64_data: int | None = None
    while pos + 8 <= len(head):
        cid = head[pos : pos + 4]
        clen = int(struct.unpack_from("<I", head, pos + 4)[0])
        if cid == b"ds64":
            ds64_data = int(struct.unpack_from("<Q", head, pos + 16)[0])
        elif cid == b"fmt ":
            fmt_chunk = head[pos : pos + 8 + clen]
        elif cid == b"data":
            if fmt_chunk is None:
                break
            size = ds64_data if clen == 0xFFFFFFFF and ds64_data is not None else clen
            tag, channels, rate, _bps, block_align, bits = struct.unpack_from(
                "<HHIIHH", fmt_chunk, 8
            )
            if tag == _WAVE_EXTENSIBLE:
                if (
                    len(fmt_chunk) < 8 + 40
                    or fmt_chunk[8 + 24 : 8 + 40] != _KSDATAFORMAT_PCM
                ):
                    raise PassthroughError(
                        "WAVE_FORMAT_EXTENSIBLE that is not integer PCM"
                    )
            elif tag != _WAVE_PCM:
                raise PassthroughError(f"WAV format tag {tag:#x} is not integer PCM")
            if block_align != channels * ((bits + 7) // 8) or not rate:
                raise PassthroughError(
                    f"unusual PCM packing: {bits}-bit, block align {block_align}, {channels} ch"
                )
            file_size = path.stat().st_size
            size = min(size, file_size - (pos + 8))
            return WavLayout(
                fmt_chunk, pos + 8, size - size % block_align, block_align, rate
            )
        pos += 8 + clen + (clen & 1)
    raise PassthroughError("WAV fmt/data chunk not found")


def _wav_header(layout: WavLayout, data_bytes: int) -> bytes:
    fmt = layout.fmt_chunk + (b"\0" if len(layout.fmt_chunk) & 1 else b"")
    riff_size = 4 + len(fmt) + 8 + data_bytes + (data_bytes & 1)
    if riff_size < 0xFFFFFFFF:
        return (
            b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + fmt
            + b"data" + struct.pack("<I", data_bytes)
        )  # fmt: skip
    ds64 = b"ds64" + struct.pack("<IQQQI", 28, riff_size + 36, data_bytes, 0, 0)
    return (
        b"RF64" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE" + ds64 + fmt
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )  # fmt: skip


def _cut_pcm(
    src: Path, delay_ns: int, video_end_ns: int | None, dst: Path
) -> PassthroughCut:
    layout = read_wav_layout(src)
    rate, align = layout.rate, layout.block_align
    total = layout.data_bytes // align
    first = 0 if delay_ns >= 0 else _ceil_div(-delay_ns * rate, NS)
    if first >= total:
        raise PassthroughError("the delay removes the whole track")
    exact = first * NS + delay_ns * rate
    sync_ms = _round_ms(exact, rate * NS)
    keep = total - first
    overrun: int | None = None
    if video_end_ns is not None:
        limit = video_end_ns * rate - sync_ms * 1_000_000 * rate
        if limit <= 0:
            raise PassthroughError("no audio is left before the video end")
        keep = min(keep, _ceil_div(limit, NS))
        overrun = (keep * NS - limit) // rate
        if overrun < 0:  # the track ends before the video end: nothing to trim
            overrun = None
    rewrite = first > 0 or keep < total - first
    if rewrite:
        start = layout.data_offset + first * align
        nbytes = keep * align
        with src.open("rb") as f, dst.open("wb") as out:
            out.write(_wav_header(layout, nbytes))
            f.seek(start)
            left = nbytes
            while left:
                chunk = f.read(min(_COPY_CHUNK, left))
                if not chunk:
                    raise PassthroughError("source ended early")
                out.write(chunk)
                left -= len(chunk)
            if nbytes & 1:
                out.write(b"\0")
        again = read_wav_layout(dst)
        if again.data_bytes != nbytes or again.fmt_chunk != layout.fmt_chunk:
            raise PassthroughError(
                "cut WAV failed its check: header does not match the plan"
            )
        if _sha256_range(
            dst, again.data_offset, again.data_offset + nbytes
        ) != _sha256_range(src, start, start + nbytes):
            raise PassthroughError(
                "cut WAV failed its check: samples differ from the source"
            )
    return PassthroughCut(
        "pcm",
        rate,
        sync_ms,
        dst if rewrite else None,
        total,
        first,
        total - first - keep,
        exact // rate,
        overrun,
        NS // rate,
    )


# ---------------------------------------------------------------------------
# Opus (Ogg)
# ---------------------------------------------------------------------------


def _cut_opus(
    src: Path, delay_ns: int, video_end_ns: int | None, dst: Path
) -> PassthroughCut:
    try:
        stream = read_ogg_opus(src)
    except OggOpusError as e:
        raise PassthroughError(str(e)) from e
    rate = OPUS_RATE
    starts = [0]
    for packet in stream.packets:
        starts.append(starts[-1] + opus_packet_samples(packet))
    # Each page's granule must count the samples decoded so far from 0.
    for i, g in enumerate(stream.granules[:-1]):
        if g >= 0 and g != starts[i + 1]:
            raise PassthroughError(
                f"Ogg granule at packet {i} does not match its samples"
            )
    pre_skip = stream.pre_skip
    audible = stream.final_granule - pre_skip
    if audible <= 0:
        raise PassthroughError("no audible samples")

    first = 0 if delay_ns >= 0 else _ceil_div(-delay_ns * rate, NS)
    if first >= audible:
        raise PassthroughError("the delay removes the whole track")
    exact = first * NS + delay_ns * rate
    sync_ms = _round_ms(exact, rate * NS)
    keep = audible - first
    overrun: int | None = None
    if video_end_ns is not None:
        limit = video_end_ns * rate - sync_ms * 1_000_000 * rate
        if limit <= 0:
            raise PassthroughError("no audio is left before the video end")
        keep = min(keep, _ceil_div(limit, NS))
        overrun = (keep * NS - limit) // rate
        if overrun < 0:  # the track ends before the video end: nothing to trim
            overrun = None
    rewrite = first > 0 or keep < audible - first
    if rewrite:
        target = first + pre_skip  # decoded-sample index of the first kept sample
        floor = max(target - _OPUS_PREROLL, 0)
        j = max(i for i in range(len(stream.packets)) if starts[i] <= floor)
        new_pre_skip = target - starts[j]
        end_decoded = target + keep
        stop = next(
            (i for i in range(len(starts)) if starts[i] >= end_decoded),
            len(stream.packets),
        )
        packets = stream.packets[j:stop]
        try:
            write_ogg_opus(dst, stream, packets, new_pre_skip, new_pre_skip + keep)
            again = read_ogg_opus(dst)
        except OggOpusError as e:
            raise PassthroughError(str(e)) from e
        if (
            again.packets != packets
            or again.pre_skip != new_pre_skip
            or again.final_granule - again.pre_skip != keep
        ):
            raise PassthroughError(
                "cut Opus failed its check: packets or granules differ"
            )
    return PassthroughCut(
        "opus",
        rate,
        sync_ms,
        dst if rewrite else None,
        audible,
        first,
        audible - first - keep,
        exact // rate,
        overrun,
        NS // rate,
    )


# ---------------------------------------------------------------------------


def cut_passthrough(
    kind: PassthroughKind,
    src: Path,
    delay_ns: int,
    video_end_ns: int | None,
    dst: Path,
    remove_dialnorm: bool = False,
) -> PassthroughCut:
    """Plan, write and check the cut of one extracted track.

    ``delay_ns`` is the track's exact delay; ``video_end_ns`` the video end on
    the output timeline, or None for no end trim. ``dst`` is written only when
    something changes. Raises PassthroughError when the track can't be cut safely.
    """
    if kind == "pcm":
        return _cut_pcm(src, delay_ns, video_end_ns, dst)
    if kind == "opus":
        return _cut_opus(src, delay_ns, video_end_ns, dst)
    return _cut_frames(
        kind, src, delay_ns, video_end_ns, dst, remove_dialnorm and kind == "ac3"
    )
