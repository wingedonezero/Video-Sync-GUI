# vsg_core/subtitles/data.py
"""
Unified subtitle data container for all subtitle operations.

This module provides the central data structure for subtitle processing:
- Load once from file (ASS, SRT) or OCR output
- Apply operations (stepping, sync, style patches, etc.)
- Write once at the end (single rounding point)

All timing is stored as FLOAT MILLISECONDS internally.
Rounding happens ONLY at final save (ASS → centiseconds, SRT → milliseconds).
"""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# =============================================================================
# Per-Event Metadata (OCR, Sync, Stepping)
# =============================================================================


@dataclass
class OCREventData:
    """OCR-specific metadata for a single subtitle event."""

    index: int  # OCR index (sub_0000.png -> 0)
    image: str = ""  # Debug image filename (sub_0000.png)
    confidence: float = 0.0  # OCR confidence 0-100
    raw_text: str = ""  # Raw OCR output before corrections
    fixes_applied: dict[str, int] = field(default_factory=dict)  # fix_name -> count
    unknown_words: list[str] = field(default_factory=list)

    # Position data from source image
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    frame_width: int = 0
    frame_height: int = 0

    # VobSub specific
    is_forced: bool = False
    subtitle_colors: list[list[int]] = field(default_factory=list)  # 4 RGBA colors
    dominant_color: list[int] = field(default_factory=list)  # RGB

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "image": self.image,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
            "fixes_applied": self.fixes_applied,
            "unknown_words": self.unknown_words,
            "position": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
            "frame_size": [self.frame_width, self.frame_height],
            "is_forced": self.is_forced,
            "subtitle_colors": self.subtitle_colors,
            "dominant_color": self.dominant_color,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OCREventData:
        position = data.get("position", {}) or {}
        frame_size = data.get("frame_size", [0, 0]) or [0, 0]
        return cls(
            index=data.get("index", 0),
            image=data.get("image", ""),
            confidence=float(data.get("confidence", 0.0)),
            raw_text=data.get("raw_text", ""),
            fixes_applied=data.get("fixes_applied", {}) or {},
            unknown_words=data.get("unknown_words", []) or [],
            x=int(position.get("x", 0)),
            y=int(position.get("y", 0)),
            width=int(position.get("width", 0)),
            height=int(position.get("height", 0)),
            frame_width=int(frame_size[0]) if len(frame_size) > 0 else 0,
            frame_height=int(frame_size[1]) if len(frame_size) > 1 else 0,
            is_forced=bool(data.get("is_forced", False)),
            subtitle_colors=data.get("subtitle_colors", []) or [],
            dominant_color=data.get("dominant_color", []) or [],
        )


@dataclass
class SyncEventData:
    """Sync-specific metadata for a single subtitle event."""

    original_start_ms: float = 0.0  # Start before sync
    original_end_ms: float = 0.0  # End before sync
    start_adjustment_ms: float = 0.0  # Delta applied to start
    end_adjustment_ms: float = 0.0  # Delta applied to end
    snapped_to_frame: bool = False  # Whether frame alignment was used
    target_frame_start: int | None = None  # Frame number if snapped
    target_frame_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "original_start_ms": self.original_start_ms,
            "original_end_ms": self.original_end_ms,
            "start_adjustment_ms": self.start_adjustment_ms,
            "end_adjustment_ms": self.end_adjustment_ms,
            "snapped_to_frame": self.snapped_to_frame,
        }
        if self.target_frame_start is not None:
            result["target_frame_start"] = self.target_frame_start
        if self.target_frame_end is not None:
            result["target_frame_end"] = self.target_frame_end
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncEventData:
        return cls(
            original_start_ms=float(data.get("original_start_ms", 0.0)),
            original_end_ms=float(data.get("original_end_ms", 0.0)),
            start_adjustment_ms=float(data.get("start_adjustment_ms", 0.0)),
            end_adjustment_ms=float(data.get("end_adjustment_ms", 0.0)),
            snapped_to_frame=bool(data.get("snapped_to_frame", False)),
            target_frame_start=data.get("target_frame_start"),
            target_frame_end=data.get("target_frame_end"),
        )


@dataclass
class SteppingEventData:
    """Stepping-specific metadata for a single subtitle event."""

    original_start_ms: float = 0.0
    original_end_ms: float = 0.0
    segment_index: int | None = None  # Which EDL segment it fell into
    adjustment_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_start_ms": self.original_start_ms,
            "original_end_ms": self.original_end_ms,
            "segment_index": self.segment_index,
            "adjustment_ms": self.adjustment_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SteppingEventData:
        return cls(
            original_start_ms=float(data.get("original_start_ms", 0.0)),
            original_end_ms=float(data.get("original_end_ms", 0.0)),
            segment_index=data.get("segment_index"),
            adjustment_ms=float(data.get("adjustment_ms", 0.0)),
        )


