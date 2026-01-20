# vsg_core/subtitles/ocr/parsers/vobsub.py
# -*- coding: utf-8 -*-
"""
VobSub (.sub/.idx) Parser

Extracts subtitle images from DVD VobSub format files.
Based on SubtitleEdit's VobSub parsing logic, ported to Python.

VobSub format consists of two files:
    - .idx: Text index file with timestamps and byte offsets
    - .sub: Binary file containing MPEG-2 PES packets with subtitle bitmaps

The subtitle data is encoded as run-length encoded (RLE) bitmaps with a
4-color palette per subtitle.

RLE Encoding formats (from SubtitleEdit):
    Value      Bits   Format
    1-3        4      nncc               (half a byte)
    4-15       8      00nnnncc           (one byte)
    16-63     12      0000nnnnnncc       (one and a half byte)
    64-255    16      000000nnnnnnnncc   (two bytes)
"""

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, BinaryIO
import numpy as np

from .base import SubtitleImage, SubtitleImageParser, ParseResult


@dataclass
class IdxEntry:
    """Parsed entry from .idx file."""
    timestamp_ms: int
    file_position: int


@dataclass
class VobSubHeader:
    """Header information from .idx file."""
    size_x: int = 720
    size_y: int = 480
    org_x: int = 0
    org_y: int = 0
    palette: List[Tuple[int, int, int]] = None  # RGB tuples
    language: str = "en"
    language_index: int = 0

    def __post_init__(self):
        if self.palette is None:
            # Default grayscale palette
            self.palette = [(i * 17, i * 17, i * 17) for i in range(16)]


