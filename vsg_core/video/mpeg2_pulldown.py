# vsg_core/video/mpeg2_pulldown.py
"""MPEG-2 soft pulldown (3:2 telecine) detection and lossless removal.

This module operates directly on MPEG-2 elementary stream bytes.
It scans for picture coding extensions and sequence headers, validates
that the stream contains true soft pulldown, and surgically flips the
repeat_first_field / top_field_first bits to remove it.

No video data is modified — only header flags and frame rate metadata.
The output is byte-identical to the input except for the flipped bits.

Reference implementations:
- TsMuxeR (justdan96/tsMuxer): mpeg2StreamReader.cpp, mpegVideo.cpp
- FFmpeg mpeg2_metadata BSF ivtc patch
- DGIndex (DGMPGDec): gethdr.cpp picture_coding_extension parsing

ISO 13818-2 (MPEG-2 Video) section 6.2.3.1 defines the picture coding
extension layout used for bit-offset calculations.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 - used at runtime for file I/O

# =============================================================================
# MPEG-2 start codes (ISO 13818-2 Table 6-1)
# =============================================================================

# 3-byte prefix shared by all MPEG-2 start codes
_START_CODE_PREFIX = b"\x00\x00\x01"

# Start code suffixes (the byte after the prefix)
_SEQUENCE_HEADER_CODE: int = 0xB3
_EXTENSION_START_CODE: int = 0xB5

# Extension start code identifiers (4-bit field after extension start code)
_PICTURE_CODING_EXT_ID: int = 0x08
_SEQUENCE_EXT_ID: int = 0x01

# =============================================================================
# Standard MPEG-2 frame rates (ISO 13818-2 Table 6-4)
# Index 0 is forbidden; indices 1-8 are defined.
# =============================================================================

_FRAME_RATES: dict[int, float] = {
    1: 24000.0 / 1001.0,  # 23.976 — NTSC film
    2: 24.0,
    3: 25.0,  # PAL
    4: 30000.0 / 1001.0,  # 29.970 — NTSC video
    5: 30.0,
    6: 50.0,
    7: 60000.0 / 1001.0,  # 59.940
    8: 60.0,
}

# After removing pulldown: source frame_rate_index → target frame_rate_index
_PULLDOWN_TARGET_RATE: dict[int, int] = {
    4: 1,  # 29.97 → 23.976
    5: 2,  # 30.0 → 24.0
}


# =============================================================================
# Data structures
# =============================================================================


@dataclass(frozen=True, slots=True)
class PictureCodingInfo:
    """Parsed fields from one MPEG-2 picture coding extension.

    Byte offsets are absolute positions within the elementary stream file.
    Bit offsets for RFF/TFF are relative to the first byte after the
    extension_start_code (0x000001B5), i.e. the byte containing the
    4-bit extension_start_code_identifier.
    """

    ext_data_offset: int  # Absolute byte offset of first byte after 00 00 01 B5
    repeat_first_field: bool
    top_field_first: bool
    progressive_frame: bool
    picture_structure: int  # 3 = frame, 1 = top field, 2 = bottom field
    frame_pred_frame_dct: bool

    # Absolute byte offset + bit-within-byte for surgical modification
    rff_byte_offset: int  # Byte in file containing the RFF bit
    rff_bit_mask: int  # Bitmask to clear RFF (AND with this to clear)
    tff_byte_offset: int  # Byte in file containing the TFF bit
    tff_bit_mask: int  # Bitmask to clear TFF


@dataclass(frozen=True, slots=True)
class SequenceHeaderInfo:
    """Parsed fields from an MPEG-2 sequence header.

    The frame_rate_index occupies the lower 4 bits of the byte at
    offset (start_code_offset + 7) per ISO 13818-2 section 6.2.2.1.
    Actually it's the lower 4 bits of byte at start_code_offset + 3
    from the sequence header start code (00 00 01 B3).
    Layout: horizontal_size(12) + vertical_size(12) + aspect_ratio(4) + frame_rate_index(4)
    That's 32 bits = 4 bytes after the start code suffix byte.
    So frame_rate_index is the lower 4 bits of byte at offset+7
    (offset = position of 0x00 in start code, +3 for B3, +4 for the fields).
    """

    start_code_offset: int  # Absolute byte offset of 0x00 in 00 00 01 B3
    frame_rate_index: int
    frame_rate_byte_offset: (
        int  # Absolute byte offset of byte containing frame_rate_index
    )


@dataclass(frozen=True, slots=True)
class SequenceExtInfo:
    """Parsed fields from an MPEG-2 sequence extension."""

    ext_data_offset: int
    progressive_sequence: bool


@dataclass(frozen=True, slots=True)
class PulldownScanResult:
    """Result of scanning an MPEG-2 ES for soft pulldown."""

    has_pulldown: bool  # At least one frame has RFF set
    is_safe_to_remove: bool  # All safety checks passed
    total_pictures: int
    rff_count: int  # Frames with repeat_first_field set
    progressive_count: int  # Frames where progressive_frame == 1
    non_progressive_count: int  # Frames where progressive_frame != 1
    progressive_pct: float  # Percentage of progressive frames (0-100)
    field_picture_count: int  # Frames where picture_structure != 3
    original_frame_rate_index: int
    target_frame_rate_index: int | None
    reason: str  # Human-readable explanation if not safe
    pictures: list[PictureCodingInfo]
    sequence_headers: list[SequenceHeaderInfo]
    sequence_extensions: list[SequenceExtInfo]


@dataclass(frozen=True, slots=True)
class PulldownRemovalResult:
    """Result of a pulldown removal operation."""

    success: bool
    output_path: Path
    pictures_modified: int
    sequence_headers_modified: int
    original_rate: float  # e.g., 29.97
    new_rate: float  # e.g., 23.976
    reason: str  # Error explanation if not successful


# =============================================================================
# Start code scanning
# =============================================================================


def _find_start_codes(data: bytes | bytearray) -> list[int]:
    """Find all MPEG-2 start code positions in the stream.

    Returns a list of byte offsets where 0x000001 sequences begin.
    This is the hot loop — kept simple for speed on large files.
    """
    positions: list[int] = []
    search_from = 0
    prefix = _START_CODE_PREFIX
    data_len = len(data)

    while search_from < data_len - 3:
        pos = data.find(prefix, search_from, data_len)
        if pos == -1:
            break
        positions.append(pos)
        search_from = pos + 3  # Skip past the 00 00 01

    return positions


# =============================================================================
# Picture Coding Extension parsing (ISO 13818-2 section 6.2.3.1)
# =============================================================================
#
# Layout of picture_coding_extension() after extension_start_code (00 00 01 B5):
#
# Byte 0 (relative to ext_data_start):
#   [7:4] extension_start_code_identifier = 0x8 (4 bits)
#   [3:0] f_code[0][0] (4 bits)
#
# Byte 1:
#   [7:4] f_code[0][1] (4 bits)
#   [3:0] f_code[1][0] (4 bits)
#
# Byte 2:
#   [7:4] f_code[1][1] (4 bits)
#   [3:2] intra_dc_precision (2 bits)
#   [1:0] picture_structure (2 bits, high part)
#     Actually: picture_structure is 2 bits spanning byte boundary...
#
# Let me lay this out bit by bit from the ext_data_start:
#   Bits  0-3:   extension_start_code_identifier (0x8)
#   Bits  4-7:   f_code[0][0]
#   Bits  8-11:  f_code[0][1]
#   Bits 12-15:  f_code[1][0]
#   Bits 16-19:  f_code[1][1]
#   Bits 20-21:  intra_dc_precision
#   Bits 22-23:  picture_structure
#   Bit  24:     top_field_first          <-- TFF
#   Bit  25:     frame_pred_frame_dct
#   Bit  26:     concealment_motion_vectors
#   Bit  27:     q_scale_type
#   Bit  28:     intra_vlc_format
#   Bit  29:     alternate_scan
#   Bit  30:     repeat_first_field       <-- RFF
#   Bit  31:     chroma_420_type
#   Bit  32:     progressive_frame        <-- PF
#   Bit  33:     composite_display_flag


def _parse_picture_coding_ext(
    data: bytes | bytearray, ext_data_offset: int
) -> PictureCodingInfo | None:
    """Parse a picture coding extension starting at ext_data_offset.

    ext_data_offset points to the first byte after 00 00 01 B5 —
    the byte whose upper 4 bits hold extension_start_code_identifier.

    Returns None if there aren't enough bytes to parse.
    """
    # Need at least 5 bytes from ext_data_offset to read through bit 33
    if ext_data_offset + 5 > len(data):
        return None

    # Check extension ID (upper 4 bits of first byte)
    ext_id = (data[ext_data_offset] >> 4) & 0x0F
    if ext_id != _PICTURE_CODING_EXT_ID:
        return None

    # Read bytes we need (relative to ext_data_offset)
    # Bytes 0-1 hold ext_id + f_codes — not needed for our fields
    b2 = data[
        ext_data_offset + 2
    ]  # f_code[1][1] + intra_dc_precision + picture_structure(hi)
    b3 = data[ext_data_offset + 3]  # TFF + frame_pred_frame_dct + ... + RFF + chroma420
    b4 = data[
        ext_data_offset + 4
    ]  # progressive_frame (bit 0 = bit 32) + composite_display

    # picture_structure: bits 22-23 from ext_data_start
    # That's the lower 2 bits of byte 2
    picture_structure = b2 & 0x03

    # top_field_first: bit 24 = bit 7 of byte 3
    top_field_first = bool((b3 >> 7) & 0x01)

    # frame_pred_frame_dct: bit 25 = bit 6 of byte 3
    frame_pred_frame_dct = bool((b3 >> 6) & 0x01)

    # repeat_first_field: bit 30 = bit 1 of byte 3
    repeat_first_field = bool((b3 >> 1) & 0x01)

    # progressive_frame: bit 32 = bit 7 of byte 4
    progressive_frame = bool((b4 >> 7) & 0x01)

    # Pre-compute the byte offsets and masks for surgical bit clearing
    # TFF is bit 7 of byte 3 (absolute: ext_data_offset + 3)
    tff_byte_offset = ext_data_offset + 3
    tff_bit_mask = ~(1 << 7) & 0xFF  # 0b01111111 = 0x7F

    # RFF is bit 1 of byte 3 (absolute: ext_data_offset + 3)
    rff_byte_offset = ext_data_offset + 3
    rff_bit_mask = ~(1 << 1) & 0xFF  # 0b11111101 = 0xFD

    return PictureCodingInfo(
        ext_data_offset=ext_data_offset,
        repeat_first_field=repeat_first_field,
        top_field_first=top_field_first,
        progressive_frame=progressive_frame,
        picture_structure=picture_structure,
        frame_pred_frame_dct=frame_pred_frame_dct,
        rff_byte_offset=rff_byte_offset,
        rff_bit_mask=rff_bit_mask,
        tff_byte_offset=tff_byte_offset,
        tff_bit_mask=tff_bit_mask,
    )


# =============================================================================
# Sequence Header parsing (ISO 13818-2 section 6.2.2.1)
# =============================================================================
#
# Layout after sequence_header_code (00 00 01 B3):
#   Bits 0-11:  horizontal_size_value (12 bits)
#   Bits 12-23: vertical_size_value (12 bits)
#   Bits 24-27: aspect_ratio_information (4 bits)
#   Bits 28-31: frame_rate_code (4 bits)     <-- this is frame_rate_index
#
# So frame_rate_code is the lower 4 bits of byte 3 (0-indexed from the
# first byte after B3, which is byte offset start_code_offset + 4 + 3 = +7).


def _parse_sequence_header(
    data: bytes | bytearray, sc_offset: int
) -> SequenceHeaderInfo | None:
    """Parse a sequence header starting at sc_offset (position of 0x00 in 00 00 01 B3).

    Returns None if there aren't enough bytes.
    """
    # The data after 00 00 01 B3 starts at sc_offset + 4
    header_start = sc_offset + 4
    if header_start + 4 > len(data):
        return None

    # frame_rate_code is the lower 4 bits of byte 3 after the start code suffix
    frame_rate_byte_offset = header_start + 3
    frame_rate_index = data[frame_rate_byte_offset] & 0x0F

    return SequenceHeaderInfo(
        start_code_offset=sc_offset,
        frame_rate_index=frame_rate_index,
        frame_rate_byte_offset=frame_rate_byte_offset,
    )


# =============================================================================
# Sequence Extension parsing (ISO 13818-2 section 6.2.2.3)
# =============================================================================
#
# Layout after extension_start_code with ID = 0x1:
#   Bits 0-3:   extension_start_code_identifier = 0x1
#   Bits 4-11:  profile_and_level_indication (8 bits)
#   Bit  12:    progressive_sequence           <-- what we need


def _parse_sequence_ext(
    data: bytes | bytearray, ext_data_offset: int
) -> SequenceExtInfo | None:
    """Parse a sequence extension starting at ext_data_offset."""
    if ext_data_offset + 2 > len(data):
        return None

    ext_id = (data[ext_data_offset] >> 4) & 0x0F
    if ext_id != _SEQUENCE_EXT_ID:
        return None

    # progressive_sequence is bit 12 from ext_data_start
    # That's bit 4 of byte 1
    b1 = data[ext_data_offset + 1]
    progressive_sequence = bool((b1 >> 3) & 0x01)

    return SequenceExtInfo(
        ext_data_offset=ext_data_offset,
        progressive_sequence=progressive_sequence,
    )


# =============================================================================
# Scan: detect soft pulldown in an MPEG-2 elementary stream
# =============================================================================


def scan_for_pulldown(es_path: Path) -> PulldownScanResult:
    """Scan an MPEG-2 elementary stream for soft 3:2 pulldown.

    Reads the entire file, finds all start codes, and parses picture coding
    extensions and sequence headers to determine if the stream contains
    removable soft pulldown.

    Safety checks (ALL must pass for is_safe_to_remove=True):
    1. At least one sequence header with frame_rate_index 4 (29.97) or 5 (30.0)
    2. At least one picture has repeat_first_field set
    3. >= 90% of pictures have progressive_frame == 1 (allows minor interlaced
       inserts like credits/OP/ED — matches DGIndex "film percentage" concept)
    4. ALL pictures have picture_structure == 3 (frame picture — even interlaced
       DVD content is stored as frame pictures, not field pictures)
    5. RFF percentage among progressive frames is consistent with 3:2 pattern

    Note: frame_pred_frame_dct is NOT checked. TsMuxeR does not check it,
    and non-progressive frames correctly have it set to 0. Checking it would
    reject valid mixed content.

    RFF is cleared unconditionally on ALL frames during removal (matching
    TsMuxeR behavior). The few non-progressive frames get uniform timing
    alongside the progressive majority.
    """
    data = es_path.read_bytes()
    start_codes = _find_start_codes(data)

    pictures: list[PictureCodingInfo] = []
    sequence_headers: list[SequenceHeaderInfo] = []
    sequence_extensions: list[SequenceExtInfo] = []

    for sc_pos in start_codes:
        suffix = data[sc_pos + 3]

        if suffix == _SEQUENCE_HEADER_CODE:
            header = _parse_sequence_header(data, sc_pos)
            if header is not None:
                sequence_headers.append(header)

        elif suffix == _EXTENSION_START_CODE:
            ext_data_offset = sc_pos + 4
            if ext_data_offset >= len(data):
                continue

            ext_id = (data[ext_data_offset] >> 4) & 0x0F

            if ext_id == _PICTURE_CODING_EXT_ID:
                pic = _parse_picture_coding_ext(data, ext_data_offset)
                if pic is not None:
                    pictures.append(pic)

            elif ext_id == _SEQUENCE_EXT_ID:
                seq_ext = _parse_sequence_ext(data, ext_data_offset)
                if seq_ext is not None:
                    sequence_extensions.append(seq_ext)

    # --- Pre-compute counts ---
    total = len(pictures)
    non_progressive = sum(1 for p in pictures if not p.progressive_frame)
    progressive_count = total - non_progressive
    progressive_pct = (progressive_count / total * 100.0) if total > 0 else 0.0

    # --- Validation ---

    def _fail(reason: str) -> PulldownScanResult:
        """Build a 'not safe' result with the given reason."""
        return PulldownScanResult(
            has_pulldown=any(p.repeat_first_field for p in pictures),
            is_safe_to_remove=False,
            total_pictures=total,
            rff_count=sum(1 for p in pictures if p.repeat_first_field),
            progressive_count=progressive_count,
            non_progressive_count=non_progressive,
            progressive_pct=progressive_pct,
            field_picture_count=sum(1 for p in pictures if p.picture_structure != 3),
            original_frame_rate_index=sequence_headers[0].frame_rate_index
            if sequence_headers
            else 0,
            target_frame_rate_index=None,
            reason=reason,
            pictures=pictures,
            sequence_headers=sequence_headers,
            sequence_extensions=sequence_extensions,
        )

    # Check 1: Must have sequence headers
    if not sequence_headers:
        return _fail("No MPEG-2 sequence headers found")

    # Check 2: Must have pictures
    if not pictures:
        return _fail("No picture coding extensions found")

    # Check 3: Frame rate must be 29.97 or 30.0
    original_rate_idx = sequence_headers[0].frame_rate_index
    if original_rate_idx not in _PULLDOWN_TARGET_RATE:
        rate_str = f"{_FRAME_RATES.get(original_rate_idx, 0):.3f}"
        return _fail(
            f"Frame rate index {original_rate_idx} ({rate_str} fps) "
            f"is not a pulldown source rate (need 29.97 or 30.0)"
        )

    target_rate_idx = _PULLDOWN_TARGET_RATE[original_rate_idx]

    # Check 4: At least one frame must have RFF set
    rff_count = sum(1 for p in pictures if p.repeat_first_field)
    if rff_count == 0:
        return _fail("No frames have repeat_first_field set — no pulldown present")

    # Check 5: >= 90% of frames must be progressive
    # Real DVDs commonly have a small percentage of interlaced inserts
    # (credits, OP/ED, chapter cards) within otherwise progressive film.
    # DGIndex uses ~95% as its "film" threshold; we use 90% to be safe.
    # TsMuxeR has no threshold at all — it's purely user-driven.
    _MIN_PROGRESSIVE_PCT = 90.0
    if progressive_pct < _MIN_PROGRESSIVE_PCT:
        return _fail(
            f"Only {progressive_pct:.1f}% of frames are progressive "
            f"({progressive_count}/{total}). Need >= {_MIN_PROGRESSIVE_PCT:.0f}% "
            f"to confirm this is film content with pulldown, not native interlaced."
        )

    # Check 6: ALL frames must be frame pictures (not field pictures)
    # Even interlaced DVD content is stored as frame pictures (both fields
    # interleaved in one picture). Field pictures are extremely rare on DVD.
    field_pics = sum(1 for p in pictures if p.picture_structure != 3)
    if field_pics > 0:
        return _fail(
            f"{field_pics}/{total} frames are field pictures — "
            f"cannot safely remove pulldown from field-structured content"
        )

    # Check 7: RFF percentage among PROGRESSIVE frames should be consistent
    # with 3:2 pulldown. In a standard 2:3 pattern, 2 of every 5 progressive
    # frames have RFF set = 40%. Allow a generous range to account for partial
    # GOPs, scene changes, and the interlaced inserts we're tolerating.
    progressive_rff = sum(
        1 for p in pictures if p.repeat_first_field and p.progressive_frame
    )
    prog_rff_pct = (
        (progressive_rff / progressive_count * 100.0) if progressive_count > 0 else 0
    )
    if prog_rff_pct < 20.0 or prog_rff_pct > 55.0:
        return _fail(
            f"RFF percentage among progressive frames ({prog_rff_pct:.1f}%) "
            f"outside expected range for 3:2 pulldown (expected ~40%). "
            f"Pattern may be irregular."
        )

    return PulldownScanResult(
        has_pulldown=True,
        is_safe_to_remove=True,
        total_pictures=total,
        rff_count=rff_count,
        progressive_count=progressive_count,
        non_progressive_count=non_progressive,
        progressive_pct=progressive_pct,
        field_picture_count=0,
        original_frame_rate_index=original_rate_idx,
        target_frame_rate_index=target_rate_idx,
        reason=f"Soft pulldown detected and safe to remove "
        f"({progressive_pct:.1f}% progressive)",
        pictures=pictures,
        sequence_headers=sequence_headers,
        sequence_extensions=sequence_extensions,
    )


# =============================================================================
# Remove: strip soft pulldown from an MPEG-2 elementary stream
# =============================================================================


def remove_pulldown(
    es_path: Path,
    scan: PulldownScanResult,
    output_path: Path | None = None,
) -> PulldownRemovalResult:
    """Remove soft pulldown from an MPEG-2 elementary stream.

    Operates on a COPY of the input file (the original is never modified).
    For each picture coding extension, clears repeat_first_field (and
    top_field_first if the sequence is progressive). Updates frame_rate_index
    in all sequence headers.

    Args:
        es_path: Path to the input MPEG-2 elementary stream.
        scan: Result from scan_for_pulldown() — must have is_safe_to_remove=True.
        output_path: Where to write the modified stream. If None, writes to
            es_path.stem + "_pulldown_removed" + es_path.suffix in the same dir.

    Returns:
        PulldownRemovalResult with success status and details.
    """
    if not scan.is_safe_to_remove:
        return PulldownRemovalResult(
            success=False,
            output_path=output_path or es_path,
            pictures_modified=0,
            sequence_headers_modified=0,
            original_rate=_FRAME_RATES.get(scan.original_frame_rate_index, 0),
            new_rate=0,
            reason=f"Scan indicated removal is not safe: {scan.reason}",
        )

    if scan.target_frame_rate_index is None:
        return PulldownRemovalResult(
            success=False,
            output_path=output_path or es_path,
            pictures_modified=0,
            sequence_headers_modified=0,
            original_rate=_FRAME_RATES.get(scan.original_frame_rate_index, 0),
            new_rate=0,
            reason="No target frame rate index determined",
        )

    # Determine output path
    if output_path is None:
        output_path = es_path.with_stem(es_path.stem + "_pulldown_removed")

    # Copy original to output, then modify in place on the copy
    shutil.copy2(es_path, output_path)

    # Read the copy into a mutable bytearray
    data = bytearray(output_path.read_bytes())
    original_size = len(data)

    # Determine if sequence is progressive (for TFF clearing decision)
    is_progressive_sequence = any(
        se.progressive_sequence for se in scan.sequence_extensions
    )

    # --- Modify picture coding extensions ---
    # Clear RFF unconditionally on ALL frames, matching TsMuxeR behavior.
    # For mixed content (mostly progressive with some interlaced inserts),
    # the few interlaced frames get their RFF cleared too — they will
    # display at the uniform 23.976 rate alongside the progressive majority.
    # TFF is only cleared for progressive sequences (sequence-level flag).
    pictures_modified = 0
    for pic in scan.pictures:
        if pic.repeat_first_field:
            data[pic.rff_byte_offset] &= pic.rff_bit_mask
            pictures_modified += 1

        if pic.top_field_first and is_progressive_sequence:
            data[pic.tff_byte_offset] &= pic.tff_bit_mask

    # --- Modify sequence headers: update frame_rate_index ---
    target_idx = scan.target_frame_rate_index
    seq_headers_modified = 0
    for sh in scan.sequence_headers:
        # frame_rate_index is the lower 4 bits of the byte
        old_byte = data[sh.frame_rate_byte_offset]
        new_byte = (old_byte & 0xF0) | (target_idx & 0x0F)
        data[sh.frame_rate_byte_offset] = new_byte
        seq_headers_modified += 1

    # --- Validate: file size must not change ---
    if len(data) != original_size:
        # This should never happen since we only modify existing bytes
        output_path.unlink(missing_ok=True)
        return PulldownRemovalResult(
            success=False,
            output_path=output_path,
            pictures_modified=pictures_modified,
            sequence_headers_modified=seq_headers_modified,
            original_rate=_FRAME_RATES.get(scan.original_frame_rate_index, 0),
            new_rate=_FRAME_RATES.get(target_idx, 0),
            reason=f"File size changed during modification "
            f"({original_size} → {len(data)}). Aborting.",
        )

    # Write the modified data back
    output_path.write_bytes(data)

    return PulldownRemovalResult(
        success=True,
        output_path=output_path,
        pictures_modified=pictures_modified,
        sequence_headers_modified=seq_headers_modified,
        original_rate=_FRAME_RATES.get(scan.original_frame_rate_index, 0),
        new_rate=_FRAME_RATES.get(target_idx, 0),
        reason="Pulldown removed successfully",
    )