# =============================================================================
# Document-Level OCR Metadata
# =============================================================================


@dataclass
class OCRMetadata:
    """Document-level OCR metadata and statistics."""

    engine: str = "tesseract"
    language: str = "eng"
    source_format: str = "vobsub"  # vobsub, pgs, etc.
    source_file: str = ""
    source_resolution: list[int] = field(default_factory=lambda: [0, 0])
    master_palette: list[list[int]] = field(default_factory=list)  # 16 colors from IDX

    # Statistics
    total_subtitles: int = 0
    successful: int = 0
    failed: int = 0
    average_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0
    total_fixes_applied: int = 0
    positioned_subtitles: int = 0

    # Aggregated data
    fixes_by_type: dict[str, int] = field(default_factory=dict)
    unknown_words: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "language": self.language,
            "source_format": self.source_format,
            "source_file": self.source_file,
            "source_resolution": self.source_resolution,
            "master_palette": self.master_palette,
            "statistics": {
                "total_subtitles": self.total_subtitles,
                "successful": self.successful,
                "failed": self.failed,
                "average_confidence": self.average_confidence,
                "min_confidence": self.min_confidence,
                "max_confidence": self.max_confidence,
                "total_fixes_applied": self.total_fixes_applied,
                "positioned_subtitles": self.positioned_subtitles,
            },
            "fixes_by_type": self.fixes_by_type,
            "unknown_words": self.unknown_words,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OCRMetadata:
        stats = data.get("statistics", {}) or {}
        return cls(
            engine=data.get("engine", "tesseract"),
            language=data.get("language", "eng"),
            source_format=data.get("source_format", "vobsub"),
            source_file=data.get("source_file", ""),
            source_resolution=data.get("source_resolution", [0, 0]) or [0, 0],
            master_palette=data.get("master_palette", []) or [],
            total_subtitles=int(stats.get("total_subtitles", 0)),
            successful=int(stats.get("successful", 0)),
            failed=int(stats.get("failed", 0)),
            average_confidence=float(stats.get("average_confidence", 0.0)),
            min_confidence=float(stats.get("min_confidence", 0.0)),
            max_confidence=float(stats.get("max_confidence", 0.0)),
            total_fixes_applied=int(stats.get("total_fixes_applied", 0)),
            positioned_subtitles=int(stats.get("positioned_subtitles", 0)),
            fixes_by_type=data.get("fixes_by_type", {}) or {},
            unknown_words=data.get("unknown_words", []) or [],
        )


