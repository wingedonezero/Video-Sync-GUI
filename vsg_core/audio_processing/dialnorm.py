# vsg_core/audio_processing/dialnorm.py
"""Dialog normalization removal for AC-3 / E-AC-3, done by the app.

This is the same header edit as mkvmerge's ``--remove-dialog-normalization-gain``
(MKVToolNix common/ac3.cpp ``remove_dialog_normalization_gain_impl``): set
``dialnorm`` (and ``dialnorm2`` for dual mono) to 31, the level at which a
decoder applies no attenuation, then rewrite CRC1 (AC-3 only) and CRC2. When
the new CRC2 would read as a sync word, the ``crcrsv`` bit is set and CRC2
recomputed. Doing it before the mux means the MKV holds exactly the bytes the
app wrote, so the post-mux check can compare them byte for byte.

TrueHD is deliberately not handled: editing its dialnorm breaks Atmos data
(Doom9 eac3to reports), and the app never asks for it. Nor does it ask for
E-AC-3 Atmos (JOC): after this exact edit receivers play it as plain DD+
(Doom9 "Remove dialog norm. from DD+ w/ Atmos?", Denon X6500 and another).
"""

from __future__ import annotations

import numpy as np

REMOVED_LEVEL = 31
_SYNC_WORD = 0x0B77
_CRC16_POLY = (1 << 0) | (1 << 2) | (1 << 15) | (1 << 16)  # x^16 + x^15 + x^2 + 1


def _crc16_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) if c & 0x8000 else (c << 1)
        table.append(c & 0xFFFF)
    return tuple(table)


_CRC16 = _crc16_table()


def crc16(data: bytes | bytearray | memoryview) -> int:
    """CRC-16, polynomial 0x8005, MSB first, initial value 0 (A/52 CRC)."""
    c = 0
    for x in data:
        c = ((c << 8) & 0xFFFF) ^ _CRC16[(c >> 8) ^ x]
    return c


def _mul_poly(a: int, b: int, poly: int) -> int:
    c = 0
    while a:
        if a & 1:
            c ^= b
        a >>= 1
        b <<= 1
        if b & (1 << 16):
            b ^= poly
    return c


def _pow_poly(a: int, n: int, poly: int) -> int:
    r = 1
    while n:
        if n & 1:
            r = _mul_poly(r, a, poly)
        a = _mul_poly(a, a, poly)
        n >>= 1
    return r


def ac3_crc1(frame: bytes | bytearray) -> int:
    """CRC1 of an AC-3 frame: the value that makes the CRC of its first 5/8 zero."""
    words = len(frame) >> 1
    words_58 = (words >> 1) + (words >> 3)
    crc = crc16(memoryview(frame)[4 : 2 * words_58])
    inverse = _pow_poly(_CRC16_POLY >> 1, 16 * words_58 - 16, _CRC16_POLY)
    return _mul_poly(inverse, crc, _CRC16_POLY)


def ac3_crc2(frame: bytes | bytearray) -> int:
    return crc16(memoryview(frame)[2 : len(frame) - 2])


def checksums_ok(frame: bytes | bytearray, is_eac3: bool) -> bool:
    """Both stored CRCs of one AC-3 / E-AC-3 frame are correct."""
    if not is_eac3 and int.from_bytes(frame[2:4], "big") != ac3_crc1(frame):
        return False
    return int.from_bytes(frame[-2:], "big") == ac3_crc2(frame)


