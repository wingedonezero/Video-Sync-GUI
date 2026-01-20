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

        Returns:
            RGBA numpy array
        """
        # Create RGBA image
        image = np.zeros((height, width, 4), dtype=np.uint8)

        # Build color lookup with alpha
        colors = []
        for i, (idx, alpha) in enumerate(zip(color_indices, alpha_values)):
            if idx < len(palette):
                r, g, b = palette[idx]
            else:
                r, g, b = 128, 128, 128
            # Convert 4-bit alpha (0-15) to 8-bit (0-255)
            a = int(alpha * 255 / 15)
            colors.append((r, g, b, a))

        # Decode top field (even lines: 0, 2, 4, ...)
        self._decode_rle_field(data, top_offset, image, 0, 2, width, height, colors)

        # Decode bottom field (odd lines: 1, 3, 5, ...)
        self._decode_rle_field(data, bottom_offset, image, 1, 2, width, height, colors)

        return image

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

        RLE encoding:
            - 4 bits at a time, forming run-length + color codes
            - Special codes for line endings
        """
        if offset >= len(data):
            return

        bit_pos = 0
        byte_pos = offset
        x = 0
        y = start_line

        while y < height and byte_pos < len(data):
            # Read nibble
            if bit_pos == 0:
                nibble = (data[byte_pos] >> 4) & 0x0F
                bit_pos = 4
            else:
                nibble = data[byte_pos] & 0x0F
                bit_pos = 0
                byte_pos += 1

            # Decode run-length code
            if nibble < 4:
                # 2-bit color, need more nibbles for length
                color = nibble
                # Read next nibble for length
                if byte_pos >= len(data):
                    break
                if bit_pos == 0:
                    next_nibble = (data[byte_pos] >> 4) & 0x0F
                    bit_pos = 4
                else:
                    next_nibble = data[byte_pos] & 0x0F
                    bit_pos = 0
                    byte_pos += 1

                if next_nibble < 4:
                    # Still short, read more
                    if byte_pos >= len(data):
                        break
                    if bit_pos == 0:
                        third = (data[byte_pos] >> 4) & 0x0F
                        bit_pos = 4
                    else:
                        third = data[byte_pos] & 0x0F
                        bit_pos = 0
                        byte_pos += 1

                    if third < 4:
                        # Read fourth nibble
                        if byte_pos >= len(data):
                            break
                        if bit_pos == 0:
                            fourth = (data[byte_pos] >> 4) & 0x0F
                            bit_pos = 4
                        else:
                            fourth = data[byte_pos] & 0x0F
                            bit_pos = 0
                            byte_pos += 1
                        length = (nibble << 6) | (next_nibble << 4) | (third << 2) | (fourth >> 2)
                        color = fourth & 0x03
                    else:
                        length = (nibble << 4) | (next_nibble << 2) | (third >> 2)
                        color = third & 0x03
                else:
                    length = (nibble << 2) | (next_nibble >> 2)
                    color = next_nibble & 0x03

                if length == 0:
                    # End of line - fill rest with color
                    length = width - x
            else:
                # Simple run: 2 bits length, 2 bits color
                length = nibble >> 2
                color = nibble & 0x03

            # Apply run to image
            if color < len(colors):
                r, g, b, a = colors[color]
                end_x = min(x + length, width)
                if y < height:
                    image[y, x:end_x, 0] = r
                    image[y, x:end_x, 1] = g
                    image[y, x:end_x, 2] = b
                    image[y, x:end_x, 3] = a
                x = end_x

            # Check for line end
            if x >= width:
                x = 0
                y += line_step
                # Align to byte boundary at end of each line
                if bit_pos != 0:
                    bit_pos = 0
                    byte_pos += 1