# =============================================================================
# Style Definition
# =============================================================================


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
    primary_color: str = "&H00FFFFFF"  # ASS format: &HAABBGGRR
    secondary_color: str = "&H000000FF"
    outline_color: str = "&H00000000"
    back_color: str = "&H00000000"
    bold: int = 0  # -1 = true, 0 = false
    italic: int = 0
    underline: int = 0
    strike_out: int = 0
    scale_x: float = 100.0
    scale_y: float = 100.0
    spacing: float = 0.0
    angle: float = 0.0
    border_style: int = 1  # 1 = outline + shadow, 3 = opaque box
    outline: float = 2.0
    shadow: float = 2.0
    alignment: int = 2  # Numpad style: 1-9
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 10
    encoding: int = 1  # Character set encoding

    # Original line for debugging
    _original_line: str | None = field(default=None, repr=False)

    @classmethod
    def from_format_line(
        cls, format_fields: list[str], values: list[str]
    ) -> SubtitleStyle:
        """
        Parse style from Format fields and values.

        Args:
            format_fields: Field names from Format line
            values: Values from Style line

        Returns:
            SubtitleStyle instance
        """
        # Map format field to value
        field_map = {}
        for i, field_name in enumerate(format_fields):
            if i < len(values):
                field_map[field_name.strip().lower()] = values[i].strip()

        return cls(
            name=field_map.get("name", "Default"),
            fontname=field_map.get("fontname", "Arial"),
            fontsize=float(field_map.get("fontsize", 48)),
            primary_color=field_map.get(
                "primarycolour", field_map.get("primarycolor", "&H00FFFFFF")
            ),
            secondary_color=field_map.get(
                "secondarycolour", field_map.get("secondarycolor", "&H000000FF")
            ),
            outline_color=field_map.get(
                "outlinecolour", field_map.get("outlinecolor", "&H00000000")
            ),
            back_color=field_map.get(
                "backcolour", field_map.get("backcolor", "&H00000000")
            ),
            bold=int(field_map.get("bold", 0)),
            italic=int(field_map.get("italic", 0)),
            underline=int(field_map.get("underline", 0)),
            strike_out=int(field_map.get("strikeout", 0)),
            scale_x=float(field_map.get("scalex", 100)),
            scale_y=float(field_map.get("scaley", 100)),
            spacing=float(field_map.get("spacing", 0)),
            angle=float(field_map.get("angle", 0)),
            border_style=int(field_map.get("borderstyle", 1)),
            outline=float(field_map.get("outline", 2)),
            shadow=float(field_map.get("shadow", 2)),
            alignment=int(field_map.get("alignment", 2)),
            margin_l=int(field_map.get("marginl", 10)),
            margin_r=int(field_map.get("marginr", 10)),
            margin_v=int(field_map.get("marginv", 10)),
            encoding=int(field_map.get("encoding", 1)),
        )

    def to_format_values(self, format_fields: list[str]) -> list[str]:
        """
        Convert to values list matching format fields.

        Args:
            format_fields: Field names for output Format line

        Returns:
            List of string values in format order
        """
        # Map our fields to ASS field names
        value_map = {
            "name": self.name,
            "fontname": self.fontname,
            "fontsize": _format_number(self.fontsize),
            "primarycolour": self.primary_color,
            "primarycolor": self.primary_color,
            "secondarycolour": self.secondary_color,
            "secondarycolor": self.secondary_color,
            "outlinecolour": self.outline_color,
            "outlinecolor": self.outline_color,
            "backcolour": self.back_color,
            "backcolor": self.back_color,
            "bold": str(self.bold),
            "italic": str(self.italic),
            "underline": str(self.underline),
            "strikeout": str(self.strike_out),
            "scalex": _format_number(self.scale_x),
            "scaley": _format_number(self.scale_y),
            "spacing": _format_number(self.spacing),
            "angle": _format_number(self.angle),
            "borderstyle": str(self.border_style),
            "outline": _format_number(self.outline),
            "shadow": _format_number(self.shadow),
            "alignment": str(self.alignment),
            "marginl": str(self.margin_l),
            "marginr": str(self.margin_r),
            "marginv": str(self.margin_v),
            "encoding": str(self.encoding),
        }

        return [value_map.get(f.strip().lower(), "") for f in format_fields]

    @classmethod
    def default(cls) -> SubtitleStyle:
        """Create default style."""
        return cls(name="Default")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "fontname": self.fontname,
            "fontsize": self.fontsize,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "outline_color": self.outline_color,
            "back_color": self.back_color,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "strike_out": self.strike_out,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "spacing": self.spacing,
            "angle": self.angle,
            "border_style": self.border_style,
            "outline": self.outline,
            "shadow": self.shadow,
            "alignment": self.alignment,
            "margin_l": self.margin_l,
            "margin_r": self.margin_r,
            "margin_v": self.margin_v,
            "encoding": self.encoding,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubtitleStyle:
        return cls(
            name=data.get("name", "Default"),
            fontname=data.get("fontname", "Arial"),
            fontsize=float(data.get("fontsize", 48.0)),
            primary_color=data.get("primary_color", "&H00FFFFFF"),
            secondary_color=data.get("secondary_color", "&H000000FF"),
            outline_color=data.get("outline_color", "&H00000000"),
            back_color=data.get("back_color", "&H00000000"),
            bold=int(data.get("bold", 0)),
            italic=int(data.get("italic", 0)),
            underline=int(data.get("underline", 0)),
            strike_out=int(data.get("strike_out", 0)),
            scale_x=float(data.get("scale_x", 100.0)),
            scale_y=float(data.get("scale_y", 100.0)),
            spacing=float(data.get("spacing", 0.0)),
            angle=float(data.get("angle", 0.0)),
            border_style=int(data.get("border_style", 1)),
            outline=float(data.get("outline", 2.0)),
            shadow=float(data.get("shadow", 2.0)),
            alignment=int(data.get("alignment", 2)),
            margin_l=int(data.get("margin_l", 10)),
            margin_r=int(data.get("margin_r", 10)),
            margin_v=int(data.get("margin_v", 10)),
            encoding=int(data.get("encoding", 1)),
        )


# =============================================================================
# Event Definition
# =============================================================================


