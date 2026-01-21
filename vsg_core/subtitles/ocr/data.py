# vsg_core/subtitles/ocr/data.py
# -*- coding: utf-8 -*-
"""
OCR Subtitle Data Container

Provides a rich data structure that preserves all OCR output data throughout
the processing pipeline. This enables:
- Single-point ASS conversion at the end (no intermediate rounding)
- Full preservation of position, color, and metadata
- JSON serialization for debugging and potential manual editing
- Future extensibility for styles, fonts, etc.

The data flows through: OCR → Sync → Styles → Final ASS Write
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
import json
import math


@dataclass
class OCRSubtitleEntry:
    """
    A single subtitle entry with full precision timing and metadata.

    Timing is stored as float milliseconds to preserve precision through
    all processing steps. Rounding to centiseconds happens only at final
    ASS output.
    """
    index: int
    start_ms: float  # Float for precision - only round at final output
    end_ms: float
    text: str

    # Position data (from source image)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    frame_width: int = 720
    frame_height: int = 480

    # Flags
    is_forced: bool = False

    # OCR metadata
    confidence: float = 0.0
    raw_ocr_text: str = ""  # Text before post-processing fixes
    unknown_words: List[str] = field(default_factory=list)
    fixes_applied: Dict[str, int] = field(default_factory=dict)  # {fix_name: count}

    # Color data (from VobSub palette)
    # These are the actual RGBA colors used for this subtitle
    # Positions: 0=background, 1=text, 2=outline, 3=anti-alias
    subtitle_colors: Optional[List[Tuple[int, int, int, int]]] = None
    dominant_color: Optional[Tuple[int, int, int]] = None  # Main text color (RGB)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'index': self.index,
            'start_ms': self.start_ms,
            'end_ms': self.end_ms,
            'text': self.text,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'frame_width': self.frame_width,
            'frame_height': self.frame_height,
            'is_forced': self.is_forced,
            'confidence': self.confidence,
            'raw_ocr_text': self.raw_ocr_text,
            'unknown_words': self.unknown_words,
            'fixes_applied': self.fixes_applied,
            'subtitle_colors': self.subtitle_colors,
            'dominant_color': self.dominant_color,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OCRSubtitleEntry':
        """Create from dictionary."""
        return cls(
            index=data['index'],
            start_ms=float(data['start_ms']),
            end_ms=float(data['end_ms']),
            text=data['text'],
            x=data.get('x', 0),
            y=data.get('y', 0),
            width=data.get('width', 0),
            height=data.get('height', 0),
            frame_width=data.get('frame_width', 720),
            frame_height=data.get('frame_height', 480),
            is_forced=data.get('is_forced', False),
            confidence=data.get('confidence', 0.0),
            raw_ocr_text=data.get('raw_ocr_text', ''),
            unknown_words=data.get('unknown_words', []),
            fixes_applied=data.get('fixes_applied', {}),
            subtitle_colors=data.get('subtitle_colors'),
            dominant_color=tuple(data['dominant_color']) if data.get('dominant_color') else None,
        )

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        return self.end_ms - self.start_ms

    @property
    def y_position_percent(self) -> float:
        """Y position as percentage of frame height (for alignment detection)."""
        if self.frame_height == 0:
            return 100.0
        center_y = self.y + (self.height / 2)
        return (center_y / self.frame_height) * 100

    def is_bottom_positioned(self, threshold: float = 75.0) -> bool:
        """Check if subtitle is at bottom of frame."""
        return self.y_position_percent >= threshold

    def is_top_positioned(self, threshold: float = 25.0) -> bool:
        """Check if subtitle is at top of frame."""
        return self.y_position_percent <= threshold


@dataclass
class OCRSubtitleData:
    """
    Complete OCR output container - preserves all data until final ASS generation.

    This is the central data structure that flows through:
    1. OCR Pipeline (creation)
    2. Sync Mode (timing adjustment)
    3. Style Engine (style application)
    4. Final Writer (single ASS conversion)
    """

    # Core data
    entries: List[OCRSubtitleEntry] = field(default_factory=list)

    # Source information
    source_file: str = ""
    source_format: str = "vobsub"  # 'vobsub', 'pgs', etc.
    source_resolution: Tuple[int, int] = (720, 480)

    # OCR settings used
    ocr_engine: str = "paddleocr"
    language: str = "eng"

    # Global palette (from VobSub IDX header - 16 colors)
    master_palette: Optional[List[Tuple[int, int, int]]] = None

    # Processing metadata
    total_fixes_applied: Dict[str, int] = field(default_factory=dict)
    total_unknown_words: List[str] = field(default_factory=list)
    processing_duration_seconds: float = 0.0

    # Sync adjustment tracking
    sync_offset_applied_ms: float = 0.0
    sync_mode_used: str = ""

    # Style settings (can be modified before final output)
    style_config: Dict[str, Any] = field(default_factory=lambda: {
        'font_name': 'Arial',
        'font_size': 48,
        'primary_color': '&H00FFFFFF',  # White
        'outline_color': '&H00000000',  # Black
        'outline_width': 2.0,
        'shadow_depth': 1.0,
        'margin_v': 30,
    })

    # Output settings
    output_resolution: Tuple[int, int] = (1920, 1080)
    preserve_positions: bool = True
    bottom_threshold_percent: float = 75.0
    top_threshold_percent: float = 25.0

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        data = {
            'version': '1.0',
            'source_file': self.source_file,
            'source_format': self.source_format,
            'source_resolution': list(self.source_resolution),
            'ocr_engine': self.ocr_engine,
            'language': self.language,
            'master_palette': self.master_palette,
            'total_fixes_applied': self.total_fixes_applied,
            'total_unknown_words': self.total_unknown_words,
            'processing_duration_seconds': self.processing_duration_seconds,
            'sync_offset_applied_ms': self.sync_offset_applied_ms,
            'sync_mode_used': self.sync_mode_used,
            'style_config': self.style_config,
            'output_resolution': list(self.output_resolution),
            'preserve_positions': self.preserve_positions,
            'bottom_threshold_percent': self.bottom_threshold_percent,
            'top_threshold_percent': self.top_threshold_percent,
            'entries': [e.to_dict() for e in self.entries],
        }
        return json.dumps(data, indent=indent, ensure_ascii=False)

    def save_json(self, path: Path):
        """Save to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    @classmethod
    def from_json(cls, json_str: str) -> 'OCRSubtitleData':
        """Load from JSON string."""
        data = json.loads(json_str)

        obj = cls(
            source_file=data.get('source_file', ''),
            source_format=data.get('source_format', 'vobsub'),
            source_resolution=tuple(data.get('source_resolution', [720, 480])),
            ocr_engine=data.get('ocr_engine', 'paddleocr'),
            language=data.get('language', 'eng'),
            master_palette=data.get('master_palette'),
            total_fixes_applied=data.get('total_fixes_applied', {}),
            total_unknown_words=data.get('total_unknown_words', []),
            processing_duration_seconds=data.get('processing_duration_seconds', 0.0),
            sync_offset_applied_ms=data.get('sync_offset_applied_ms', 0.0),
            sync_mode_used=data.get('sync_mode_used', ''),
            style_config=data.get('style_config', {}),
            output_resolution=tuple(data.get('output_resolution', [1920, 1080])),
            preserve_positions=data.get('preserve_positions', True),
            bottom_threshold_percent=data.get('bottom_threshold_percent', 75.0),
            top_threshold_percent=data.get('top_threshold_percent', 25.0),
        )

        obj.entries = [OCRSubtitleEntry.from_dict(e) for e in data.get('entries', [])]
        return obj

    @classmethod
    def load_json(cls, path: Path) -> 'OCRSubtitleData':
        """Load from JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_json(f.read())

    def apply_timing_offset(self, offset_ms: float):
        """
        Apply a timing offset to all entries.

        This modifies timing in-place while preserving float precision.
        """
        for entry in self.entries:
            entry.start_ms += offset_ms
            entry.end_ms += offset_ms
        self.sync_offset_applied_ms += offset_ms

    def to_ass(self) -> str:
        """
        Convert to ASS format string.

        This is the SINGLE POINT where timing gets rounded to centiseconds.
        All precision is preserved until this final conversion.
        """
        lines = []

        # Script Info section
        lines.extend([
            '[Script Info]',
            '; Generated by Video-Sync-GUI OCR System',
            f'; Source: {self.source_file}',
            f'; OCR Engine: {self.ocr_engine}',
            f'; Language: {self.language}',
            f'PlayResX: {self.output_resolution[0]}',
            f'PlayResY: {self.output_resolution[1]}',
            'ScriptType: v4.00+',
            'WrapStyle: 0',
            'ScaledBorderAndShadow: yes',
            '',
        ])

        # Styles section
        style = self.style_config
        lines.extend([
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
            'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, '
            'ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, '
            'MarginL, MarginR, MarginV, Encoding',
        ])

        # Default style (bottom alignment)
        default_style = (
            f"Style: Default,{style.get('font_name', 'Arial')},"
            f"{style.get('font_size', 48)},{style.get('primary_color', '&H00FFFFFF')},"
            f"&H000000FF,{style.get('outline_color', '&H00000000')},&H00000000,"
            f"0,0,0,0,100,100,0,0,1,{style.get('outline_width', 2.0)},"
            f"{style.get('shadow_depth', 1.0)},2,10,10,{style.get('margin_v', 30)},1"
        )
        lines.append(default_style)

        # Top style (for top-positioned subtitles)
        top_style = (
            f"Style: Top,{style.get('font_name', 'Arial')},"
            f"{style.get('font_size', 48)},{style.get('primary_color', '&H00FFFFFF')},"
            f"&H000000FF,{style.get('outline_color', '&H00000000')},&H00000000,"
            f"0,0,0,0,100,100,0,0,1,{style.get('outline_width', 2.0)},"
            f"{style.get('shadow_depth', 1.0)},8,10,10,{style.get('margin_v', 30)},1"
        )
        lines.append(top_style)
        lines.append('')

        # Events section
        lines.extend([
            '[Events]',
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
        ])

        # Add dialogue lines
        for entry in self.entries:
            start = self._ms_to_ass_time(entry.start_ms)
            end = self._ms_to_ass_time(entry.end_ms)
            text = self._escape_ass_text(entry.text)

            # Determine style based on position
            style_name = 'Default'
            if self.preserve_positions:
                if entry.is_top_positioned(self.top_threshold_percent):
                    style_name = 'Top'
                # Could add middle positioning with \pos() here in future

            dialogue = f'Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}'
            lines.append(dialogue)

        return '\n'.join(lines)

    def save_ass(self, path: Path):
        """Save to ASS file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write(self.to_ass())

    def to_srt(self) -> str:
        """
        Convert to SRT format string.

        SRT supports millisecond precision, so minimal rounding occurs.
        """
        lines = []

        for i, entry in enumerate(self.entries, 1):
            start = self._ms_to_srt_time(entry.start_ms)
            end = self._ms_to_srt_time(entry.end_ms)
            text = entry.text.strip()

            lines.extend([
                str(i),
                f'{start} --> {end}',
                text,
                '',
            ])

        return '\n'.join(lines)

    def save_srt(self, path: Path):
        """Save to SRT file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_srt())

    @staticmethod
    def _ms_to_ass_time(ms: float) -> str:
        """
        Convert milliseconds to ASS time format (H:MM:SS.cc).

        THIS IS WHERE ROUNDING HAPPENS - centisecond precision.
        Uses floor to ensure subtitle appears at or after the intended time.
        """
        if ms < 0:
            ms = 0

        # Convert to centiseconds with floor (single rounding point)
        total_cs = int(math.floor(ms / 10))

        cs = total_cs % 100
        total_seconds = total_cs // 100
        seconds = total_seconds % 60
        total_minutes = total_seconds // 60
        minutes = total_minutes % 60
        hours = total_minutes // 60

        return f'{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}'

    @staticmethod
    def _ms_to_srt_time(ms: float) -> str:
        """
        Convert milliseconds to SRT time format (HH:MM:SS,mmm).

        SRT supports milliseconds, so we round to nearest ms.
        """
        if ms < 0:
            ms = 0

        ms_int = int(round(ms))

        milliseconds = ms_int % 1000
        total_seconds = ms_int // 1000
        seconds = total_seconds % 60
        total_minutes = total_seconds // 60
        minutes = total_minutes % 60
        hours = total_minutes // 60

        return f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'

    @staticmethod
    def _escape_ass_text(text: str) -> str:
        """Escape special characters for ASS format."""
        # Replace newlines with ASS hard line break
        text = text.replace('\n', '\\N')
        text = text.replace('\\n', '\\N')
        return text

    def get_summary(self) -> Dict[str, Any]:
        """Get processing summary for reports."""
        return {
            'total_subtitles': len(self.entries),
            'source_format': self.source_format,
            'source_resolution': f'{self.source_resolution[0]}x{self.source_resolution[1]}',
            'ocr_engine': self.ocr_engine,
            'language': self.language,
            'total_fixes': sum(self.total_fixes_applied.values()),
            'unknown_words_count': len(self.total_unknown_words),
            'sync_offset_ms': self.sync_offset_applied_ms,
            'sync_mode': self.sync_mode_used,
            'processing_time_seconds': self.processing_duration_seconds,
        }
