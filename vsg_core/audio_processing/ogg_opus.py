# vsg_core/audio_processing/ogg_opus.py
"""Minimal Ogg Opus reader/writer (RFC 3533 pages, RFC 7845 mapping).

Opus can be cut to the exact sample without re-encoding: drop whole packets,
then set the header's pre-skip to the samples the decoder must discard at the
start (RFC 7845 §4.2) and the last page's granule position to where playback
must stop (§4.4). mkvmerge turns the pre-skip into CodecDelay and the end
granule into DiscardPadding.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

OPUS_RATE = 48000


def _crc_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        table.append(r & 0xFFFFFFFF)
    return tuple(table)


_CRC = _crc_table()


def ogg_crc(data: bytes | bytearray) -> int:
    c = 0
    for x in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ _CRC[((c >> 24) & 0xFF) ^ x]
    return c


def opus_packet_samples(packet: bytes) -> int:
    """Samples at 48 kHz in one Opus packet (RFC 6716 §3.1: TOC + frame count)."""
    toc = packet[0]
    config = toc >> 3
    if config < 12:
        frame = (480, 960, 1920, 2880)[config & 3]
    elif config < 16:
        frame = (480, 960)[config & 1]
    else:
        frame = (120, 240, 480, 960)[config & 3]
    code = toc & 3
    frames = 1 if code == 0 else 2 if code in (1, 2) else packet[1] & 0x3F
    return frame * frames


@dataclass(frozen=True, slots=True)
class OggOpus:
    """One logical Opus stream: headers, audio packets and their page granules."""

    head: bytes
    tags: bytes
    serial: int
    packets: tuple[bytes, ...]
    # Granule of the page each packet ends on, or -1 when another packet ends
    # later on the same page.
    granules: tuple[int, ...]

    @property
    def pre_skip(self) -> int:
        return int(struct.unpack_from("<H", self.head, 10)[0])

    @property
    def final_granule(self) -> int:
        return next((g for g in reversed(self.granules) if g >= 0), 0)


class OggOpusError(ValueError):
    pass


def read_ogg_opus(path: Path) -> OggOpus:
    data = path.read_bytes()
    pos = 0
    serial: int | None = None
    packets: list[bytes] = []
    granules: list[int] = []
    partial = bytearray()
    while pos < len(data):
        if data[pos : pos + 4] != b"OggS":
            raise OggOpusError(f"no Ogg page at byte {pos}")
        granule, page_serial = struct.unpack_from("<qI", data, pos + 6)
        if serial is None:
            serial = page_serial
        elif page_serial != serial:
            raise OggOpusError("more than one logical stream (chained Ogg)")
        nseg = data[pos + 26]
        lacing = data[pos + 27 : pos + 27 + nseg]
        body = pos + 27 + nseg
        ended: list[bytes] = []
        for lv in lacing:
            partial += data[body : body + lv]
            body += lv
            if lv < 255:
                ended.append(bytes(partial))
                partial.clear()
        for i, packet in enumerate(ended):
            packets.append(packet)
            granules.append(granule if i == len(ended) - 1 else -1)
        pos = body
    if partial:
        raise OggOpusError("stream ends inside a packet")
    if len(packets) < 2 or not packets[0].startswith(b"OpusHead"):
        raise OggOpusError("not an Ogg Opus stream")
    if not packets[1].startswith(b"OpusTags"):
        raise OggOpusError("OpusTags header missing")
    assert serial is not None
    return OggOpus(
        packets[0], packets[1], serial, tuple(packets[2:]), tuple(granules[2:])
    )


def _page(flags: int, granule: int, serial: int, seq: int, packet: bytes) -> bytes:
    lacing = bytearray()
    n = len(packet)
    while n >= 255:
        lacing.append(255)
        n -= 255
    lacing.append(n)
    header = b"OggS" + bytes([0, flags]) + struct.pack("<qII", granule, serial, seq)
    page = bytearray(
        header + b"\0\0\0\0" + bytes([len(lacing)]) + bytes(lacing) + packet
    )
    struct.pack_into("<I", page, 22, ogg_crc(page))
    return bytes(page)


def write_ogg_opus(
    path: Path,
    stream: OggOpus,
    packets: tuple[bytes, ...],
    pre_skip: int,
    end_granule: int,
) -> None:
    """One packet per page; each granule = decoded samples so far (RFC 7845 §4.3),
    the last page's = ``end_granule`` (end trim, §4.4)."""
    if not 0 <= pre_skip <= 0xFFFF:
        raise OggOpusError(f"pre-skip {pre_skip} does not fit in 16 bits")
    head = bytearray(stream.head)
    struct.pack_into("<H", head, 10, pre_skip)
    out = bytearray(_page(2, 0, stream.serial, 0, bytes(head)))
    out += _page(0, 0, stream.serial, 1, stream.tags)
    granule = 0
    for i, packet in enumerate(packets):
        granule += opus_packet_samples(packet)
        last = i == len(packets) - 1
        out += _page(
            4 if last else 0,
            end_granule if last else granule,
            stream.serial,
            2 + i,
            packet,
        )
    path.write_bytes(bytes(out))