@dataclass
class SubtitleEvent:
    """
    Single subtitle event with FLOAT MILLISECOND timing.

    Timing precision is preserved throughout all operations.
    Rounding to centiseconds (ASS) happens only at final save.
    """

    # Timing - FLOAT MS for precision
    start_ms: float
    end_ms: float

    # Content
    text: str
    style: str = "Default"

    # ASS fields
    layer: int = 0
    name: str = ""  # Actor field
    margin_l: int = 0
    margin_r: int = 0
    margin_v: int = 0
    effect: str = ""

    # Type
    is_comment: bool = False  # Comment vs Dialogue

    # Aegisub extradata reference (list of IDs)
    extradata_ids: list[int] = field(default_factory=list)

    # Source tracking
    original_index: int | None = None  # Original position in file
    srt_index: int | None = None  # SRT sequence number if from SRT

    # Original line for debugging
    _original_line: str | None = field(default=None, repr=False)

    # Optional per-event metadata (populated by operations)
    ocr: OCREventData | None = None  # OCR data if from OCR
    sync: SyncEventData | None = None  # Sync data after sync applied
    stepping: SteppingEventData | None = None  # Stepping data after stepping

    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        return self.end_ms - self.start_ms

    @classmethod
    def from_format_line(
        cls, format_fields: list[str], values: list[str], is_comment: bool = False
    ) -> SubtitleEvent:
        """
        Parse event from Format fields and values.

        Args:
            format_fields: Field names from Format line
            values: Values from Dialogue/Comment line
            is_comment: Whether this is a Comment line

        Returns:
            SubtitleEvent instance
        """
        # Map format field to value
        # Note: Text field may contain commas, so we need special handling
        field_map = {}
        text_idx = None

        for i, field_name in enumerate(format_fields):
            key = field_name.strip().lower()
            if key == "text":
                text_idx = i
                break
            if i < len(values):
                field_map[key] = values[i].strip()

        # Text is everything from text_idx onwards (may contain commas)
        text = ""
        if text_idx is not None and text_idx < len(values):
            text = ",".join(values[text_idx:])

        # Parse timing
        start_ms = _parse_ass_time(field_map.get("start", "0:00:00.00"))
        end_ms = _parse_ass_time(field_map.get("end", "0:00:00.00"))

        # Parse extradata IDs if present
        extradata_ids = []
        if "extradataid" in field_map or "extradata" in field_map:
            ed_str = field_map.get("extradataid", field_map.get("extradata", ""))
            if ed_str:
                # Format: {=N} or {=N,M,...}
                import re

                match = re.search(r"\{=(\d+(?:,\d+)*)\}", ed_str)
                if match:
                    extradata_ids = [int(x) for x in match.group(1).split(",")]

        return cls(
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            style=field_map.get("style", "Default"),
            layer=int(field_map.get("layer", 0)),
            name=field_map.get("name", field_map.get("actor", "")),
            margin_l=int(field_map.get("marginl", 0)),
            margin_r=int(field_map.get("marginr", 0)),
            margin_v=int(field_map.get("marginv", 0)),
            effect=field_map.get("effect", ""),
            is_comment=is_comment,
            extradata_ids=extradata_ids,
        )

    def to_format_values(self, format_fields: list[str]) -> list[str]:
        """
        Convert to values list matching format fields.

        Note: Timing is NOT rounded here - that happens in the writer.
        This returns placeholder timing strings that the writer replaces.

        Args:
            format_fields: Field names for output Format line

        Returns:
            List of string values in format order
        """
        value_map = {
            "layer": str(self.layer),
            "start": "__START_MS__",  # Placeholder - writer handles rounding
            "end": "__END_MS__",  # Placeholder - writer handles rounding
            "style": self.style,
            "name": self.name,
            "actor": self.name,
            "marginl": str(self.margin_l),
            "marginr": str(self.margin_r),
            "marginv": str(self.margin_v),
            "effect": self.effect,
            "text": self.text,
        }

        return [value_map.get(f.strip().lower(), "") for f in format_fields]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "index": self.original_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "text": self.text,
            "style": self.style,
            "layer": self.layer,
            "name": self.name,
            "margin_l": self.margin_l,
            "margin_r": self.margin_r,
            "margin_v": self.margin_v,
            "effect": self.effect,
            "is_comment": self.is_comment,
        }

        # Include optional metadata if present
        if self.ocr is not None:
            result["ocr"] = self.ocr.to_dict()
        if self.sync is not None:
            result["sync"] = self.sync.to_dict()
        if self.stepping is not None:
            result["stepping"] = self.stepping.to_dict()

        # Include extra tracking if present
        if self.extradata_ids:
            result["extradata_ids"] = self.extradata_ids
        if self.srt_index is not None:
            result["srt_index"] = self.srt_index

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubtitleEvent:
        event = cls(
            start_ms=float(data.get("start_ms", 0.0)),
            end_ms=float(data.get("end_ms", 0.0)),
            text=data.get("text", ""),
            style=data.get("style", "Default"),
            layer=int(data.get("layer", 0)),
            name=data.get("name", ""),
            margin_l=int(data.get("margin_l", 0)),
            margin_r=int(data.get("margin_r", 0)),
            margin_v=int(data.get("margin_v", 0)),
            effect=data.get("effect", ""),
            is_comment=bool(data.get("is_comment", False)),
            extradata_ids=data.get("extradata_ids", []) or [],
            original_index=data.get("index"),
            srt_index=data.get("srt_index"),
        )
        ocr_data = data.get("ocr")
        if ocr_data:
            event.ocr = OCREventData.from_dict(ocr_data)
        sync_data = data.get("sync")
        if sync_data:
            event.sync = SyncEventData.from_dict(sync_data)
        stepping_data = data.get("stepping")
        if stepping_data:
            event.stepping = SteppingEventData.from_dict(stepping_data)
        return event


