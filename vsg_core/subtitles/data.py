# vsg_core/subtitles/data.py
# -*- coding: utf-8 -*-
"""
Unified subtitle data container for all subtitle operations.

This module provides a single data structure that:
- Preserves ALL original data (metadata, styles, comments, extradata)
- Uses float milliseconds internally for timing precision
- Tracks all operations applied
- Has a single output point (no double rounding)

Design:
- Load once at start of subtitle processing
- Apply all operations to the data structure (not files)
- Write once at the end (single rounding point)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
import math
import json
import copy


@dataclass
class SubtitleStyle:
    """
    ASS/SSA style definition with all 23 fields.

    Field order matches ASS V4+ Styles format line.
    All fields preserved exactly as in source file.
    """
    name: str
    fontname: str = "Arial"
    fontsize: float = 48.0
    primary_color: str = "&H00FFFFFF"      # ASS format: &HAABBGGRR
    secondary_color: str = "&H000000FF"
    outline_color: str = "&H00000000"
    back_color: str = "&H00000000"
    bold: int = 0                           # -1 = true, 0 = false
    italic: int = 0
    underline: int = 0
    strike_out: int = 0
    scale_x: float = 100.0
    scale_y: float = 100.0
    spacing: float = 0.0
    angle: float = 0.0
    border_style: int = 1                   # 1 = outline + shadow, 3 = opaque box
    outline: float = 2.0
    shadow: float = 2.0
    alignment: int = 2                      # Numpad style: 1-9
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 10
    encoding: int = 1                       # Character set encoding

    # Original definition for debugging/comparison
    original_definition: Optional[str] = None

    @classmethod
    def from_ass_line(cls, format_fields: List[str], style_line: str) -> 'SubtitleStyle':
        """
        Parse a Style line using the Format field order.

        Args:
            format_fields: List of field names from Format line
            style_line: The Style: line content (after "Style: ")

        Returns:
            SubtitleStyle object
        """
        # Split style values (handle commas in font names by limiting splits)
        values = style_line.split(',')

        # Build a dict mapping field name -> value
        field_map = {}
        for i, field_name in enumerate(format_fields):
            if i < len(values):
                field_map[field_name.strip().lower()] = values[i].strip()

        # Map ASS field names to our dataclass fields
        style = cls(
            name=field_map.get('name', 'Default'),
            fontname=field_map.get('fontname', 'Arial'),
            fontsize=float(field_map.get('fontsize', 48)),
            primary_color=field_map.get('primarycolour', field_map.get('primarycolor', '&H00FFFFFF')),
            secondary_color=field_map.get('secondarycolour', field_map.get('secondarycolor', '&H000000FF')),
            outline_color=field_map.get('outlinecolour', field_map.get('outlinecolor', '&H00000000')),
            back_color=field_map.get('backcolour', field_map.get('backcolor', '&H00000000')),
            bold=int(field_map.get('bold', 0)),
            italic=int(field_map.get('italic', 0)),
            underline=int(field_map.get('underline', 0)),
            strike_out=int(field_map.get('strikeout', 0)),
            scale_x=float(field_map.get('scalex', 100)),
            scale_y=float(field_map.get('scaley', 100)),
            spacing=float(field_map.get('spacing', 0)),
            angle=float(field_map.get('angle', 0)),
            border_style=int(field_map.get('borderstyle', 1)),
            outline=float(field_map.get('outline', 2)),
            shadow=float(field_map.get('shadow', 2)),
            alignment=int(field_map.get('alignment', 2)),
            margin_l=int(field_map.get('marginl', 10)),
            margin_r=int(field_map.get('marginr', 10)),
            margin_v=int(field_map.get('marginv', 10)),
            encoding=int(field_map.get('encoding', 1)),
            original_definition=style_line
        )
        return style

    def to_ass_line(self, format_fields: List[str]) -> str:
        """
        Convert to ASS Style line using given format field order.

        Args:
            format_fields: List of field names for Format line

        Returns:
            Style line content (without "Style: " prefix)
        """
        # Map our field names to ASS field names
        field_values = {
            'name': self.name,
            'fontname': self.fontname,
            'fontsize': str(int(self.fontsize) if self.fontsize == int(self.fontsize) else self.fontsize),
            'primarycolour': self.primary_color,
            'primarycolor': self.primary_color,
            'secondarycolour': self.secondary_color,
            'secondarycolor': self.secondary_color,
            'outlinecolour': self.outline_color,
            'outlinecolor': self.outline_color,
            'backcolour': self.back_color,
            'backcolor': self.back_color,
            'bold': str(self.bold),
            'italic': str(self.italic),
            'underline': str(self.underline),
            'strikeout': str(self.strike_out),
            'scalex': str(int(self.scale_x) if self.scale_x == int(self.scale_x) else self.scale_x),
            'scaley': str(int(self.scale_y) if self.scale_y == int(self.scale_y) else self.scale_y),
            'spacing': str(int(self.spacing) if self.spacing == int(self.spacing) else self.spacing),
            'angle': str(int(self.angle) if self.angle == int(self.angle) else self.angle),
            'borderstyle': str(self.border_style),
            'outline': str(int(self.outline) if self.outline == int(self.outline) else self.outline),
            'shadow': str(int(self.shadow) if self.shadow == int(self.shadow) else self.shadow),
            'alignment': str(self.alignment),
            'marginl': str(self.margin_l),
            'marginr': str(self.margin_r),
            'marginv': str(self.margin_v),
            'encoding': str(self.encoding),
        }

        values = []
        for field_name in format_fields:
            key = field_name.strip().lower()
            values.append(field_values.get(key, ''))

        return ','.join(values)

    @classmethod
    def default(cls) -> 'SubtitleStyle':
        """Create a default style."""
        return cls(name='Default')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'fontname': self.fontname,
            'fontsize': self.fontsize,
            'primary_color': self.primary_color,
            'secondary_color': self.secondary_color,
            'outline_color': self.outline_color,
            'back_color': self.back_color,
            'bold': self.bold,
            'italic': self.italic,
            'underline': self.underline,
            'strike_out': self.strike_out,
            'scale_x': self.scale_x,
            'scale_y': self.scale_y,
            'spacing': self.spacing,
            'angle': self.angle,
            'border_style': self.border_style,
            'outline': self.outline,
            'shadow': self.shadow,
            'alignment': self.alignment,
            'margin_l': self.margin_l,
            'margin_r': self.margin_r,
            'margin_v': self.margin_v,
            'encoding': self.encoding,
        }


@dataclass
class SubtitleEvent:
    """
    Single subtitle event with full precision timing.

    Timing is stored as float milliseconds internally.
    Rounding to ASS centiseconds happens only on final output.
    """
    # Timing (float ms - full precision until final output)
    start_ms: float
    end_ms: float

    # Content
    text: str
    style: str = 'Default'

    # ASS event fields
    layer: int = 0
    name: str = ''                          # Actor name
    margin_l: int = 0                       # 0 = use style default
    margin_r: int = 0
    margin_v: int = 0
    effect: str = ''

    # Event type
    is_comment: bool = False                # Comment vs Dialogue

    # Aegisub extradata reference
    extradata_ids: List[int] = field(default_factory=list)

    # For debugging/comparison
    original_line: Optional[str] = None
    line_number: Optional[int] = None

    # SRT-specific (preserved if source was SRT)
    srt_index: Optional[int] = None

    @property
    def duration_ms(self) -> float:
        """Get event duration in milliseconds."""
        return self.end_ms - self.start_ms

    @classmethod
    def from_ass_line(cls, format_fields: List[str], event_line: str,
                      line_type: str = 'Dialogue', line_number: int = None) -> 'SubtitleEvent':
        """
        Parse a Dialogue/Comment line using the Format field order.

        Args:
            format_fields: List of field names from Format line
            event_line: The event line content (after "Dialogue: " or "Comment: ")
            line_type: 'Dialogue' or 'Comment'
            line_number: Original line number in file

        Returns:
            SubtitleEvent object
        """
        # Text field can contain commas, so we need to be careful
        # Split only up to the number of format fields minus 1
        num_fields = len(format_fields)
        parts = event_line.split(',', num_fields - 1)

        # Build field map
        field_map = {}
        for i, field_name in enumerate(format_fields):
            if i < len(parts):
                field_map[field_name.strip().lower()] = parts[i].strip()

        # Parse timing
        start_ms = cls._ass_time_to_ms(field_map.get('start', '0:00:00.00'))
        end_ms = cls._ass_time_to_ms(field_map.get('end', '0:00:00.00'))

        # Parse extradata IDs from effect field if present
        extradata_ids = []
        effect = field_map.get('effect', '')
        if effect.startswith('{='):
            # Format: {=123}... or {=123,456}...
            try:
                ids_str = effect[2:effect.index('}')]
                extradata_ids = [int(x) for x in ids_str.split(',') if x.strip()]
                effect = effect[effect.index('}') + 1:]
            except (ValueError, IndexError):
                pass

        return cls(
            start_ms=start_ms,
            end_ms=end_ms,
            text=field_map.get('text', ''),
            style=field_map.get('style', 'Default'),
            layer=int(field_map.get('layer', 0)),
            name=field_map.get('name', ''),
            margin_l=int(field_map.get('marginl', 0)),
            margin_r=int(field_map.get('marginr', 0)),
            margin_v=int(field_map.get('marginv', 0)),
            effect=effect,
            is_comment=(line_type.lower() == 'comment'),
            extradata_ids=extradata_ids,
            original_line=event_line,
            line_number=line_number
        )

    def to_ass_line(self, format_fields: List[str]) -> str:
        """
        Convert to ASS event line using given format field order.

        THIS IS WHERE TIMING ROUNDING HAPPENS - centisecond precision.

        Args:
            format_fields: List of field names for Format line

        Returns:
            Event line content (without "Dialogue: " or "Comment: " prefix)
        """
        # Prepare effect field with extradata IDs if present
        effect = self.effect
        if self.extradata_ids:
            ids_str = ','.join(str(x) for x in self.extradata_ids)
            effect = f'{{={ids_str}}}{effect}'

        # Map our fields to ASS field names
        field_values = {
            'layer': str(self.layer),
            'start': self._ms_to_ass_time(self.start_ms),
            'end': self._ms_to_ass_time(self.end_ms),
            'style': self.style,
            'name': self.name,
            'marginl': str(self.margin_l),
            'marginr': str(self.margin_r),
            'marginv': str(self.margin_v),
            'effect': effect,
            'text': self.text,
        }

        values = []
        for field_name in format_fields:
            key = field_name.strip().lower()
            values.append(field_values.get(key, ''))

        return ','.join(values)

    @staticmethod
    def _ass_time_to_ms(time_str: str) -> float:
        """
        Convert ASS timestamp to milliseconds (float for precision).

        Format: H:MM:SS.cc (centiseconds)
        Example: "0:01:23.45" = 83450.0 ms
        """
        try:
            parts = time_str.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                sec_parts = parts[2].split('.')
                seconds = int(sec_parts[0])
                centiseconds = int(sec_parts[1]) if len(sec_parts) > 1 else 0

                return (hours * 3600000.0 +
                        minutes * 60000.0 +
                        seconds * 1000.0 +
                        centiseconds * 10.0)
        except (ValueError, IndexError):
            pass
        return 0.0

    @staticmethod
    def _ms_to_ass_time(ms: float) -> str:
        """
        Convert milliseconds to ASS timestamp.

        THIS IS THE SINGLE ROUNDING POINT - uses floor for consistency.

        Args:
            ms: Time in milliseconds (float)

        Returns:
            ASS timestamp string: H:MM:SS.cc
        """
        # Floor to centiseconds for consistent rounding
        total_cs = int(math.floor(ms / 10))

        cs = total_cs % 100
        total_seconds = total_cs // 100
        seconds = total_seconds % 60
        total_minutes = total_seconds // 60
        minutes = total_minutes % 60
        hours = total_minutes // 60

        return f'{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}'

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'start_ms': self.start_ms,
            'end_ms': self.end_ms,
            'duration_ms': self.duration_ms,
            'text': self.text,
            'style': self.style,
            'layer': self.layer,
            'name': self.name,
            'margin_l': self.margin_l,
            'margin_r': self.margin_r,
            'margin_v': self.margin_v,
            'effect': self.effect,
            'is_comment': self.is_comment,
            'extradata_ids': self.extradata_ids,
            'srt_index': self.srt_index,
        }


@dataclass
class EmbeddedFont:
    """Embedded font data from [Fonts] section."""
    name: str
    data: str  # Base64 encoded font data

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'data_length': len(self.data)}


@dataclass
class EmbeddedGraphic:
    """Embedded graphic data from [Graphics] section."""
    name: str
    data: str  # Base64 encoded image data

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'data_length': len(self.data)}


@dataclass
class OperationRecord:
    """Record of an operation applied to the subtitle data."""
    operation: str                          # 'stepping', 'sync', 'style_patch', etc.
    timestamp: datetime = field(default_factory=datetime.now)
    parameters: Dict[str, Any] = field(default_factory=dict)
    events_affected: int = 0
    styles_affected: int = 0
    summary: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'operation': self.operation,
            'timestamp': self.timestamp.isoformat(),
            'parameters': self.parameters,
            'events_affected': self.events_affected,
            'styles_affected': self.styles_affected,
            'summary': self.summary,
        }


@dataclass
class OperationResult:
    """Result of applying an operation."""
    success: bool
    operation: str
    events_affected: int = 0
    styles_affected: int = 0
    summary: str = ''
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class SubtitleData:
    """
    Universal subtitle data container for all operations.

    This is the central data structure for subtitle processing:
    - Load once from file (ASS, SRT, VTT) or OCR output
    - Apply all operations (stepping, sync, style patches, etc.)
    - Write once at the end (single rounding point)

    All timing is stored as float milliseconds for precision.
    Rounding to ASS centiseconds happens only in save_ass().
    """

    # Source information
    source_path: Optional[Path] = None
    source_format: str = 'ass'              # 'ass', 'ssa', 'srt', 'vtt', 'ocr'
    encoding: str = 'utf-8'
    has_bom: bool = False

    # ASS Script Info section (preserved in order)
    script_info: OrderedDict = field(default_factory=OrderedDict)

    # Aegisub Project Garbage (preserved in order)
    aegisub_garbage: OrderedDict = field(default_factory=OrderedDict)

    # Aegisub Extradata (preserved as raw lines)
    extradata: List[str] = field(default_factory=list)

    # Custom/Unknown sections (preserved as raw lines, in order)
    # Key = section name (e.g., "[Custom Section]"), Value = list of lines
    custom_sections: OrderedDict = field(default_factory=OrderedDict)

    # Section order (to preserve original ordering)
    section_order: List[str] = field(default_factory=list)

    # Styles (parsed for editing)
    styles: OrderedDict = field(default_factory=OrderedDict)  # OrderedDict[str, SubtitleStyle]
    styles_format: List[str] = field(default_factory=list)    # Format field order

    # Events (dialogue and comments)
    events: List[SubtitleEvent] = field(default_factory=list)
    events_format: List[str] = field(default_factory=list)    # Format field order

    # Embedded content
    fonts: List[EmbeddedFont] = field(default_factory=list)
    graphics: List[EmbeddedGraphic] = field(default_factory=list)

    # Operation tracking
    operations: List[OperationRecord] = field(default_factory=list)

    # Comment lines between sections (preserved)
    # Key = section name, Value = list of comment lines before that section
    section_comments: OrderedDict = field(default_factory=OrderedDict)

    # Raw header lines before first section (e.g., encoding declarations)
    header_lines: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Initialize default format fields if not set."""
        if not self.styles_format:
            self.styles_format = [
                'Name', 'Fontname', 'Fontsize', 'PrimaryColour', 'SecondaryColour',
                'OutlineColour', 'BackColour', 'Bold', 'Italic', 'Underline',
                'StrikeOut', 'ScaleX', 'ScaleY', 'Spacing', 'Angle', 'BorderStyle',
                'Outline', 'Shadow', 'Alignment', 'MarginL', 'MarginR', 'MarginV',
                'Encoding'
            ]
        if not self.events_format:
            self.events_format = [
                'Layer', 'Start', 'End', 'Style', 'Name', 'MarginL', 'MarginR',
                'MarginV', 'Effect', 'Text'
            ]

    # =========================================================================
    # Factory methods
    # =========================================================================

    @classmethod
    def from_file(cls, path: Path | str) -> 'SubtitleData':
        """
        Load subtitle from file, auto-detecting format.

        Args:
            path: Path to subtitle file

        Returns:
            SubtitleData object
        """
        path = Path(path)
        ext = path.suffix.lower()

        if ext in ('.ass', '.ssa'):
            from .parsers.ass_parser import parse_ass_file
            return parse_ass_file(path)
        elif ext == '.srt':
            from .parsers.srt_parser import parse_srt_file
            return parse_srt_file(path)
        elif ext == '.vtt':
            from .parsers.srt_parser import parse_vtt_file
            return parse_vtt_file(path)
        else:
            raise ValueError(f"Unsupported subtitle format: {ext}")

    @classmethod
    def from_ass(cls, path: Path | str) -> 'SubtitleData':
        """Load from ASS/SSA file."""
        from .parsers.ass_parser import parse_ass_file
        return parse_ass_file(Path(path))

    @classmethod
    def from_srt(cls, path: Path | str) -> 'SubtitleData':
        """Load from SRT file."""
        from .parsers.srt_parser import parse_srt_file
        return parse_srt_file(Path(path))

    # =========================================================================
    # Output methods
    # =========================================================================

    def save_ass(self, path: Path | str) -> None:
        """
        Save as ASS file.

        THIS IS THE SINGLE ROUNDING POINT for timing.
        All float ms values are converted to ASS centiseconds here.

        Args:
            path: Output file path
        """
        from .writers.ass_writer import write_ass_file
        write_ass_file(self, Path(path))

    def save_srt(self, path: Path | str) -> None:
        """
        Save as SRT file.

        Args:
            path: Output file path
        """
        from .writers.srt_writer import write_srt_file
        write_srt_file(self, Path(path))

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            'source_path': str(self.source_path) if self.source_path else None,
            'source_format': self.source_format,
            'encoding': self.encoding,
            'script_info': dict(self.script_info),
            'aegisub_garbage': dict(self.aegisub_garbage),
            'extradata_count': len(self.extradata),
            'custom_sections': list(self.custom_sections.keys()),
            'styles': {name: style.to_dict() for name, style in self.styles.items()},
            'events_count': len(self.events),
            'events_sample': [e.to_dict() for e in self.events[:5]],  # First 5 for preview
            'fonts': [f.to_dict() for f in self.fonts],
            'graphics': [g.to_dict() for g in self.graphics],
            'operations': [op.to_dict() for op in self.operations],
        }

    def save_json(self, path: Path | str) -> None:
        """Save JSON representation for debugging."""
        path = Path(path)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False)

    # =========================================================================
    # Query methods
    # =========================================================================

    def get_style_names(self) -> List[str]:
        """Get list of all style names."""
        return list(self.styles.keys())

    def get_style(self, name: str) -> Optional[SubtitleStyle]:
        """Get style by name."""
        return self.styles.get(name)

    def get_events_by_style(self, style_name: str) -> List[SubtitleEvent]:
        """Get all events using a specific style."""
        return [e for e in self.events if e.style == style_name]

    def get_dialogue_events(self) -> List[SubtitleEvent]:
        """Get only dialogue events (not comments)."""
        return [e for e in self.events if not e.is_comment]

    def get_comment_events(self) -> List[SubtitleEvent]:
        """Get only comment events."""
        return [e for e in self.events if e.is_comment]

    def get_fonts_used(self) -> Set[str]:
        """
        Get all font names used in styles.

        Note: Does not include inline \\fn tags (future enhancement).
        """
        return {style.fontname for style in self.styles.values()}

    def get_timing_range(self) -> Tuple[float, float]:
        """Get the time range of all events (min start, max end)."""
        if not self.events:
            return (0.0, 0.0)

        dialogue_events = self.get_dialogue_events()
        if not dialogue_events:
            return (0.0, 0.0)

        min_start = min(e.start_ms for e in dialogue_events)
        max_end = max(e.end_ms for e in dialogue_events)
        return (min_start, max_end)

    # =========================================================================
    # Operation methods (to be implemented in operations/ modules)
    # =========================================================================

    def apply_sync_offset(self, offset_ms: float,
                          per_line_offsets: Optional[Dict[int, float]] = None,
                          exclude_comments: bool = True) -> OperationResult:
        """
        Apply timing offset to all events.

        Args:
            offset_ms: Global offset in milliseconds
            per_line_offsets: Optional dict of event_index -> additional offset
            exclude_comments: If True, don't modify comment events

        Returns:
            OperationResult with details
        """
        affected = 0

        for i, event in enumerate(self.events):
            if exclude_comments and event.is_comment:
                continue

            # Apply global offset
            event.start_ms += offset_ms
            event.end_ms += offset_ms

            # Apply per-line offset if provided
            if per_line_offsets and i in per_line_offsets:
                additional = per_line_offsets[i]
                event.start_ms += additional
                event.end_ms += additional

            affected += 1

        # Record operation
        record = OperationRecord(
            operation='sync_offset',
            parameters={'offset_ms': offset_ms, 'has_per_line': per_line_offsets is not None},
            events_affected=affected,
            summary=f'Applied {offset_ms:+.3f}ms offset to {affected} events'
        )
        self.operations.append(record)

        return OperationResult(
            success=True,
            operation='sync_offset',
            events_affected=affected,
            summary=record.summary
        )

    def apply_style_patch(self, patches: Dict[str, Dict[str, Any]]) -> OperationResult:
        """
        Apply style attribute changes.

        Args:
            patches: Dict of style_name -> {attribute: value}

        Returns:
            OperationResult with details
        """
        affected = 0

        for style_name, changes in patches.items():
            if style_name not in self.styles:
                continue

            style = self.styles[style_name]
            for attr, value in changes.items():
                if hasattr(style, attr):
                    setattr(style, attr, value)
            affected += 1

        # Record operation
        record = OperationRecord(
            operation='style_patch',
            parameters={'patches': list(patches.keys())},
            styles_affected=affected,
            summary=f'Patched {affected} style(s)'
        )
        self.operations.append(record)

        return OperationResult(
            success=True,
            operation='style_patch',
            styles_affected=affected,
            summary=record.summary
        )

    def apply_font_replacement(self, replacements: Dict[str, str]) -> OperationResult:
        """
        Replace font names in styles.

        Args:
            replacements: Dict of old_font -> new_font

        Returns:
            OperationResult with details

        Note: Currently only handles style-level fonts, not inline \\fn tags.
        """
        affected = 0

        for style in self.styles.values():
            if style.fontname in replacements:
                style.fontname = replacements[style.fontname]
                affected += 1

        # Record operation
        record = OperationRecord(
            operation='font_replacement',
            parameters={'replacements': replacements},
            styles_affected=affected,
            summary=f'Replaced fonts in {affected} style(s)'
        )
        self.operations.append(record)

        return OperationResult(
            success=True,
            operation='font_replacement',
            styles_affected=affected,
            summary=record.summary
        )

    def apply_size_multiplier(self, multiplier: float) -> OperationResult:
        """
        Multiply all font sizes by a factor.

        Args:
            multiplier: Size multiplier (e.g., 1.5 for 50% larger)

        Returns:
            OperationResult with details
        """
        if abs(multiplier - 1.0) < 1e-6:
            return OperationResult(
                success=True,
                operation='size_multiplier',
                summary='No size change needed (multiplier ~1.0)'
            )

        affected = 0
        for style in self.styles.values():
            style.fontsize *= multiplier
            affected += 1

        # Record operation
        record = OperationRecord(
            operation='size_multiplier',
            parameters={'multiplier': multiplier},
            styles_affected=affected,
            summary=f'Applied {multiplier:.2f}x size multiplier to {affected} style(s)'
        )
        self.operations.append(record)

        return OperationResult(
            success=True,
            operation='size_multiplier',
            styles_affected=affected,
            summary=record.summary
        )

    def apply_stepping(self, edl_segments: List[Dict[str, Any]]) -> OperationResult:
        """
        Apply stepping/EDL timing adjustments.

        Args:
            edl_segments: List of EDL segment dictionaries with timing info

        Returns:
            OperationResult with details
        """
        # Import the stepping logic
        from .operations.stepping import apply_stepping_to_data
        return apply_stepping_to_data(self, edl_segments)

    def copy(self) -> 'SubtitleData':
        """Create a deep copy of this subtitle data."""
        return copy.deepcopy(self)
