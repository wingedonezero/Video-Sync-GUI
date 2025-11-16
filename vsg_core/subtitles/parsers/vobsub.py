# vsg_core/subtitles/parsers/vobsub.py
# -*- coding: utf-8 -*-
"""
VobSub (.idx/.sub) parser for DVD subtitles.
Adapted from VobSub-ML-OCR (SubtitleEdit port to Python).
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import struct
import re
from PIL import Image
import numpy as np


@dataclass
class VobSubEvent:
    """Represents a single subtitle event from VobSub."""
    start_time: int          # milliseconds
    end_time: int            # milliseconds
    x: int                   # X position
    y: int                   # Y position
    width: int               # Image width
    height: int              # Image height
    image: Image.Image       # PIL Image (RGBA)


class VobSubParser:
    """Parses VobSub .idx and .sub files to extract subtitle events."""

    def __init__(self, idx_path: str):
        """
        Initialize VobSub parser.

        Args:
            idx_path: Path to the .idx file
        """
        self.idx_path = Path(idx_path)
        self.sub_path = self.idx_path.with_suffix('.sub')

        if not self.idx_path.exists():
            raise FileNotFoundError(f"IDX file not found: {self.idx_path}")
        if not self.sub_path.exists():
            raise FileNotFoundError(f"SUB file not found: {self.sub_path}")

        self.palette: List[Tuple[int, int, int, int]] = []
        self.events: List[VobSubEvent] = []
        self.frame_width = 720
        self.frame_height = 480

    def parse(self) -> List[VobSubEvent]:
        """
        Parse VobSub files and extract all subtitle events.

        Returns:
            List of VobSubEvent objects
        """
        # Parse IDX file for palette and timing
        idx_entries = self._parse_idx()

        # Parse SUB file and extract images
        self._parse_sub(idx_entries)

        return self.events

    def _parse_idx(self) -> List[dict]:
        """Parse IDX file for timing and positioning information."""
        entries = []

        with open(self.idx_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Extract palette (16 colors in RGB hex format)
        palette_match = re.search(r'palette:\s*([0-9a-fA-F, ]+)', content)
        if palette_match:
            palette_str = palette_match.group(1)
            colors = re.findall(r'([0-9a-fA-F]{6})', palette_str)
            for color_hex in colors[:16]:  # Max 16 colors
                r = int(color_hex[0:2], 16)
                g = int(color_hex[2:4], 16)
                b = int(color_hex[4:6], 16)
                self.palette.append((r, g, b, 255))

        # Pad palette to 16 colors if needed
        while len(self.palette) < 16:
            self.palette.append((0, 0, 0, 0))

        # Extract resolution if specified
        size_match = re.search(r'size:\s*(\d+)x(\d+)', content, re.IGNORECASE)
        if size_match:
            self.frame_width = int(size_match.group(1))
            self.frame_height = int(size_match.group(2))

        # Extract timestamp entries
        # Format: "timestamp: HH:MM:SS:mmm, filepos: XXXXXXXXX"
        pattern = r'timestamp:\s*(\d{2}):(\d{2}):(\d{2}):(\d{3}),\s*filepos:\s*([0-9A-Fa-f]+)'
        matches = re.findall(pattern, content)

        for match in matches:
            hours, minutes, seconds, millis, filepos = match
            timestamp_ms = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(millis)
            file_position = int(filepos, 16)  # Hex string to int

            entries.append({
                'timestamp': timestamp_ms,
                'filepos': file_position
            })

        return entries

    def _parse_sub(self, idx_entries: List[dict]):
        """Parse SUB file and extract subtitle images."""
        with open(self.sub_path, 'rb') as f:
            sub_data = f.read()

        for i, entry in enumerate(idx_entries):
            try:
                filepos = entry['filepos']
                start_time = entry['timestamp']

                # Determine end time (next subtitle start or +3 seconds)
                if i + 1 < len(idx_entries):
                    end_time = idx_entries[i + 1]['timestamp']
                else:
                    end_time = start_time + 3000  # Default 3 seconds

                # Parse subtitle packet at this position
                event = self._parse_subtitle_packet(sub_data, filepos, start_time, end_time)

                if event and event.image:
                    self.events.append(event)

            except Exception as e:
                # Skip malformed packets
                continue

    def _parse_subtitle_packet(self, sub_data: bytes, offset: int, start_time: int, end_time: int) -> Optional[VobSubEvent]:
        """Parse a single subtitle packet from SUB data."""
        if offset + 4 > len(sub_data):
            return None

        # Read packet header
        try:
            # Skip MPEG-2 pack header if present (14 bytes starting with 0x000001BA)
            if offset + 14 <= len(sub_data):
                pack_header = sub_data[offset:offset+4]
                if pack_header == b'\x00\x00\x01\xBA':
                    offset += 14

            # Skip PES packet header to get to subtitle data
            # Look for private stream 1 (0x000001BD)
            if offset + 4 <= len(sub_data):
                pes_header = sub_data[offset:offset+4]
                if pes_header == b'\x00\x00\x01\xBD':
                    offset += 4

                    # Read PES packet length
                    if offset + 2 <= len(sub_data):
                        pes_length = struct.unpack('>H', sub_data[offset:offset+2])[0]
                        offset += 2

                        # Skip PES header extension
                        if offset + 3 <= len(sub_data):
                            header_data_length = sub_data[offset + 2]
                            offset += 3 + header_data_length

                            # Now at subtitle data
                            # First byte is substream ID (0x20-0x3F for subtitles)
                            if offset < len(sub_data):
                                substream_id = sub_data[offset]
                                offset += 1

                                # Parse subtitle packet
                                return self._parse_subtitle_data(sub_data, offset, start_time, end_time)

        except Exception:
            pass

        return None

    def _parse_subtitle_data(self, data: bytes, offset: int, start_time: int, end_time: int) -> Optional[VobSubEvent]:
        """Parse subtitle control and pixel data."""
        if offset + 2 > len(data):
            return None

        try:
            # Read data packet size
            packet_size = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2

            if offset + packet_size > len(data):
                return None

            packet_data = data[offset:offset + packet_size]

            # Read control sequence offset
            if len(packet_data) < 2:
                return None

            ctrl_offset = struct.unpack('>H', packet_data[0:2])[0]

            if ctrl_offset >= len(packet_data):
                return None

            # Parse control sequence (now returns field addresses too)
            x, y, width, height, colors, alphas, top_field_addr, bottom_field_addr = \
                self._parse_control_sequence(packet_data, ctrl_offset)

            if width == 0 or height == 0:
                return None

            # Decode interlaced image with field addresses
            image = self._decode_rle_image(
                packet_data, width, height,
                colors, alphas,
                top_field_addr, bottom_field_addr
            )

            if image is None:
                return None

            return VobSubEvent(
                start_time=start_time,
                end_time=end_time,
                x=x,
                y=y,
                width=width,
                height=height,
                image=image
            )

        except Exception:
            return None

    @staticmethod
    def _decode_rle(index: int, data: bytes, only_half: bool) -> Tuple[int, int, int, bool, bool]:
        """
        Decode VobSub nibble-based RLE encoding.

        VobSub uses variable-length RLE with 4 modes based on run length:
        - Mode 1 (2-bit): 1-3 pixels
        - Mode 2 (4-bit): 4-15 pixels
        - Mode 3 (8-bit): 16-63 pixels
        - Mode 4 (14-bit): 64+ pixels

        Returns:
            (bytes_consumed, run_length, color_index, only_half, rest_of_line)
        """
        rest_of_line = False
        b1 = data[index]
        b2 = data[index + 1]

        # Handle nibble alignment (when previous code ended on half-byte boundary)
        if only_half:
            b3 = data[index + 2]
            b1 = ((b1 & 0x0F) << 4) | ((b2 & 0xF0) >> 4)
            b2 = ((b2 & 0x0F) << 4) | ((b3 & 0xF0) >> 4)

        # Mode 4: 14-bit run (pattern: 00LLLLLL LLLLLLCC)
        # Used for runs of 64+ pixels
        if b1 >> 2 == 0:
            run_length = (b1 << 6) | (b2 >> 2)
            color = b2 & 0x03
            if run_length == 0:
                # Special case: fill rest of line
                rest_of_line = True
                if only_half:
                    only_half = False
                    return 3, run_length, color, only_half, rest_of_line
            return 2, run_length, color, only_half, rest_of_line

        # Mode 3: 8-bit run (pattern: 0000LLLL LLCCXXXX)
        # Used for runs of 16-63 pixels
        if b1 >> 4 == 0:
            run_length = (b1 << 2) | (b2 >> 6)
            color = (b2 & 0x30) >> 4
            if only_half:
                only_half = False
                return 2, run_length, color, only_half, rest_of_line
            only_half = True
            return 1, run_length, color, only_half, rest_of_line

        # Mode 2: 4-bit run (pattern: 00LLLLCC)
        # Used for runs of 4-15 pixels
        if b1 >> 6 == 0:
            run_length = b1 >> 2
            color = b1 & 0x03
            return 1, run_length, color, only_half, rest_of_line

        # Mode 1: 2-bit run (pattern: LLCCXXXX)
        # Used for runs of 1-3 pixels
        run_length = b1 >> 6
        color = (b1 & 0x30) >> 4

        if only_half:
            only_half = False
            return 1, run_length, color, only_half, rest_of_line
        only_half = True
        return 0, run_length, color, only_half, rest_of_line

    def _parse_control_sequence(self, packet_data: bytes, ctrl_offset: int) -> Tuple[int, int, int, int, List[int], List[int], int, int]:
        """Parse control sequence to get position, size, colors, and field addresses."""
        x, y, width, height = 0, 0, 0, 0
        colors = [0, 1, 2, 3]
        alphas = [15, 15, 15, 15]
        top_field_addr = 4  # Default offset (skip packet header)
        bottom_field_addr = 4

        pos = ctrl_offset
        while pos + 1 < len(packet_data):
            cmd = packet_data[pos]
            pos += 1

            if cmd == 0x00:  # Force display
                continue
            elif cmd == 0x01:  # Start display
                continue
            elif cmd == 0x03:  # Set color (4 x 4-bit color indices)
                if pos + 2 <= len(packet_data):
                    color_data = struct.unpack('>H', packet_data[pos:pos+2])[0]
                    colors[3] = (color_data >> 12) & 0x0F
                    colors[2] = (color_data >> 8) & 0x0F
                    colors[1] = (color_data >> 4) & 0x0F
                    colors[0] = color_data & 0x0F
                    pos += 2
            elif cmd == 0x04:  # Set alpha (4 x 4-bit alpha values)
                if pos + 2 <= len(packet_data):
                    alpha_data = struct.unpack('>H', packet_data[pos:pos+2])[0]
                    alphas[3] = (alpha_data >> 12) & 0x0F
                    alphas[2] = (alpha_data >> 8) & 0x0F
                    alphas[1] = (alpha_data >> 4) & 0x0F
                    alphas[0] = alpha_data & 0x0F
                    pos += 2
            elif cmd == 0x05:  # Set display area (x1, y1, x2, y2)
                if pos + 6 <= len(packet_data):
                    coords = struct.unpack('>HHH', packet_data[pos:pos+6])[0:2]
                    x1 = (coords[0] >> 4) & 0x0FFF
                    x2 = ((coords[0] & 0x000F) << 8) | ((coords[1] >> 8) & 0x00FF)
                    y1 = (coords[1] & 0x00FF) | ((coords[0] & 0x0F00) >> 4)

                    # Parse as two 12-bit pairs
                    area_data = packet_data[pos:pos+6]
                    x = ((area_data[0] << 4) | (area_data[1] >> 4)) & 0xFFF
                    x2 = (((area_data[1] & 0x0F) << 8) | area_data[2]) & 0xFFF
                    y = ((area_data[3] << 4) | (area_data[4] >> 4)) & 0xFFF
                    y2 = (((area_data[4] & 0x0F) << 8) | area_data[5]) & 0xFFF

                    width = x2 - x + 1
                    height = y2 - y + 1
                    pos += 6
            elif cmd == 0x06:  # Set pixel data addresses (for interlaced fields)
                if pos + 4 <= len(packet_data):
                    # Extract addresses for top field (even lines) and bottom field (odd lines)
                    top_field_addr = struct.unpack('>H', packet_data[pos:pos+2])[0]
                    bottom_field_addr = struct.unpack('>H', packet_data[pos+2:pos+4])[0]
                pos += 4
            elif cmd == 0xFF:  # End of control sequence
                break
            else:
                # Unknown command, try to skip
                pos += 1

        return x, y, width, height, colors, alphas, top_field_addr, bottom_field_addr

    def _decode_rle_image(self, packet_data: bytes, width: int, height: int,
                          colors: List[int], alphas: List[int],
                          top_field_addr: int, bottom_field_addr: int) -> Optional[Image.Image]:
        """
        Decode interlaced RLE subtitle image.

        VobSub images are interlaced like old TV broadcasts:
        - Top field: even lines (0, 2, 4, 6...)
        - Bottom field: odd lines (1, 3, 5, 7...)
        """
        try:
            # Create RGB image (VobSub subtitles are always opaque)
            img_array = np.zeros((height, width, 3), dtype=np.uint8)

            # Get background color and fill image
            bg_idx = colors[0] if 0 < len(colors) else 0
            if bg_idx < len(self.palette):
                bg_r, bg_g, bg_b, _ = self.palette[bg_idx]
                img_array[:, :] = [bg_r, bg_g, bg_b]

            # Decode top field (even lines: 0, 2, 4, ...)
            self._decode_field(
                packet_data, img_array,
                start_y=0, y_increment=2,
                data_addr=top_field_addr,
                colors=colors, alphas=alphas
            )

            # Decode bottom field (odd lines: 1, 3, 5, ...)
            self._decode_field(
                packet_data, img_array,
                start_y=1, y_increment=2,
                data_addr=bottom_field_addr,
                colors=colors, alphas=alphas
            )

            # Convert to PIL Image
            image = Image.fromarray(img_array, 'RGB')
            return image

        except Exception:
            return None

    def _decode_field(self, data: bytes, img: np.ndarray,
                      start_y: int, y_increment: int, data_addr: int,
                      colors: List[int], alphas: List[int]):
        """
        Decode one interlaced field using nibble-based RLE.

        Args:
            data: Packet data containing RLE codes
            img: Image array to draw into
            start_y: Starting line (0 for top field, 1 for bottom field)
            y_increment: Line increment (2 for interlaced)
            data_addr: Offset in data where field RLE starts
            colors: 4-color palette indices
            alphas: 4-alpha values (unused, kept for compatibility)
        """
        height, width = img.shape[:2]
        y = start_y
        x = 0
        pos = 0
        only_half = False

        # Get background color for comparison
        bg_idx = colors[0] if 0 < len(colors) else 0
        if bg_idx < len(self.palette):
            bg_color = tuple(self.palette[bg_idx][:3])
        else:
            bg_color = (0, 0, 0)

        while y < height and data_addr + pos + 2 < len(data):
            # Decode one RLE code
            consumed, run_length, color_idx, only_half, rest_of_line = \
                self._decode_rle(data_addr + pos, data, only_half)

            pos += consumed

            if rest_of_line:
                # Special case: fill rest of line with this color
                run_length = width - x

            # Get color from palette
            palette_idx = colors[color_idx] if color_idx < len(colors) else 0
            if palette_idx < len(self.palette):
                r, g, b, _ = self.palette[palette_idx]
                pixel_color = (r, g, b)
            else:
                pixel_color = bg_color

            # Draw pixels
            for i in range(run_length):
                if x >= width:
                    # Line wrap - advance to next line in this field
                    if only_half:
                        # Nibble boundary: skip half byte
                        pos += 1
                        only_half = False
                    x = 0
                    y += y_increment  # Increment by 2 for interlaced!
                    break

                # Set pixel (skip if background color)
                if y < height and pixel_color != bg_color:
                    img[y, x] = pixel_color

                x += 1