# =============================================================================
# Embedded Content
# =============================================================================


@dataclass
class EmbeddedFont:
    """Embedded font from [Fonts] section."""

    name: str
    data: str  # Base64 encoded or raw UUE data

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "data_length": len(self.data)}


@dataclass
class EmbeddedGraphic:
    """Embedded graphic from [Graphics] section."""

    name: str
    data: str  # Base64 encoded or raw UUE data

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "data_length": len(self.data)}


# =============================================================================
# Operation Tracking
# =============================================================================


@dataclass
class OperationRecord:
    """Record of an operation applied to subtitle data."""

    operation: str  # 'stepping', 'sync', 'style_patch', etc.
    timestamp: datetime = field(default_factory=datetime.now)
    parameters: dict[str, Any] = field(default_factory=dict)
    events_affected: int = 0
    styles_affected: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "timestamp": self.timestamp.isoformat(),
            "parameters": self.parameters,
            "events_affected": self.events_affected,
            "styles_affected": self.styles_affected,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationRecord:
        timestamp_raw = data.get("timestamp")
        timestamp = datetime.now()
        if timestamp_raw:
            try:
                timestamp = datetime.fromisoformat(timestamp_raw)
            except ValueError:
                timestamp = datetime.now()
        return cls(
            operation=data.get("operation", ""),
            timestamp=timestamp,
            parameters=data.get("parameters", {}) or {},
            events_affected=int(data.get("events_affected", 0)),
            styles_affected=int(data.get("styles_affected", 0)),
            summary=data.get("summary", ""),
        )


@dataclass
class OperationResult:
    """Result of applying an operation."""

    success: bool
    operation: str
    events_affected: int = 0
    styles_affected: int = 0
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# =============================================================================
# Main SubtitleData Container
# =============================================================================


