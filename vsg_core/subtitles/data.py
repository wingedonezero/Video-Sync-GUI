# vsg_core/subtitles/data.py
"""
Unified subtitle data container for all subtitle operations.

This module provides the central data structure for subtitle processing:
- Load once from file (ASS, SRT) or OCR output
- Apply operations (stepping, sync, style patches, etc.)
- Write once at the end (single rounding point)

All timing is stored as FLOAT MILLISECONDS internally.
Rounding happens ONLY at final save (ASS -> centiseconds, SRT -> milliseconds).

NOTE: Model classes have been moved to vsg_core/models/subtitles/core.py
This file re-exports them for backward compatibility.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Import models from centralized location
from vsg_core.models.subtitles.core import (
    EmbeddedFont,
    EmbeddedGraphic,
    OCREventData,
    OCRMetadata,
    OperationRecord,
    OperationResult,
    SteppingEventData,
    SubtitleEvent,
    SubtitleStyle,
    SyncEventData,
)

if TYPE_CHECKING:
    pass

# Re-export models for backward compatibility
__all__ = [
    "OCREventData",
    "SyncEventData",
    "SteppingEventData",
    "OCRMetadata",
    "SubtitleStyle",
    "SubtitleEvent",
    "EmbeddedFont",
    "EmbeddedGraphic",
    "OperationRecord",
    "OperationResult",
    "SubtitleData",
]


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
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        data = cls(
            source_path=(
                Path(payload["source_path"]) if payload.get("source_path") else None
            ),
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
            config=config or {},
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


# Helper functions are imported from vsg_core.models.subtitles.core:
# _parse_ass_time, _format_ass_time, _format_number