class _BitReader:
    def __init__(self, data: bytes | bytearray) -> None:
        self._data = data
        self.pos = 0

    def get(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self._data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v


def dialnorm_positions(frame: bytes | bytearray) -> tuple[bool, list[int]]:
    """(is E-AC-3, bit positions of dialnorm[, dialnorm2]) as mkvmerge finds them."""
    bsid = frame[5] >> 3
    r = _BitReader(frame)
    r.pos = 16
    if bsid <= 8:  # AC-3
        r.get(16)  # crc1
        r.get(2)  # fscod
        r.get(6)  # frmsizecod
        r.get(5)  # bsid
        r.get(3)  # bsmod
        acmod = r.get(3)
        if (acmod & 1) and acmod != 1:
            r.get(2)  # cmixlev
        if acmod & 4:
            r.get(2)  # surmixlev
        if acmod == 2:
            r.get(2)  # dsurmod
        r.get(1)  # lfeon
        positions = [r.pos]
        r.get(5)
        if r.get(1):  # compre
            r.get(8)
        if r.get(1):  # langcode
            r.get(8)
        if r.get(1):  # audprodie
            r.get(7)
        if acmod == 0:
            positions.append(r.pos)
        return False, positions
    if 10 < bsid <= 16:  # E-AC-3
        r.get(2)  # strmtyp
        r.get(3)  # substreamid
        r.get(11)  # frmsiz
        r.get(2)  # fscod
        r.get(2)  # fscod2 / numblkscod
        acmod = r.get(3)
        r.get(1)  # lfeon
        r.get(5)  # bsid
        positions = [r.pos]
        r.get(5)
        if r.get(1):  # compre
            r.get(8)
        if acmod == 0:
            positions.append(r.pos)
        return True, positions
    raise ValueError(f"not an AC-3 / E-AC-3 frame (bsid {bsid})")


def get_bits(data: bytes | bytearray, bit: int, n: int) -> int:
    v = 0
    for i in range(n):
        p = bit + i
        v = (v << 1) | ((data[p >> 3] >> (7 - (p & 7))) & 1)
    return v


def _put_bits(data: bytearray, bit: int, n: int, value: int) -> None:
    for i in range(n):
        p = bit + i
        mask = 1 << (7 - (p & 7))
        if (value >> (n - 1 - i)) & 1:
            data[p >> 3] |= mask
        else:
            data[p >> 3] &= ~mask & 0xFF


def remove_dialnorm_frame(frame: bytearray) -> bool:
    """Edit one frame in place; True when it changed."""
    is_eac3, positions = dialnorm_positions(frame)
    if all(get_bits(frame, p, 5) == REMOVED_LEVEL for p in positions):
        return False
    for p in positions:
        _put_bits(frame, p, 5, REMOVED_LEVEL)
    size = len(frame)
    if not is_eac3:
        frame[2:4] = ac3_crc1(frame).to_bytes(2, "big")
    frame[size - 3] &= 0xFE  # crcrsv
    crc2 = ac3_crc2(frame)
    if crc2 == _SYNC_WORD:
        frame[size - 3] |= 0x01
        crc2 = ac3_crc2(frame)
    frame[size - 2 : size] = crc2.to_bytes(2, "big")
    return True


# --- many frames at once ------------------------------------------------------
#
# A film's AC-3 track has ~200,000 frames; computing their CRCs byte by byte in
# Python takes about a minute. The functions below do the same arithmetic for
# all frames of one size at once with numpy, column by column.

_CRC16_NP = np.array(_CRC16, dtype=np.uint16)


def crc16_rows(rows: np.ndarray, start: int, stop: int) -> np.ndarray:
    """``crc16(row[start:stop])`` for every row of a 2-D uint8 array."""
    crc = np.zeros(rows.shape[0], dtype=np.uint16)
    for col in range(start, stop):
        crc = ((crc << 8) & 0xFFFF) ^ _CRC16_NP[(crc >> 8) ^ rows[:, col]]
    return crc


def ac3_crc1_rows(rows: np.ndarray) -> np.ndarray:
    """``ac3_crc1`` for every row (all rows one frame size)."""
    words = rows.shape[1] >> 1
    words_58 = (words >> 1) + (words >> 3)
    crc = crc16_rows(rows, 4, 2 * words_58)
    inverse = _pow_poly(_CRC16_POLY >> 1, 16 * words_58 - 16, _CRC16_POLY)
    # Multiplying by a constant is linear in the bits of crc.
    out = np.zeros_like(crc)
    for bit in range(16):
        term = _mul_poly(inverse, 1 << bit, _CRC16_POLY)
        out ^= np.where((crc >> bit) & 1, np.uint16(term), np.uint16(0))
    return out


def checksums_ok_rows(rows: np.ndarray, is_eac3: bool) -> np.ndarray:
    """``checksums_ok`` for every row (all rows one frame size and type)."""
    size = rows.shape[1]
    stored2 = (rows[:, size - 2].astype(np.uint16) << 8) | rows[:, size - 1]
    ok = crc16_rows(rows, 2, size - 2) == stored2
    if not is_eac3:
        stored1 = (rows[:, 2].astype(np.uint16) << 8) | rows[:, 3]
        ok &= ac3_crc1_rows(rows) == stored1
    return ok


def _rewrite_checksums(rows: np.ndarray, is_eac3: bool) -> None:
    """CRC1 (AC-3), crcrsv and CRC2 of every row, in place, as mkvmerge writes them."""
    size = rows.shape[1]
    if not is_eac3:
        crc1 = ac3_crc1_rows(rows)
        rows[:, 2] = crc1 >> 8
        rows[:, 3] = crc1 & 0xFF
    rows[:, size - 3] &= 0xFE  # crcrsv
    crc2 = crc16_rows(rows, 2, size - 2)
    sync = crc2 == _SYNC_WORD
    if sync.any():
        rows[sync, size - 3] |= 0x01
        crc2[sync] = crc16_rows(rows[sync], 2, size - 2)
    rows[:, size - 2] = crc2 >> 8
    rows[:, size - 1] = crc2 & 0xFF


def remove_dialnorm_frames(frames: list[bytearray]) -> int:
    """``remove_dialnorm_frame`` for many frames at once, in place.

    Returns how many changed. The bit edits are the same; the CRCs are
    computed per group of equal-size frames with numpy.
    """
    groups: dict[tuple[int, bool], list[int]] = {}
    for i, frame in enumerate(frames):
        is_eac3, positions = dialnorm_positions(frame)
        if all(get_bits(frame, p, 5) == REMOVED_LEVEL for p in positions):
            continue
        for p in positions:
            _put_bits(frame, p, 5, REMOVED_LEVEL)
        groups.setdefault((len(frame), is_eac3), []).append(i)
    for (size, is_eac3), idx in groups.items():
        rows = np.frombuffer(b"".join(frames[i] for i in idx), dtype=np.uint8)
        rows = rows.reshape(len(idx), size).copy()
        _rewrite_checksums(rows, is_eac3)
        for row, i in zip(rows, idx, strict=True):
            frames[i][:] = row.tobytes()
    return sum(len(idx) for idx in groups.values())
