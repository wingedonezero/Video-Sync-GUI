# vsg_core/subtitles/pgs/models.py
# -*- coding: utf-8 -*-
"""
Data models for PGS (Presentation Graphic Stream) subtitle parsing.
Based on SubtitleEdit's implementation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import IntEnum


class SegmentType(IntEnum):
    """PGS segment types"""
    PALETTE = 0x14      # PDS - Palette Definition Segment
    OBJECT = 0x15       # ODS - Object Definition Segment (bitmap data)
    COMPOSITION = 0x16  # PCS - Picture Composition Segment (timing/position)
    WINDOW = 0x17       # WDS - Window Display Segment
    END = 0x80          # End of Display Set


@dataclass
class SupSegment:
    """Raw segment header from SUP file"""
    type: SegmentType
    size: int
    pts_timestamp: int  # Presentation timestamp (90kHz clock)
    dts_timestamp: int  # Decode timestamp (90kHz clock)
    data: bytes

    @property
    def time_ms(self) -> float:
        """Convert PTS to milliseconds"""
        return self.pts_timestamp / 90.0


@dataclass
class PaletteEntry:
    """Single color entry in palette"""
    index: int
    y: int   # Luma
    cr: int  # Red chroma
    cb: int  # Blue chroma
    alpha: int


@dataclass
class PaletteInfo:
    """Color palette for subtitle"""
    palette_id: int
    version: int
    entries: List[PaletteEntry] = field(default_factory=list)

    def get_entry(self, index: int) -> Optional[PaletteEntry]:
        """Get palette entry by index"""
        for entry in self.entries:
            if entry.index == index:
                return entry
        return None


@dataclass
class OdsData:
    """Object Definition Segment - bitmap image data"""
    object_id: int
    version: int
    width: int
    height: int
    image_buffer: bytes  # RLE-compressed image data
    is_first_fragment: bool
    is_last_fragment: bool
    data_length: int = 0  # Total expected data length


@dataclass
class PcsObject:
    """Single object within a Picture Composition"""
    object_id: int
    window_id: int
    is_forced: bool
    x: int  # Position X coordinate
    y: int  # Position Y coordinate


@dataclass
class PcsData:
    """Complete Picture Composition Segment (one subtitle display)"""
    composition_number: int
    start_time_ms: float
    end_time_ms: Optional[float] = None
    width: int = 1920   # Composition width (video width)
    height: int = 1080  # Composition height (video height)
    frame_rate: int = 0
    palette_update_flag: bool = False
    palette_id: int = 0
    objects: List[PcsObject] = field(default_factory=list)
    palette: Optional[PaletteInfo] = None
    bitmaps: List[OdsData] = field(default_factory=list)

    def get_primary_position(self) -> Tuple[int, int]:
        """Get primary subtitle position (X, Y)"""
        if self.objects:
            return (self.objects[0].x, self.objects[0].y)
        return (0, 0)

    def has_complete_data(self) -> bool:
        """Check if this composition has all required data"""
        return (
            len(self.objects) > 0 and
            len(self.bitmaps) > 0 and
            self.palette is not None
        )


@dataclass
class SubtitleEntry:
    """Final OCR'd subtitle with positioning"""
    start_ms: float
    end_ms: float
    text: str
    x: int
    y: int
    width: int
    height: int
    is_forced: bool = False
    alignment: int = 2  # Default bottom-center

    def format_ass_time(self, ms: float) -> str:
        """Format time as ASS timestamp (H:MM:SS.CS)"""
        total_seconds = ms / 1000.0
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        centiseconds = int((ms % 1000) / 10)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

    def to_ass_dialogue(self, style: str = "Default") -> str:
        """Convert to ASS Dialogue line"""
        start = self.format_ass_time(self.start_ms)
        end = self.format_ass_time(self.end_ms)

        # Add positioning override tags
        pos_x = self.x
        pos_y = self.y
        tags = f"{{\\an{self.alignment}\\pos({pos_x},{pos_y})}}"

        text = self.text.replace("\n", "\\N")  # ASS uses \N for line breaks

        return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{tags}{text}"
