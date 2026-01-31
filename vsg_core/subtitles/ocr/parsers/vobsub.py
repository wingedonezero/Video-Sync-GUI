# vsg_core/subtitles/ocr/parsers/vobsub.py
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

import logging
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .base import ParseResult, SubtitleImage, SubtitleImageParser

logger = logging.getLogger(__name__)


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
    palette: list[tuple[int, int, int]] = None  # RGB tuples
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
        if suffix == ".idx":
            return file_path.with_suffix(".sub").exists()
        elif suffix == ".sub":
            return file_path.with_suffix(".idx").exists()
        return False

    def parse(self, file_path: Path, work_dir: Path | None = None) -> ParseResult:
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
        if file_path.suffix.lower() == ".sub":
            idx_path = file_path.with_suffix(".idx")
            sub_path = file_path
        else:
            idx_path = file_path
            sub_path = file_path.with_suffix(".sub")

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
                "format": "VobSub",
                "frame_size": (header.size_x, header.size_y),
                "language": header.language,
                "subtitle_count": len(entries),
            }

            if not entries:
                result.warnings.append("No subtitle entries found in IDX file")
                return result

            # Parse .sub file for actual subtitle data
            with open(sub_path, "rb") as sub_file:
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

    def _parse_idx(self, idx_path: Path) -> tuple[VobSubHeader, list[IdxEntry]]:
        """
        Parse the .idx index file.

        Returns:
            Tuple of (header info, list of subtitle entries)
        """
        header = VobSubHeader()
        entries: list[IdxEntry] = []

        with open(idx_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()

                # Parse header fields
                if line.startswith("size:"):
                    match = re.match(r"size:\s*(\d+)x(\d+)", line)
                    if match:
                        header.size_x = int(match.group(1))
                        header.size_y = int(match.group(2))

                elif line.startswith("org:"):
                    match = re.match(r"org:\s*(\d+),\s*(\d+)", line)
                    if match:
                        header.org_x = int(match.group(1))
                        header.org_y = int(match.group(2))

                elif line.startswith("palette:"):
                    # Parse 16-color palette (RGB values in hex)
                    palette_str = line[8:].strip()
                    colors = palette_str.split(",")
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

                elif line.startswith("id:"):
                    # Language ID line: id: en, index: 0
                    match = re.match(r"id:\s*(\w+),\s*index:\s*(\d+)", line)
                    if match:
                        header.language = match.group(1)
                        header.language_index = int(match.group(2))

                elif line.startswith("timestamp:"):
                    # Timestamp line: timestamp: 00:00:01:234, filepos: 000000000
                    match = re.match(
                        r"timestamp:\s*(\d+):(\d+):(\d+):(\d+),\s*filepos:\s*([0-9a-fA-F]+)",
                        line,
                    )
                    if match:
                        hours = int(match.group(1))
                        minutes = int(match.group(2))
                        seconds = int(match.group(3))
                        ms = int(match.group(4))
                        filepos = int(match.group(5), 16)

                        timestamp_ms = (
                            hours * 3600000 + minutes * 60000 + seconds * 1000 + ms
                        )
                        entries.append(IdxEntry(timestamp_ms, filepos))

        return header, entries

    def _parse_subtitle(
        self,
        sub_file: BinaryIO,
        entry: IdxEntry,
        index: int,
        header: VobSubHeader,
        all_entries: list[IdxEntry],
    ) -> SubtitleImage | None:
        """
        Parse a single subtitle from the .sub file.

        Args:
            sub_file: Open binary file handle
            entry: IDX entry for this subtitle
            index: Index of this subtitle
            header: VobSub header info
            all_entries: All entries (for fallback end time calculation)

        Returns:
            SubtitleImage or None if parsing fails
        """
        sub_file.seek(entry.file_position)

        # Read MPEG-2 PES packets until we have complete subtitle data
        subtitle_data = self._read_pes_packets(sub_file)
        if not subtitle_data or len(subtitle_data) < 4:
            return None

        # Parse the subtitle packet (now includes duration from control sequence)
        try:
            image, x, y, forced, duration_ms = self._decode_subtitle_packet(
                subtitle_data, header
            )
        except Exception:
            return None

        if image is None:
            return None

        # Calculate end time using duration from control sequence
        # The duration comes from the SP_DCSQ_STM delay field when stop display (0x02) is seen
        if duration_ms > 0:
            # Use the actual duration from the subtitle packet
            end_ms = entry.timestamp_ms + duration_ms
            logger.debug(f"Subtitle {index}: using SPU duration {duration_ms}ms")
        elif index + 1 < len(all_entries):
            # Fallback: use next subtitle's start time (old behavior)
            end_ms = all_entries[index + 1].timestamp_ms
            logger.debug(f"Subtitle {index}: no SPU duration, using next start time")
        else:
            # Default 4 second duration for last subtitle with no duration info
            end_ms = entry.timestamp_ms + 4000
            logger.debug(f"Subtitle {index}: no SPU duration, using 4s default")

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
            if start_code == b"\x00\x00\x01\xba":
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
            if start_code[:3] == b"\x00\x00\x01":
                stream_id = start_code[3]

                # Read PES packet length
                length_bytes = f.read(2)
                if len(length_bytes) < 2:
                    break
                packet_length = struct.unpack(">H", length_bytes)[0]
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
                            data.extend(packet_data[payload_start + 1 :])

                # Check for end code
                if stream_id == 0xB9:
                    break
            else:
                # Not a valid start code, we may be at end of subtitle data
                break

        return bytes(data)

    def _decode_subtitle_packet(
        self, data: bytes, header: VobSubHeader
    ) -> tuple[np.ndarray | None, int, int, bool, int]:
        """
        Decode subtitle packet into bitmap image.

        VobSub subtitles use run-length encoding with a 4-color palette
        selected from the 16-color master palette.

        Args:
            data: Raw subtitle packet data
            header: VobSub header with palette

        Returns:
            Tuple of (image array, x position, y position, is_forced, duration_ms)
        """
        if len(data) < 4:
            return None, 0, 0, False, 0

        # First two bytes are total size (we already have the data)
        # Next two bytes are offset to control sequence
        data_size = struct.unpack(">H", data[0:2])[0]
        ctrl_offset = struct.unpack(">H", data[2:4])[0]

        if ctrl_offset >= len(data):
            return None, 0, 0, False, 0

        # Parse control sequence to get display parameters and duration
        ctrl_result = self._parse_control_sequence(data, ctrl_offset, header)
        if ctrl_result is None:
            return None, 0, 0, False, 0

        (
            x1,
            y1,
            x2,
            y2,
            color_indices,
            alpha_values,
            top_field_offset,
            bottom_field_offset,
            forced,
            duration_ms,
        ) = ctrl_result

        width = x2 - x1 + 1
        height = y2 - y1 + 1

        if width <= 0 or height <= 0 or width > 2000 or height > 2000:
            return None, 0, 0, False, 0

        # Decode RLE data into bitmap
        image = self._decode_rle_image(
            data,
            top_field_offset,
            bottom_field_offset,
            width,
            height,
            color_indices,
            alpha_values,
            header.palette,
        )

        return image, x1, y1, forced, duration_ms

    def _parse_control_sequence(
        self, data: bytes, offset: int, header: VobSubHeader
    ) -> tuple | None:
        """
        Parse subtitle control sequence.

        The control sequence contains timing info in SP_DCSQ_STM field.
        When we see command 0x02 (stop display), the delay value tells us
        the subtitle duration.

        SP_DCSQ format (from DVD spec):
            - 2 bytes: SP_DCSQ_STM (delay in 90KHz/1024 ticks)
            - 2 bytes: pointer to next SP_DCSQ
            - commands until 0xFF

        Delay to milliseconds: delay_ms = (delay_ticks * 1024) / 90

        Returns:
            Tuple of (x1, y1, x2, y2, colors, alphas, top_offset, bottom_offset, forced, duration_ms)
        """
        x1, y1, x2, y2 = 0, 0, header.size_x - 1, header.size_y - 1
        color_indices = [0, 1, 2, 3]  # Default palette indices
        alpha_values = [0, 15, 15, 15]  # Default alpha (0=transparent, 15=opaque)
        top_field_offset = 4  # Default data start
        bottom_field_offset = 4
        forced = False
        duration_ms = 0  # Will be set when we find stop display command

        pos = offset
        while pos < len(data) - 3:
            # Read SP_DCSQ_STM delay field (2 bytes, big-endian)
            # This is the delay in 90KHz/1024 ticks before executing commands
            delay_ticks = struct.unpack(">H", data[pos : pos + 2])[0]
            pos += 2

            if pos + 2 > len(data):
                break

            # Read next control sequence offset
            next_ctrl = struct.unpack(">H", data[pos : pos + 2])[0]
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
                    # Stop display - the delay_ticks tells us when to stop
                    # Convert to milliseconds: (ticks * 1024) / 90
                    duration_ms = int((delay_ticks * 1024) / 90)

                elif cmd == 0x03:
                    # Palette - 4 nibbles map to color slots 3,2,1,0 (SubtitleEdit order)
                    # RLE color index 0 uses slot 0, index 1 uses slot 1, etc.
                    if pos + 2 <= len(data):
                        b1, b2 = data[pos], data[pos + 1]
                        color_indices = [
                            b2 & 0x0F,  # slot 0 (background)
                            (b2 >> 4) & 0x0F,  # slot 1 (text/pattern)
                            b1 & 0x0F,  # slot 2 (emphasis1/outline)
                            (b1 >> 4) & 0x0F,  # slot 3 (emphasis2/anti-alias)
                        ]
                        pos += 2

                elif cmd == 0x04:
                    # Alpha channel - same nibble order as palette
                    if pos + 2 <= len(data):
                        b1, b2 = data[pos], data[pos + 1]
                        alpha_values = [
                            b2 & 0x0F,  # slot 0 alpha
                            (b2 >> 4) & 0x0F,  # slot 1 alpha
                            b1 & 0x0F,  # slot 2 alpha
                            (b1 >> 4) & 0x0F,  # slot 3 alpha
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
                        top_field_offset = struct.unpack(">H", data[pos : pos + 2])[0]
                        bottom_field_offset = struct.unpack(
                            ">H", data[pos + 2 : pos + 4]
                        )[0]
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

        return (
            x1,
            y1,
            x2,
            y2,
            color_indices,
            alpha_values,
            top_field_offset,
            bottom_field_offset,
            forced,
            duration_ms,
        )

    def _decode_rle_image(
        self,
        data: bytes,
        top_offset: int,
        bottom_offset: int,
        width: int,
        height: int,
        color_indices: list[int],
        alpha_values: list[int],
        palette: list[tuple[int, int, int]],
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

        Following subtile-ocr approach:
        - Convert palette RGB colors to luminance values
        - Apply dual thresholding: alpha >= threshold AND luminance >= threshold
        - Output grayscale image directly (black text on white background)

        DVD subtitles typically have:
        - Position 1: Light colored text (white/yellow) - THE ACTUAL TEXT
        - Position 2: Dark outline (black) - around text edges
        - Position 3: Gray anti-aliasing - edge smoothing

        By using luminance thresholding, we keep only the bright text and
        filter out the dark outlines, producing cleaner characters for OCR.

        Returns:
            Grayscale numpy array (black text on white background)
        """
        # DEBUG: Log color and alpha info for first few subtitles
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(
            f"VobSub decode: color_indices={color_indices}, alpha_values={alpha_values}"
        )
        palette_colors = [
            palette[idx] if idx < len(palette) else (0, 0, 0) for idx in color_indices
        ]
        logger.debug(f"VobSub decode: palette_colors={palette_colors}")

        # Create grayscale image (white background)
        image = np.full((height, width), 255, dtype=np.uint8)

        # Calculate luminance for each color position
        # Luminance formula: Y = 0.299*R + 0.587*G + 0.114*B
        luminances = []
        for idx in color_indices:
            if idx < len(palette):
                r, g, b = palette[idx]
                luma = 0.299 * r + 0.587 * g + 0.114 * b
            else:
                luma = 128  # Default gray
            luminances.append(luma)

        logger.debug(f"VobSub decode: luminances={luminances}")

        # Thresholds for determining text pixels (subtile-ocr approach)
        # Alpha threshold: pixel must be visible
        alpha_threshold = 1  # Minimum alpha (0-15 scale) to be considered visible
        # Luminance threshold: pixel must be BRIGHT (actual text, not dark outline)
        # DVD text is typically white (255) or yellow (~226), outlines are black (0)
        # Using threshold of 100 to separate text from outlines
        luma_threshold = 100

        # Build color lookup - determine if each position is TEXT or BACKGROUND
        # Position 0 = always background (transparent)
        # Positions 1, 2, 3 = text if alpha >= threshold AND luminance > luma_threshold
        # This filters out dark outlines while keeping bright text
        is_text = []
        for i, (alpha, luma) in enumerate(zip(alpha_values, luminances)):
            if i == 0:
                # Position 0: Background - always transparent
                is_text.append(False)
            elif alpha >= alpha_threshold and luma > luma_threshold:
                # Visible AND bright = actual text
                is_text.append(True)
            else:
                # Either invisible OR dark (outline/shadow) = background
                is_text.append(False)

        # FALLBACK: If no positions passed luminance threshold, fall back to alpha-only
        # This handles DVDs with dark text on light background (inverted scheme)
        if not any(is_text):
            logger.debug(
                "VobSub decode: No bright colors found, falling back to alpha-only"
            )
            is_text = []
            for i, alpha in enumerate(alpha_values):
                if i == 0:
                    is_text.append(False)
                elif alpha >= alpha_threshold:
                    is_text.append(True)
                else:
                    is_text.append(False)

        logger.debug(f"VobSub decode: is_text={is_text}")

        # Convert is_text to grayscale values: True=0 (black), False=255 (white)
        colors = [(0 if t else 255) for t in is_text]

        # Decode top field (even lines: 0, 2, 4, ...)
        self._decode_rle_field_grayscale(
            data, top_offset, image, 0, 2, width, height, colors
        )

        # Decode bottom field (odd lines: 1, 3, 5, ...)
        self._decode_rle_field_grayscale(
            data, bottom_offset, image, 1, 2, width, height, colors
        )

        # Return as RGBA for compatibility with rest of pipeline
        # Convert grayscale to RGBA (white bg, black text with full opacity)
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[:, :, 0] = image  # R
        rgba[:, :, 1] = image  # G
        rgba[:, :, 2] = image  # B
        rgba[:, :, 3] = 255  # Full opacity everywhere

        return rgba

    def _decode_rle(
        self, data: bytes, index: int, only_half: bool
    ) -> tuple[int, int, int, bool, bool]:
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
        colors: list[tuple[int, int, int, int]],
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

    def _decode_rle_field_grayscale(
        self,
        data: bytes,
        offset: int,
        image: np.ndarray,
        start_line: int,
        line_step: int,
        width: int,
        height: int,
        colors: list[int],
    ):
        """
        Decode one RLE field directly to grayscale image.

        Args:
            data: Raw subtitle data
            offset: Starting byte offset for this field
            image: Output grayscale image array (255=white, 0=black)
            start_line: First line to decode (0 for top, 1 for bottom)
            line_step: Line increment (2 for interlaced)
            width: Image width
            height: Image height
            colors: 4-element list mapping color index to grayscale (0=black, 255=white)
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

            # Get grayscale value for this color index
            gray = colors[color] if color < len(colors) else 255

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

                if y < height:
                    image[y, x] = gray
                x += 1

            # Check if we naturally hit end of line
            if x >= width:
                if only_half:
                    only_half = False
                    index += 1
                x = 0
                y += line_step