@dataclass
class SubtitleData:
    """
    Universal subtitle data container.

    This is the SINGLE source of truth for subtitle processing:
    - Load once from file or OCR
    - Apply all operations (stepping, sync, styles, etc.)
    - Write once at end (single rounding point)

    All timing stored as FLOAT MILLISECONDS.
    """

    # Source information
    source_path: Path | None = None
    source_format: str = "ass"  # 'ass', 'ssa', 'srt', 'vtt', 'ocr'
    encoding: str = "utf-8"
    has_bom: bool = False

    # ASS Script Info (preserved in order)
    script_info: OrderedDict = field(default_factory=OrderedDict)

    # Aegisub sections (preserved in order)
    aegisub_garbage: OrderedDict = field(default_factory=OrderedDict)
    aegisub_extradata: list[str] = field(default_factory=list)  # Raw lines

    # Custom/unknown sections (preserved as raw lines)
    custom_sections: OrderedDict = field(default_factory=OrderedDict)

    # Section ordering (to preserve original order)
    section_order: list[str] = field(default_factory=list)

    # Styles
    styles: OrderedDict = field(default_factory=OrderedDict)  # name -> SubtitleStyle
    styles_format: list[str] = field(default_factory=list)

    # Events
    events: list[SubtitleEvent] = field(default_factory=list)
    events_format: list[str] = field(default_factory=list)

    # Embedded content
    fonts: list[EmbeddedFont] = field(default_factory=list)
    graphics: list[EmbeddedGraphic] = field(default_factory=list)

    # Operation tracking
    operations: list[OperationRecord] = field(default_factory=list)

    # OCR document-level metadata (populated if source is OCR)
    ocr_metadata: OCRMetadata | None = None

    # Comments before sections (for preservation)
    section_comments: dict[str, list[str]] = field(default_factory=dict)

    # Header lines before first section
    header_lines: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Set default format fields if not provided."""
        if not self.styles_format:
            self.styles_format = [
                "Name",
                "Fontname",
                "Fontsize",
                "PrimaryColour",
                "SecondaryColour",
                "OutlineColour",
                "BackColour",
                "Bold",
                "Italic",
                "Underline",
                "StrikeOut",
                "ScaleX",
                "ScaleY",
                "Spacing",
                "Angle",
                "BorderStyle",
                "Outline",
                "Shadow",
                "Alignment",
                "MarginL",
                "MarginR",
                "MarginV",
                "Encoding",
            ]
        if not self.events_format:
            self.events_format = [
                "Layer",
                "Start",
                "End",
                "Style",
                "Name",
                "MarginL",
                "MarginR",
                "MarginV",
                "Effect",
                "Text",
            ]

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_file(cls, path: Path | str) -> SubtitleData:
        """
        Load subtitle from file, auto-detecting format.

        Args:
            path: Path to subtitle file

        Returns:
            SubtitleData instance
        """
        path = Path(path)
        ext = path.suffix.lower()

        if ext in (".ass", ".ssa"):
            from .parsers.ass_parser import parse_ass_file

            return parse_ass_file(path)
        elif ext == ".srt":
            from .parsers.srt_parser import parse_srt_file

            return parse_srt_file(path)
        elif ext == ".vtt":
            from .parsers.srt_parser import parse_vtt_file

            return parse_vtt_file(path)
        else:
            raise ValueError(f"Unsupported subtitle format: {ext}")

    @classmethod
    def from_json(cls, path: Path | str) -> SubtitleData:
        """
        Load SubtitleData from a JSON file produced by save_json().

        Args:
            path: Path to SubtitleData JSON file

        Returns:
            SubtitleData instance
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)

        data = cls(
            source_path=Path(payload["source_path"])
            if payload.get("source_path")
            else None,
            source_format=payload.get("source_format", "ass"),
            encoding=payload.get("encoding", "utf-8"),
        )

        if payload.get("ocr_metadata"):
            data.ocr_metadata = OCRMetadata.from_dict(payload["ocr_metadata"])

        data.script_info = OrderedDict(payload.get("script_info", {}))

        styles_payload = payload.get("styles", {}) or {}
        data.styles = OrderedDict(
            (name, SubtitleStyle.from_dict(style_data))
            for name, style_data in styles_payload.items()
        )

        events_payload = payload.get("events", []) or []
        data.events = [
            SubtitleEvent.from_dict(event_data) for event_data in events_payload
        ]

        operations_payload = payload.get("operations", []) or []
        data.operations = [
            OperationRecord.from_dict(op_data) for op_data in operations_payload
        ]

        return data

    # =========================================================================
    # Save Methods
    # =========================================================================

    def save_ass(self, path: Path | str, rounding: str = "floor") -> None:
        """
        Save as ASS file.

        THIS IS THE SINGLE ROUNDING POINT.
        Float ms → centiseconds happens here.
        """
        from .writers.ass_writer import write_ass_file

        write_ass_file(self, Path(path), rounding=rounding)

    def save_srt(self, path: Path | str, rounding: str = "round") -> None:
        """
        Save as SRT file.

        Float ms → integer ms happens here.
        """
        from .writers.srt_writer import write_srt_file

        write_srt_file(self, Path(path), rounding=rounding)

    def save(self, path: Path | str, rounding: str | None = None) -> None:
        """Save to file, format determined by extension."""
        path = Path(path)
        ext = path.suffix.lower()
        rounding_mode = rounding or "floor"

        if ext in (".ass", ".ssa"):
            self.save_ass(path, rounding=rounding_mode)
        elif ext == ".srt":
            self.save_srt(path, rounding=rounding_mode)
        else:
            raise ValueError(f"Unsupported output format: {ext}")

    def save_json(self, path: Path | str) -> None:
        """
        Save complete JSON representation for debugging and data preservation.

        This JSON contains ALL data including OCR metadata, sync adjustments,
        and per-event tracking that would be lost in ASS/SRT output.
        """
        # Try to import numpy for handling numpy types in JSON
        try:
            import numpy as np

            HAS_NUMPY = True
        except ImportError:
            HAS_NUMPY = False

        class NumpyEncoder(json.JSONEncoder):
            """JSON encoder that handles numpy types."""

            def default(self, obj):
                if HAS_NUMPY:
                    if isinstance(obj, (np.integer,)):
                        return int(obj)
                    elif isinstance(obj, (np.floating,)):
                        return float(obj)
                    elif isinstance(obj, np.ndarray):
                        return obj.tolist()
                return super().default(obj)

        path = Path(path)
        data = {
            "version": "1.0",
            "source_path": str(self.source_path) if self.source_path else None,
            "source_format": self.source_format,
            "encoding": self.encoding,
        }

        # Include OCR metadata if present
        if self.ocr_metadata is not None:
            data["ocr_metadata"] = self.ocr_metadata.to_dict()

        # Script info
        data["script_info"] = dict(self.script_info)

        # Styles
        data["styles"] = {name: style.to_dict() for name, style in self.styles.items()}

        # Events with all metadata
        data["events"] = [e.to_dict() for e in self.events]

        # Operations history
        data["operations"] = [op.to_dict() for op in self.operations]

        # Summary counts
        data["event_count"] = len(self.events)
        data["style_count"] = len(self.styles)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

    # =========================================================================
    # Operation Methods
    # =========================================================================

    def apply_sync(
        self,
        mode: str,
        total_delay_ms: float,
        global_shift_ms: float,
        target_fps: float | None = None,
        source_video: str | None = None,
        target_video: str | None = None,
        runner=None,
        config: dict | None = None,
        **kwargs,
    ) -> OperationResult:
        """
        Apply sync mode to adjust timing.

        This dispatches to the registered sync plugin for the mode.

        Args:
            mode: Sync mode name (e.g., 'timebase-frame-locked-timestamps')
            total_delay_ms: Total delay from correlation/analysis (raw float)
            global_shift_ms: User global shift (raw float)
            target_fps: Target video FPS
            source_video: Source video path
            target_video: Target video path
            runner: CommandRunner for logging
            config: Settings dict
            **kwargs: Additional mode-specific parameters

        Returns:
            OperationResult with success/failure and details
        """
        from .sync_modes import get_sync_plugin

        plugin = get_sync_plugin(mode)
        if plugin is None:
            return OperationResult(
                success=False, operation="sync", error=f"Unknown sync mode: {mode}"
            )

        return plugin.apply(
            subtitle_data=self,
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            target_fps=target_fps,
            source_video=source_video,
            target_video=target_video,
            runner=runner,
            settings=config,  # Pass as 'settings' for sync plugins that expect AppSettings
            config=config or {},  # Keep for backward compatibility
            **kwargs,
        )

    def apply_stepping(
        self, edl_segments: list[Any], boundary_mode: str = "start", runner=None
    ) -> OperationResult:
        """
        Apply stepping (EDL-based timing adjustment).

        Args:
            edl_segments: List of AudioSegment entries
            boundary_mode: How to handle boundary-spanning subs ('start', 'midpoint', 'majority')
            runner: CommandRunner for logging

        Returns:
            OperationResult
        """
        from .operations.stepping import apply_stepping

        return apply_stepping(self, edl_segments, boundary_mode, runner)

    def apply_style_patch(
        self, patches: dict[str, dict[str, Any]], runner=None
    ) -> OperationResult:
        """
        Apply style patches.

        Args:
            patches: Dict of style_name -> {attribute: value}
            runner: CommandRunner for logging

        Returns:
            OperationResult
        """
        from .operations.style_ops import apply_style_patch

        return apply_style_patch(self, patches, runner)

    def apply_font_replacement(
        self, replacements: dict[str, str], runner=None
    ) -> OperationResult:
        """
        Apply font replacements.

        Args:
            replacements: Dict of old_font -> new_font
            runner: CommandRunner for logging

        Returns:
            OperationResult
        """
        from .operations.style_ops import apply_font_replacement

        return apply_font_replacement(self, replacements, runner)

    def apply_size_multiplier(self, multiplier: float, runner=None) -> OperationResult:
        """
        Apply font size multiplier to all styles.

        Args:
            multiplier: Size multiplier (e.g., 1.2 for 20% increase)
            runner: CommandRunner for logging

        Returns:
            OperationResult
        """
        from .operations.style_ops import apply_size_multiplier

        return apply_size_multiplier(self, multiplier, runner)

    def apply_rescale(
        self, target_resolution: tuple[int, int], runner=None
    ) -> OperationResult:
        """
        Rescale subtitle to target resolution.

        Args:
            target_resolution: (width, height) tuple
            runner: CommandRunner for logging

        Returns:
            OperationResult
        """
        from .operations.style_ops import apply_rescale

        return apply_rescale(self, target_resolution, runner)

    def filter_by_styles(
        self,
        styles: list[str],
        mode: str = "exclude",
        forced_include: list[int] | None = None,
        forced_exclude: list[int] | None = None,
        runner=None,
    ) -> OperationResult:
        """
        Filter events by style name.

        Args:
            styles: List of style names to filter
            mode: 'exclude' (remove these styles) or 'include' (keep only these)
            runner: CommandRunner for logging

        Returns:
            OperationResult with filtering statistics including:
            - original_count, filtered_count, removed_count
            - styles_found, styles_missing
        """
        from .operations.style_ops import apply_style_filter

        return apply_style_filter(
            self,
            styles,
            mode,
            forced_include=forced_include,
            forced_exclude=forced_exclude,
            runner=runner,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_dialogue_events(self) -> list[SubtitleEvent]:
        """Get only dialogue events (not comments)."""
        return [e for e in self.events if not e.is_comment]

    def get_events_by_style(self, style_name: str) -> list[SubtitleEvent]:
        """Get events with specific style."""
        return [e for e in self.events if e.style == style_name]

    def get_style_counts(self) -> dict[str, int]:
        """
        Get event count per style name.

        Returns:
            Dictionary mapping style name to event count.
            Example: {'Default': 1243, 'Sign': 47, 'OP': 24}
        """
        counts: dict[str, int] = {}
        for event in self.events:
            if not event.is_comment:
                counts[event.style] = counts.get(event.style, 0) + 1
        return counts

    @staticmethod
    def get_style_counts_from_file(path: str) -> dict[str, int]:
        """
        Get style counts from a file without loading full SubtitleData.

        This is a quick method for validation and UI dialogs that only
        need style enumeration, not full subtitle data.

        Args:
            path: Path to subtitle file

        Returns:
            Dictionary mapping style name to event count.
            Empty dict if file can't be loaded.
        """
        try:
            data = SubtitleData.from_file(path)
            return data.get_style_counts()
        except Exception:
            return {}

    def get_timing_range(self) -> tuple[float, float]:
        """Get (min_start_ms, max_end_ms) of all events."""
        if not self.events:
            return (0.0, 0.0)
        starts = [e.start_ms for e in self.events]
        ends = [e.end_ms for e in self.events]
        return (min(starts), max(ends))

    def validate(self) -> list[str]:
        """
        Validate data integrity.

        Returns:
            List of validation warnings/errors
        """
        warnings = []

        for i, event in enumerate(self.events):
            if event.end_ms <= event.start_ms:
                warnings.append(
                    f"Event {i}: end ({event.end_ms}) <= start ({event.start_ms})"
                )
            if event.start_ms < 0:
                warnings.append(f"Event {i}: negative start time ({event.start_ms})")
            if event.style not in self.styles and event.style != "Default":
                warnings.append(f"Event {i}: references unknown style '{event.style}'")

        return warnings

    def sort_events_by_time(self) -> None:
        """Sort events by start time, preserving layer order for simultaneous events."""
        self.events.sort(key=lambda e: (e.start_ms, e.layer))

    def remove_events(self, indices: list[int]) -> int:
        """
        Remove events at specified indices.

        Args:
            indices: List of event indices to remove

        Returns:
            Number of events removed
        """
        # Sort in reverse to remove from end first (preserves indices)
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self.events):
                del self.events[idx]
        return len(indices)

    def remove_events_by_style(self, style_name: str) -> int:
        """
        Remove all events with specified style.

        Args:
            style_name: Style name to match

        Returns:
            Number of events removed
        """
        original_count = len(self.events)
        self.events = [e for e in self.events if e.style != style_name]
        return original_count - len(self.events)

    def shift_timing(self, offset_ms: float) -> None:
        """
        Shift all event timing by offset.

        Args:
            offset_ms: Milliseconds to add (positive) or subtract (negative)
        """
        for event in self.events:
            event.start_ms = max(0.0, event.start_ms + offset_ms)
            event.end_ms = max(0.0, event.end_ms + offset_ms)

    def remove_overlapping_events(self) -> int:
        """
        Remove events that completely overlap with others (same timing).

        Keeps the first occurrence.

        Returns:
            Number of events removed
        """
        seen = set()
        unique_events = []
        removed = 0

        for event in self.events:
            key = (event.start_ms, event.end_ms, event.text)
            if key not in seen:
                seen.add(key)
                unique_events.append(event)
            else:
                removed += 1

        self.events = unique_events
        return removed


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_ass_time(time_str: str) -> float:
    """
    Parse ASS timestamp to float milliseconds.

    Format: H:MM:SS.cc (centiseconds)

    Args:
        time_str: ASS timestamp string

    Returns:
        Time in float milliseconds
    """
    try:
        parts = time_str.strip().split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_cs = parts[2].split(".")
            seconds = int(seconds_cs[0])
            centiseconds = int(seconds_cs[1]) if len(seconds_cs) > 1 else 0

            total_ms = (
                hours * 3600000
                + minutes * 60000
                + seconds * 1000
                + centiseconds * 10  # centiseconds to ms
            )
            return float(total_ms)
    except (ValueError, IndexError):
        pass
    return 0.0


def _format_ass_time(ms: float) -> str:
    """
    Format float milliseconds to ASS timestamp.

    THIS IS WHERE ROUNDING HAPPENS.

    Args:
        ms: Time in float milliseconds

    Returns:
        ASS timestamp string (H:MM:SS.cc)
    """
    # Round to centiseconds (floor for consistency)
    total_cs = int(math.floor(ms / 10))

    cs = total_cs % 100
    total_seconds = total_cs // 100
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _format_number(value: float) -> str:
    """Format number, removing unnecessary decimals."""
    if value == int(value):
        return str(int(value))
    return str(value)