class VobSubParser(SubtitleImageParser):
    """
    Parser for VobSub (.sub/.idx) subtitle format.

    Extracts subtitle bitmaps with timing and position information.
    """

    def can_parse(self, file_path: Path) -> bool:
        """Check if file is a VobSub file."""
        suffix = file_path.suffix.lower()
        if suffix == '.idx':
            return file_path.with_suffix('.sub').exists()
        elif suffix == '.sub':
            return file_path.with_suffix('.idx').exists()
        return False

    def parse(self, file_path: Path, work_dir: Optional[Path] = None) -> ParseResult:
        """
        Parse VobSub files and extract subtitle images.

        Args:
            file_path: Path to .idx or .sub file
            work_dir: Optional working directory (unused for VobSub)

        Returns:
            ParseResult with extracted subtitle images
        """
        result = ParseResult()

        # Normalize to .idx path
        if file_path.suffix.lower() == '.sub':
            idx_path = file_path.with_suffix('.idx')
            sub_path = file_path
        else:
            idx_path = file_path
            sub_path = file_path.with_suffix('.sub')

        # Verify both files exist
        if not idx_path.exists():
            result.errors.append(f"IDX file not found: {idx_path}")
            return result
        if not sub_path.exists():
            result.errors.append(f"SUB file not found: {sub_path}")
            return result

        try:
            # Parse .idx file for header and entries
            header, entries = self._parse_idx(idx_path)
            result.format_info = {
                'format': 'VobSub',
                'frame_size': (header.size_x, header.size_y),
                'language': header.language,
                'subtitle_count': len(entries),
            }

            if not entries:
                result.warnings.append("No subtitle entries found in IDX file")
                return result

            # Parse .sub file for actual subtitle data
            with open(sub_path, 'rb') as sub_file:
                for i, entry in enumerate(entries):
                    try:
                        subtitle = self._parse_subtitle(
                            sub_file, entry, i, header, entries
                        )
                        if subtitle is not None:
                            result.subtitles.append(subtitle)
                    except Exception as e:
                        result.warnings.append(f"Failed to parse subtitle {i}: {e}")

        except Exception as e:
            result.errors.append(f"Failed to parse VobSub: {e}")

        return result

    def _parse_idx(self, idx_path: Path) -> Tuple[VobSubHeader, List[IdxEntry]]:
        """
        Parse the .idx index file.

        Returns:
            Tuple of (header info, list of subtitle entries)
        """
        header = VobSubHeader()
        entries: List[IdxEntry] = []

        with open(idx_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()

                # Parse header fields
                if line.startswith('size:'):
                    match = re.match(r'size:\s*(\d+)x(\d+)', line)
                    if match:
                        header.size_x = int(match.group(1))
                        header.size_y = int(match.group(2))

                elif line.startswith('org:'):
                    match = re.match(r'org:\s*(\d+),\s*(\d+)', line)
                    if match:
                        header.org_x = int(match.group(1))
                        header.org_y = int(match.group(2))

                elif line.startswith('palette:'):
                    # Parse 16-color palette (RGB values in hex)
                    palette_str = line[8:].strip()
                    colors = palette_str.split(',')
                    header.palette = []
                    for color in colors[:16]:
                        color = color.strip()
                        if color:
                            try:
                                rgb = int(color, 16)
                                r = (rgb >> 16) & 0xFF
                                g = (rgb >> 8) & 0xFF
                                b = rgb & 0xFF
                                header.palette.append((r, g, b))
                            except ValueError:
                                header.palette.append((128, 128, 128))
                    # Pad to 16 colors if needed
                    while len(header.palette) < 16:
                        header.palette.append((128, 128, 128))

                elif line.startswith('id:'):
                    # Language ID line: id: en, index: 0
                    match = re.match(r'id:\s*(\w+),\s*index:\s*(\d+)', line)
                    if match:
                        header.language = match.group(1)
                        header.language_index = int(match.group(2))

                elif line.startswith('timestamp:'):
                    # Timestamp line: timestamp: 00:00:01:234, filepos: 000000000
                    match = re.match(
                        r'timestamp:\s*(\d+):(\d+):(\d+):(\d+),\s*filepos:\s*([0-9a-fA-F]+)',
                        line
                    )
                    if match:
                        hours = int(match.group(1))
                        minutes = int(match.group(2))
                        seconds = int(match.group(3))
                        ms = int(match.group(4))
                        filepos = int(match.group(5), 16)

                        timestamp_ms = (
                            hours * 3600000 +
                            minutes * 60000 +
                            seconds * 1000 +
                            ms
                        )
                        entries.append(IdxEntry(timestamp_ms, filepos))

        return header, entries

    def _parse_subtitle(
        self,
        sub_file: BinaryIO,
        entry: IdxEntry,
        index: int,
        header: VobSubHeader,
        all_entries: List[IdxEntry]
    ) -> Optional[SubtitleImage]:
        """
        Parse a single subtitle from the .sub file.

        Args:
            sub_file: Open binary file handle
            entry: IDX entry for this subtitle
            index: Index of this subtitle
            header: VobSub header info
            all_entries: All entries (to calculate end time)

        Returns:
            SubtitleImage or None if parsing fails
        """
        sub_file.seek(entry.file_position)

        # Read MPEG-2 PES packets until we have complete subtitle data
        subtitle_data = self._read_pes_packets(sub_file)
        if not subtitle_data or len(subtitle_data) < 4:
            return None

        # Parse the subtitle packet
        try:
            image, x, y, forced = self._decode_subtitle_packet(
                subtitle_data, header
            )
        except Exception:
            return None

        if image is None:
            return None

        # Calculate end time from next entry or add default duration
        if index + 1 < len(all_entries):
            end_ms = all_entries[index + 1].timestamp_ms
        else:
            # Default 4 second duration for last subtitle
            end_ms = entry.timestamp_ms + 4000

        return SubtitleImage(
            index=index,
            start_ms=entry.timestamp_ms,
            end_ms=end_ms,
            image=image,
            x=x,
            y=y,
            width=image.shape[1] if image is not None else 0,
            height=image.shape[0] if image is not None else 0,
            frame_width=header.size_x,
            frame_height=header.size_y,
            is_forced=forced,
            palette=[(r, g, b, 255) for r, g, b in header.palette],
        )

    def _read_pes_packets(self, f: BinaryIO) -> bytes:
        """
        Read MPEG-2 PES packets containing subtitle data.

        VobSub uses MPEG-2 Program Stream format with subtitle data
        in private stream 1 (0xBD).

        Returns:
            Concatenated subtitle payload data
        """
        data = bytearray()
        max_read = 65536 * 10  # Safety limit
        bytes_read = 0

        while bytes_read < max_read:
            # Read pack header start code
            start_code = f.read(4)
            if len(start_code) < 4:
                break

            # Check for pack start code (0x000001BA)
            if start_code == b'\x00\x00\x01\xBA':
                # Skip pack header (MPEG-2 pack header is variable length)
                pack_header = f.read(10)
                if len(pack_header) < 10:
                    break
                # Check stuffing length in last byte
                stuffing = pack_header[9] & 0x07
                if stuffing > 0:
                    f.read(stuffing)
                bytes_read += 14 + stuffing
                continue

            # Check for PES packet start code (0x000001XX)
            if start_code[:3] == b'\x00\x00\x01':
                stream_id = start_code[3]

                # Read PES packet length
                length_bytes = f.read(2)
                if len(length_bytes) < 2:
                    break
                packet_length = struct.unpack('>H', length_bytes)[0]
                bytes_read += 6

                if packet_length == 0:
                    break

                # Read PES packet data
                packet_data = f.read(packet_length)
                if len(packet_data) < packet_length:
                    break
                bytes_read += packet_length

                # Private stream 1 (0xBD) contains subtitles
                if stream_id == 0xBD and len(packet_data) >= 3:
                    # Skip PES header extension
                    pes_header_data_length = packet_data[2]
                    payload_start = 3 + pes_header_data_length

                    if payload_start < len(packet_data):
                        # Check substream ID (subtitle streams are 0x20-0x3F)
                        substream_id = packet_data[payload_start]
                        if 0x20 <= substream_id <= 0x3F:
                            # Add subtitle payload (skip substream ID byte)
                            data.extend(packet_data[payload_start + 1:])

                # Check for end code
                if stream_id == 0xB9:
                    break
            else:
                # Not a valid start code, we may be at end of subtitle data
                break

        return bytes(data)

    def _decode_subtitle_packet(
        self,
        data: bytes,
        header: VobSubHeader
    ) -> Tuple[Optional[np.ndarray], int, int, bool]:
        """
        Decode subtitle packet into bitmap image.

        VobSub subtitles use run-length encoding with a 4-color palette
        selected from the 16-color master palette.

        Args:
            data: Raw subtitle packet data
            header: VobSub header with palette

        Returns:
            Tuple of (image array, x position, y position, is_forced)
        """
        if len(data) < 4:
            return None, 0, 0, False

        # First two bytes are total size (we already have the data)
        # Next two bytes are offset to control sequence
        data_size = struct.unpack('>H', data[0:2])[0]
        ctrl_offset = struct.unpack('>H', data[2:4])[0]

        if ctrl_offset >= len(data):
            return None, 0, 0, False

        # Parse control sequence to get display parameters
        ctrl_result = self._parse_control_sequence(data, ctrl_offset, header)
        if ctrl_result is None:
            return None, 0, 0, False

        (x1, y1, x2, y2, color_indices, alpha_values,
         top_field_offset, bottom_field_offset, forced) = ctrl_result

        width = x2 - x1 + 1
        height = y2 - y1 + 1

        if width <= 0 or height <= 0 or width > 2000 or height > 2000:
            return None, 0, 0, False

        # Decode RLE data into bitmap
        image = self._decode_rle_image(
            data, top_field_offset, bottom_field_offset,
            width, height, color_indices, alpha_values, header.palette
        )

        return image, x1, y1, forced

    def _parse_control_sequence(
        self,
        data: bytes,
        offset: int,
        header: VobSubHeader
    ) -> Optional[Tuple]:
        """
        Parse subtitle control sequence.

        Returns:
            Tuple of (x1, y1, x2, y2, colors, alphas, top_offset, bottom_offset, forced)
        """
        x1, y1, x2, y2 = 0, 0, header.size_x - 1, header.size_y - 1
        color_indices = [0, 1, 2, 3]  # Default palette indices
        alpha_values = [0, 15, 15, 15]  # Default alpha (0=transparent, 15=opaque)
        top_field_offset = 4  # Default data start
        bottom_field_offset = 4
        forced = False
        end_time_pts = 0

        pos = offset
        while pos < len(data) - 1:
            # Skip date field (2 bytes)
            pos += 2
            if pos >= len(data):
                break

            # Read next control sequence offset
            next_ctrl = struct.unpack('>H', data[pos:pos+2])[0]
            pos += 2

            # Process commands until end
            while pos < len(data):
                cmd = data[pos]
                pos += 1

                if cmd == 0x00:
                    # Forced display
                    forced = True

                elif cmd == 0x01:
                    # Start display
                    pass

                elif cmd == 0x02:
                    # Stop display
                    pass

                elif cmd == 0x03:
                    # Palette
                    if pos + 2 <= len(data):
                        b1, b2 = data[pos], data[pos + 1]
                        color_indices = [
                            (b1 >> 4) & 0x0F,
                            b1 & 0x0F,
                            (b2 >> 4) & 0x0F,
                            b2 & 0x0F
                        ]
                        pos += 2

                elif cmd == 0x04:
                    # Alpha channel
                    if pos + 2 <= len(data):
                        b1, b2 = data[pos], data[pos + 1]
                        alpha_values = [
                            (b1 >> 4) & 0x0F,
                            b1 & 0x0F,
                            (b2 >> 4) & 0x0F,
                            b2 & 0x0F
                        ]
                        pos += 2

                elif cmd == 0x05:
                    # Coordinates
                    if pos + 6 <= len(data):
                        x1 = (data[pos] << 4) | ((data[pos + 1] >> 4) & 0x0F)
                        x2 = ((data[pos + 1] & 0x0F) << 8) | data[pos + 2]
                        y1 = (data[pos + 3] << 4) | ((data[pos + 4] >> 4) & 0x0F)
                        y2 = ((data[pos + 4] & 0x0F) << 8) | data[pos + 5]
                        pos += 6

                elif cmd == 0x06:
                    # RLE offsets (top and bottom fields)
                    if pos + 4 <= len(data):
                        top_field_offset = struct.unpack('>H', data[pos:pos+2])[0]
                        bottom_field_offset = struct.unpack('>H', data[pos+2:pos+4])[0]
                        pos += 4

                elif cmd == 0xFF:
                    # End of control sequence
                    break

                else:
                    # Unknown command, skip
                    pass

            # Check if we should continue to next control sequence
            if next_ctrl == offset:
                break
            offset = next_ctrl
            pos = offset

        return (x1, y1, x2, y2, color_indices, alpha_values,
                top_field_offset, bottom_field_offset, forced)

    def _decode_rle_image(
        self,
        data: bytes,
        top_offset: int,
        bottom_offset: int,
        width: int,
        height: int,
        color_indices: List[int],
        alpha_values: List[int],
        palette: List[Tuple[int, int, int]]
    ) -> np.ndarray:
        """
        Decode RLE-encoded subtitle image.

        VobSub uses interlaced RLE with separate top and bottom fields.
        Each field contains run-length encoded 2-bit color values.

        VobSub 4-color palette positions:
            Index 0: Background (usually transparent)
            Index 1: Pattern/text fill (main text)
            Index 2: Emphasis 1 (outline or secondary text)
            Index 3: Emphasis 2 (anti-alias/shadow)

        Following subtile-ocr/vobsubocr approach:
        - Render ALL non-background colors with their ACTUAL palette values
        - Position 0 is always transparent (background)
        - Positions 1, 2, 3 are rendered with real colors + alpha
        - The preprocessing step converts to grayscale and binarizes,
          which naturally filters out light anti-aliasing colors while
          keeping the darker text colors as black.

        This approach works better than forcing specific positions to black
        because it lets the binarization threshold handle edge cases.

        Returns:
            RGBA numpy array with actual palette colors
        """
        # Create RGBA image
        image = np.zeros((height, width, 4), dtype=np.uint8)

        # Build color lookup - render with ACTUAL palette colors
        # Position 0 = transparent background
        # Positions 1, 2, 3 = render as OPAQUE regardless of alpha value
        #
        # IMPORTANT: Some VobSubs have alpha=0 for certain text colors,
        # but we still need to render them for OCR. SubtitleEdit and
        # other tools render all colors regardless of alpha. The alpha
        # in VobSub is for display purposes, not to indicate missing text.
        colors = []
        for i, (idx, alpha) in enumerate(zip(color_indices, alpha_values)):
            if idx < len(palette):
                r, g, b = palette[idx]
            else:
                r, g, b = 128, 128, 128  # Fallback gray

            if i == 0:
                # Position 0: Background - always transparent
                colors.append((0, 0, 0, 0))
            else:
                # Positions 1, 2, 3: Render with actual color, FULL OPACITY
                # Ignore alpha value - we need all text visible for OCR
                colors.append((r, g, b, 255))

        # Decode top field (even lines: 0, 2, 4, ...)
        self._decode_rle_field(data, top_offset, image, 0, 2, width, height, colors)

        # Decode bottom field (odd lines: 1, 3, 5, ...)
        self._decode_rle_field(data, bottom_offset, image, 1, 2, width, height, colors)

        return image

    def _decode_rle(
        self,
        data: bytes,
        index: int,
        only_half: bool
    ) -> Tuple[int, int, int, bool, bool]:
        """
        Decode a single RLE run from the data.

        Based on SubtitleEdit's DecodeRle algorithm.

        RLE encoding formats:
            Value      Bits   Format
            1-3        4      nncc               (half a byte)
            4-15       8      00nnnncc           (one byte)
            16-63     12      0000nnnnnncc       (one and a half byte)
            64-255    16      000000nnnnnnnncc   (two bytes)

        Args:
            data: The raw subtitle data
            index: Current byte index in data
            only_half: Whether we're starting at a half-byte position

        Returns:
            Tuple of (index_increment, run_length, color, new_only_half, rest_of_line)
        """
        rest_of_line = False

        # Safety check
        if index + 2 >= len(data):
            return 0, 0, 0, only_half, True

        b1 = data[index]
        b2 = data[index + 1]

        # If we're at a half-byte position, reconstruct the bytes
        if only_half:
            if index + 2 >= len(data):
                return 0, 0, 0, only_half, True
            b3 = data[index + 2]
            b1 = ((b1 & 0x0F) << 4) | ((b2 & 0xF0) >> 4)
            b2 = ((b2 & 0x0F) << 4) | ((b3 & 0xF0) >> 4)

        # 16-bit code: 000000nnnnnnnncc (two bytes, 64-255 pixels)
        if b1 >> 2 == 0:
            run_length = (b1 << 6) | (b2 >> 2)
            color = b2 & 0x03
            if run_length == 0:
                # End of line marker
                rest_of_line = True
                if only_half:
                    return 3, run_length, color, False, rest_of_line
            return 2, run_length, color, only_half, rest_of_line

        # 12-bit code: 0000nnnnnncc (one and a half bytes, 16-63 pixels)
        if b1 >> 4 == 0:
            run_length = (b1 << 2) | (b2 >> 6)
            color = (b2 & 0x30) >> 4
            if only_half:
                return 2, run_length, color, False, rest_of_line
            return 1, run_length, color, True, rest_of_line

        # 8-bit code: 00nnnncc (one byte, 4-15 pixels)
        if b1 >> 6 == 0:
            run_length = b1 >> 2
            color = b1 & 0x03
            return 1, run_length, color, only_half, rest_of_line

        # 4-bit code: nncc (half a byte, 1-3 pixels)
        run_length = b1 >> 6
        color = (b1 & 0x30) >> 4

        if only_half:
            return 1, run_length, color, False, rest_of_line
        return 0, run_length, color, True, rest_of_line

    def _decode_rle_field(
        self,
        data: bytes,
        offset: int,
        image: np.ndarray,
        start_line: int,
        line_step: int,
        width: int,
        height: int,
        colors: List[Tuple[int, int, int, int]]
    ):
        """
        Decode one RLE field (top or bottom) into the image.

        Uses SubtitleEdit's RLE decoding algorithm with proper half-byte tracking.

        Args:
            data: Raw subtitle data
            offset: Starting byte offset for this field
            image: Output image array to fill
            start_line: First line to decode (0 for top, 1 for bottom)
            line_step: Line increment (2 for interlaced)
            width: Image width
            height: Image height
            colors: 4-color RGBA palette
        """
        if offset >= len(data):
            return

        index = offset
        only_half = False
        x = 0
        y = start_line

        while y < height and index + 2 < len(data):
            # Decode next run
            idx_inc, run_length, color, only_half, rest_of_line = self._decode_rle(
                data, index, only_half
            )
            index += idx_inc

            # If end of line, fill rest with this color
            if rest_of_line:
                run_length = width - x

            # Get color values
            if color < len(colors):
                r, g, b, a = colors[color]
            else:
                r, g, b, a = 0, 0, 0, 0

            # Draw pixels for this run
            for i in range(run_length):
                if x >= width:
                    # Line wrap - align to byte boundary
                    if only_half:
                        only_half = False
                        index += 1
                    x = 0
                    y += line_step
                    break

                if y < height and a > 0:  # Only draw non-transparent pixels
                    image[y, x, 0] = r
                    image[y, x, 1] = g
                    image[y, x, 2] = b
                    image[y, x, 3] = a
                x += 1

            # Check if we naturally hit end of line
            if x >= width:
                if only_half:
                    only_half = False
                    index += 1
                x = 0
                y += line_step
