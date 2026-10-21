# vsg_core/audio_processing/verify.py
"""Prove a finished FLAC is exactly what its edit plan says, streaming.

1. ``scan_expected`` decodes the *source* once and hashes the samples the plan
   should produce (source slices + zeros, end cap applied). It also counts the
   source, which the tags need before encoding.
2. ``check_output`` decodes the *FLAC*, hashes it the same way and compares,
   then checks the FLAC header (STREAMINFO sample total and MD5, computed here
   from the decoded samples in FLAC's canonical byte form) and the stream
   format (rate, channels, bit depth, channel layout).

Both decodes go to signed 32-bit, so equal hashes mean equal sample values.
Memory stays flat: the tracks are streamed in chunks.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .encoder import output_layout
from .types import EditPlan, Silence, SourceFormat, Take

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from vsg_core.io.runner import CommandRunner

_ZERO_CHUNK_SAMPLES = 1 << 16


def _decode_cmd(path: Path, stream_index: int) -> list[str]:
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        f"0:a:{stream_index}",
        "-f",
        "s32le",
        "-c:a",
        "pcm_s32le",
        "-",
    ]


class _FrameReader:
    """Reads whole sample frames (all channels of one sample) from byte chunks."""

    def __init__(self, chunks: Iterator[bytes], frame_bytes: int) -> None:
        self._chunks = chunks
        self._frame_bytes = frame_bytes
        self._buf = b""
        self.position = 0  # frames consumed so far
        self._eof = False

    def _fill(self, want_bytes: int) -> None:
        while len(self._buf) < want_bytes and not self._eof:
            nxt = next(self._chunks, None)
            if nxt is None:
                self._eof = True
            else:
                self._buf += nxt

    def read(self, frames: int | None) -> Iterator[bytes]:
        """Yield up to ``frames`` frames (``None`` = to the end) in chunks."""
        remaining = frames
        while remaining is None or remaining > 0:
            self._fill(self._frame_bytes)
            usable = len(self._buf) - len(self._buf) % self._frame_bytes
            if usable == 0:
                return
            take = (
                usable
                if remaining is None
                else min(usable, remaining * self._frame_bytes)
            )
            out, self._buf = self._buf[:take], self._buf[take:]
            n = take // self._frame_bytes
            self.position += n
            if remaining is not None:
                remaining -= n
            yield out

    def drain(self) -> None:
        for _ in self.read(None):
            pass
        if len(self._buf) % self._frame_bytes:
            raise RuntimeError("decoded stream ended mid-frame")


@dataclass(frozen=True, slots=True)
class ExpectedOutput:
    source_samples: int  # per channel, whole decoded source
    output_samples: int  # per channel, what the plan yields
    sha256: str  # of the expected decoded output as s32le


def scan_expected(
    source: Path,
    stream_index: int,
    fmt: SourceFormat,
    plan: EditPlan,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> ExpectedOutput:
    frame_bytes = 4 * fmt.channels
    reader = _FrameReader(
        runner.stream_binary(_decode_cmd(source, stream_index), tool_paths), frame_bytes
    )
    digest = hashlib.sha256()
    emitted = 0
    cap = plan.max_output_samples

    def emit(data: bytes) -> None:
        nonlocal emitted
        if cap is not None:
            room = cap - emitted
            if room <= 0:
                return
            data = data[: room * frame_bytes]
        digest.update(data)
        emitted += len(data) // frame_bytes

    for op in plan.ops:
        if isinstance(op, Silence):
            left = op.samples
            while left > 0:
                n = min(left, _ZERO_CHUNK_SAMPLES)
                emit(bytes(n * frame_bytes))
                left -= n
            continue
        assert isinstance(op, Take)
        for _ in reader.read(op.start - reader.position):  # skip to the take
            pass
        if reader.position < op.start:
            break  # source ended before this take starts
        want = None if op.end is None else op.end - op.start
        for data in reader.read(want):
            emit(data)
    reader.drain()  # count the whole source (and catch truncated decodes)
    return ExpectedOutput(
        source_samples=reader.position,
        output_samples=emitted,
        sha256=digest.hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class StreamInfo:
    sample_rate: int
    channels: int
    bits: int
    total_samples: int
    md5: bytes


def read_streaminfo(path: Path) -> StreamInfo:
    with path.open("rb") as f:
        head = f.read(42)
    if head[:4] != b"fLaC" or (head[4] & 0x7F) != 0:
        raise ValueError(f"{path} does not start with a FLAC STREAMINFO block")
    i = head[8:42]
    rate = (i[10] << 12) | (i[11] << 4) | (i[12] >> 4)
    channels = ((i[12] >> 1) & 0x07) + 1
    bits = (((i[12] & 0x01) << 4) | (i[13] >> 4)) + 1
    total = ((i[13] & 0x0F) << 32) | struct.unpack_from(">I", i, 14)[0]
    return StreamInfo(rate, channels, bits, total, bytes(i[18:34]))


def canonical_bytes(s32_frames: bytes, bits: int) -> bytes:
    """FLAC's MD5 input for samples decoded as left-aligned s32: each sample as a
    signed little-endian integer of ceil(bits/8) bytes, channels interleaved."""
    values = np.frombuffer(s32_frames, dtype="<i4") >> (32 - bits)
    width = (bits + 7) // 8
    if width == 2:
        return values.astype("<i2").tobytes()
    if width == 3:
        return values.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    raise ValueError(f"unsupported bit depth {bits}")


@dataclass(frozen=True, slots=True)
class OutputCheck:
    output_samples: int
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_output(
    out: Path,
    expected: ExpectedOutput,
    fmt: SourceFormat,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> OutputCheck:
    problems: list[str] = []
    frame_bytes = 4 * fmt.channels
    reader = _FrameReader(
        runner.stream_binary(_decode_cmd(out, 0), tool_paths), frame_bytes
    )
    digest, md5 = hashlib.sha256(), hashlib.md5()
    for data in reader.read(None):
        digest.update(data)
        md5.update(canonical_bytes(data, fmt.bits))
    reader.drain()
    count = reader.position

    if count != expected.output_samples:
        problems.append(f"decoded {count} samples, plan says {expected.output_samples}")
    if digest.hexdigest() != expected.sha256:
        problems.append("decoded samples differ from the source/edit plan")

    info = read_streaminfo(out)
    if info.total_samples != count:
        problems.append(
            f"STREAMINFO says {info.total_samples} samples, decoded {count}"
        )
    if info.md5 != md5.digest():
        problems.append("STREAMINFO MD5 does not match the decoded audio")
    if (info.sample_rate, info.channels, info.bits) != (
        fmt.sample_rate,
        fmt.channels,
        fmt.bits,
    ):
        problems.append(
            f"format {info.sample_rate} Hz/{info.channels} ch/{info.bits}-bit, "
            f"source {fmt.sample_rate} Hz/{fmt.channels} ch/{fmt.bits}-bit"
        )

    probed = runner.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=channel_layout",
            "-of",
            "json",
            str(out),
        ],
        tool_paths,
    )
    layout = None
    if isinstance(probed, str):
        streams = json.loads(probed).get("streams") or []
        layout = streams[0].get("channel_layout") if streams else None
    want = output_layout(fmt)
    if layout != want:
        problems.append(f"channel layout reads back as {layout!r}, expected {want!r}")
    return OutputCheck(output_samples=count, problems=problems)
