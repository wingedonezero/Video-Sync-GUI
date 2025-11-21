# vsg_core/subtitles/pgs/parser.py
# -*- coding: utf-8 -*-
"""
PGS (Presentation Graphic Stream) SUP file binary parser.
Based on SubtitleEdit's BluRaySupParser implementation.
"""
from __future__ import annotations
import struct
from pathlib import Path
from typing import List, Optional, Dict, BinaryIO
from .models import (
    SegmentType, SupSegment, PaletteInfo, PaletteEntry,
    OdsData, PcsObject, PcsData
)


def read_big_endian_int16(data: bytes, offset: int) -> int:
    """Read 16-bit big-endian integer"""
    return struct.unpack('>H', data[offset:offset+2])[0]


def read_big_endian_int32(data: bytes, offset: int) -> int:
    """Read 32-bit big-endian integer"""
    return struct.unpack('>I', data[offset:offset+4])[0]


def read_big_endian_int24(data: bytes, offset: int) -> int:
    """Read 24-bit big-endian integer"""
    return (data[offset] << 16) | (data[offset+1] << 8) | data[offset+2]


class PgsParser:
    """Parser for PGS subtitle files"""

    def __init__(self, from_matroska: bool = False):
        """
        Initialize parser.

        Args:
            from_matroska: If True, expects Matroska-embedded format (3-byte header)
                          If False, expects standard SUP format (13-byte header)
        """
        self.from_matroska = from_matroska
        self.palettes: Dict[int, PaletteInfo] = {}  # palette_id -> PaletteInfo
        self.bitmap_objects: Dict[int, OdsData] = {}  # object_id -> OdsData
        self.compositions: List[PcsData] = []

    def parse_file(self, file_path: str) -> List[PcsData]:
        """
        Parse a PGS SUP file.

        Args:
            file_path: Path to .sup file

        Returns:
            List of PcsData objects (one per subtitle)
        """
        with open(file_path, 'rb') as f:
            return self.parse_stream(f)

    def parse_stream(self, stream: BinaryIO) -> List[PcsData]:
        """
        Parse PGS data from a stream.

        Args:
            stream: Binary stream to read from

        Returns:
            List of PcsData objects
        """
        self.compositions = []
        self.palettes = {}
        self.bitmap_objects = {}

        current_pcs: Optional[PcsData] = None

        while True:
            segment = self._read_segment(stream)
            if segment is None:
                break

            if segment.type == SegmentType.PALETTE:
                palette = self._parse_palette_segment(segment)
                if palette:
                    self.palettes[palette.palette_id] = palette
                    if current_pcs:
                        current_pcs.palette = palette

            elif segment.type == SegmentType.OBJECT:
                ods = self._parse_object_segment(segment)
                if ods:
                    if ods.is_first_fragment:
                        # New object, store it
                        self.bitmap_objects[ods.object_id] = ods
                    else:
                        # Continuation fragment, append data
                        if ods.object_id in self.bitmap_objects:
                            existing = self.bitmap_objects[ods.object_id]
                            existing.image_buffer += ods.image_buffer
                            existing.is_last_fragment = ods.is_last_fragment

                    if ods.is_last_fragment and current_pcs:
                        # Object complete, add to current composition
                        if ods.object_id in self.bitmap_objects:
                            current_pcs.bitmaps.append(self.bitmap_objects[ods.object_id])

            elif segment.type == SegmentType.COMPOSITION:
                # Parse composition segment
                pcs = self._parse_composition_segment(segment)
                if pcs:
                    # Save previous composition if exists
                    if current_pcs and current_pcs.has_complete_data():
                        self.compositions.append(current_pcs)

                    # Start new composition
                    current_pcs = pcs

                    # Try to attach existing palette
                    if pcs.palette_id in self.palettes:
                        current_pcs.palette = self.palettes[pcs.palette_id]

            elif segment.type == SegmentType.END:
                # End of display set - finalize current composition
                if current_pcs and current_pcs.has_complete_data():
                    # Don't append yet, wait for next PCS for end time
                    pass

        # Add final composition
        if current_pcs and current_pcs.has_complete_data():
            self.compositions.append(current_pcs)

        # Set end times based on next subtitle's start time
        self._calculate_end_times()

        return self.compositions

    def _read_segment(self, stream: BinaryIO) -> Optional[SupSegment]:
        """Read one segment from stream"""
        if self.from_matroska:
            # Matroska format: 3-byte header
            header = stream.read(3)
            if len(header) < 3:
                return None

            segment_type = SegmentType(header[0])
            segment_size = read_big_endian_int16(header, 1)
            pts = 0
            dts = 0

        else:
            # Standard SUP format: 13-byte header
            header = stream.read(13)
            if len(header) < 13:
                return None

            # Check magic number "PG"
            if header[0] != 0x50 or header[1] != 0x47:
                # Try to resync
                return None

            pts = read_big_endian_int32(header, 2)
            dts = read_big_endian_int32(header, 6)
            segment_type = SegmentType(header[10])
            segment_size = read_big_endian_int16(header, 11)

        # Read segment data
        data = stream.read(segment_size)
        if len(data) < segment_size:
            return None

        return SupSegment(
            type=segment_type,
            size=segment_size,
            pts_timestamp=pts,
            dts_timestamp=dts,
            data=data
        )

    def _parse_palette_segment(self, segment: SupSegment) -> Optional[PaletteInfo]:
        """
        Parse Palette Definition Segment (PDS - 0x14).

        Structure:
            - byte 0: palette_id (0-7)
            - byte 1: version
            - rest: 5-byte entries [index, Y, Cr, Cb, Alpha]
        """
        data = segment.data
        if len(data) < 2:
            return None

        palette_id = data[0]
        version = data[1]

        entries = []
        offset = 2
        while offset + 5 <= len(data):
            index = data[offset]
            y = data[offset + 1]
            cr = data[offset + 2]
            cb = data[offset + 3]
            alpha = data[offset + 4]

            entries.append(PaletteEntry(index, y, cr, cb, alpha))
            offset += 5

        return PaletteInfo(palette_id, version, entries)

    def _parse_object_segment(self, segment: SupSegment) -> Optional[OdsData]:
        """
        Parse Object Definition Segment (ODS - 0x15).

        Structure:
            - bytes 0-1: object_id (big-endian)
            - byte 2: version
            - byte 3: sequence flags
                bit 7 (0x80): first fragment
                bit 6 (0x40): last fragment

            If first fragment:
                - bytes 4-6: data length (24-bit, big-endian)
                - bytes 7-8: width (big-endian)
                - bytes 9-10: height (big-endian)
                - bytes 11+: RLE image data
            Else:
                - bytes 4+: continuation data
        """
        data = segment.data
        if len(data) < 4:
            return None

        object_id = read_big_endian_int16(data, 0)
        version = data[2]
        sequence = data[3]

        is_first = (sequence & 0x80) == 0x80
        is_last = (sequence & 0x40) == 0x40

        if is_first and len(data) >= 11:
            data_length = read_big_endian_int24(data, 4)
            width = read_big_endian_int16(data, 7)
            height = read_big_endian_int16(data, 9)
            image_data = data[11:]

            return OdsData(
                object_id=object_id,
                version=version,
                width=width,
                height=height,
                image_buffer=image_data,
                is_first_fragment=is_first,
                is_last_fragment=is_last,
                data_length=data_length
            )
        else:
            # Continuation fragment
            image_data = data[4:]
            return OdsData(
                object_id=object_id,
                version=version,
                width=0,
                height=0,
                image_buffer=image_data,
                is_first_fragment=is_first,
                is_last_fragment=is_last
            )

    def _parse_composition_segment(self, segment: SupSegment) -> Optional[PcsData]:
        """
        Parse Picture Composition Segment (PCS - 0x16).

        Structure:
            - bytes 0-1: width (big-endian)
            - bytes 2-3: height (big-endian)
            - byte 4: frame_rate
            - bytes 5-6: composition_number (big-endian)
            - byte 7: composition_state
            - byte 8: palette_update_flag
            - byte 9: palette_id
            - byte 10: number_of_objects

            For each object (8 bytes):
                - bytes 0-1: object_id
                - byte 2: window_id
                - byte 3: flags (bit 6 = forced)
                - bytes 4-5: x position
                - bytes 6-7: y position
        """
        data = segment.data
        if len(data) < 11:
            return None

        width = read_big_endian_int16(data, 0)
        height = read_big_endian_int16(data, 2)
        frame_rate = data[4]
        composition_number = read_big_endian_int16(data, 5)
        composition_state = data[7]
        palette_update_flag = data[8] == 0x80
        palette_id = data[9]
        num_objects = data[10]

        objects = []
        offset = 11

        for i in range(num_objects):
            if offset + 8 > len(data):
                break

            object_id = read_big_endian_int16(data, offset)
            window_id = data[offset + 2]
            flags = data[offset + 3]
            is_forced = (flags & 0x40) == 0x40
            x = read_big_endian_int16(data, offset + 4)
            y = read_big_endian_int16(data, offset + 6)

            objects.append(PcsObject(object_id, window_id, is_forced, x, y))
            offset += 8

        return PcsData(
            composition_number=composition_number,
            start_time_ms=segment.time_ms,
            width=width,
            height=height,
            frame_rate=frame_rate,
            palette_update_flag=palette_update_flag,
            palette_id=palette_id,
            objects=objects
        )

    def _calculate_end_times(self):
        """Calculate end times for all compositions based on next subtitle's start"""
        for i in range(len(self.compositions) - 1):
            self.compositions[i].end_time_ms = self.compositions[i + 1].start_time_ms

        # Last subtitle: add default duration (3 seconds)
        if self.compositions:
            last = self.compositions[-1]
            if last.end_time_ms is None:
                last.end_time_ms = last.start_time_ms + 3000
