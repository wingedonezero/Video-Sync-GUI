# vsg_core/subtitles/edit_plan.py
"""
Non-destructive subtitle edit plan system.

The editor creates an EditPlan describing changes to make.
The plan is saved to JSON and applied at job execution time.

This allows:
- Preview in editor without modifying original data
- Same workflow for ASS, SRT, and OCR sources
- Video sync (click line → seek) works via start_ms/end_ms
- Future PyonFX integration for effects
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .data import SubtitleData


class EventGroup(str, Enum):
    """Predefined event groups for subtitle organization."""

    DIALOGUE = "dialogue"  # Main dialogue
    OP = "op"  # Opening song
    ED = "ed"  # Ending song
    INSERT = "insert"  # Insert songs
    SIGNS = "signs"  # Signs/typesetting
    TITLES = "titles"  # Episode titles
    PREVIEW = "preview"  # Next episode preview
    CUSTOM = "custom"  # User-defined group


@dataclass
class EventEdit:
    """
    Planned edit for a single subtitle event.

    Identifies event by original_index (stable across session).
    Only non-None fields are applied.
    """

    # Event identification (by original index in loaded data)
    event_index: int

    # Text changes
    new_text: str | None = None

    # Style assignment
    new_style: str | None = None

    # Group assignment (for sync behavior, visual grouping)
    group: str | None = None

    # Manual timing adjustments (added to existing timing)
    start_offset_ms: float | None = None
    end_offset_ms: float | None = None

    # Absolute timing override (replaces existing timing)
    new_start_ms: float | None = None
    new_end_ms: float | None = None

    # Layer change
    new_layer: int | None = None

    # Actor/name field
    new_name: str | None = None

    # Effect field
    new_effect: str | None = None

    # Comment toggle
    set_comment: bool | None = None

    def has_changes(self) -> bool:
        """Check if this edit has any actual changes."""
        return any(
            [
                self.new_text is not None,
                self.new_style is not None,
                self.group is not None,
                self.start_offset_ms is not None,
                self.end_offset_ms is not None,
                self.new_start_ms is not None,
                self.new_end_ms is not None,
                self.new_layer is not None,
                self.new_name is not None,
                self.new_effect is not None,
                self.set_comment is not None,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"event_index": self.event_index}
        if self.new_text is not None:
            result["new_text"] = self.new_text
        if self.new_style is not None:
            result["new_style"] = self.new_style
        if self.group is not None:
            result["group"] = self.group
        if self.start_offset_ms is not None:
            result["start_offset_ms"] = self.start_offset_ms
        if self.end_offset_ms is not None:
            result["end_offset_ms"] = self.end_offset_ms
        if self.new_start_ms is not None:
            result["new_start_ms"] = self.new_start_ms
        if self.new_end_ms is not None:
            result["new_end_ms"] = self.new_end_ms
        if self.new_layer is not None:
            result["new_layer"] = self.new_layer
        if self.new_name is not None:
            result["new_name"] = self.new_name
        if self.new_effect is not None:
            result["new_effect"] = self.new_effect
        if self.set_comment is not None:
            result["set_comment"] = self.set_comment
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEdit:
        """Create from dictionary."""
        return cls(
            event_index=data["event_index"],
            new_text=data.get("new_text"),
            new_style=data.get("new_style"),
            group=data.get("group"),
            start_offset_ms=data.get("start_offset_ms"),
            end_offset_ms=data.get("end_offset_ms"),
            new_start_ms=data.get("new_start_ms"),
            new_end_ms=data.get("new_end_ms"),
            new_layer=data.get("new_layer"),
            new_name=data.get("new_name"),
            new_effect=data.get("new_effect"),
            set_comment=data.get("set_comment"),
        )


@dataclass
class StyleEdit:
    """
    Planned edit for a subtitle style.

    Only non-None fields are applied.
    """

    style_name: str

    # Font changes
    new_fontname: str | None = None
    new_fontsize: float | None = None

    # Color changes (ASS format: &HAABBGGRR)
    new_primary_color: str | None = None
    new_secondary_color: str | None = None
    new_outline_color: str | None = None
    new_back_color: str | None = None

    # Text decoration
    new_bold: int | None = None
    new_italic: int | None = None
    new_underline: int | None = None

    # Scaling
    new_scale_x: float | None = None
    new_scale_y: float | None = None

    # Spacing and angle
    new_spacing: float | None = None
    new_angle: float | None = None

    # Border
    new_border_style: int | None = None
    new_outline: float | None = None
    new_shadow: float | None = None

    # Alignment and margins
    new_alignment: int | None = None
    new_margin_l: int | None = None
    new_margin_r: int | None = None
    new_margin_v: int | None = None

    def has_changes(self) -> bool:
        """Check if this edit has any actual changes."""
        return any(
            [
                self.new_fontname is not None,
                self.new_fontsize is not None,
                self.new_primary_color is not None,
                self.new_secondary_color is not None,
                self.new_outline_color is not None,
                self.new_back_color is not None,
                self.new_bold is not None,
                self.new_italic is not None,
                self.new_underline is not None,
                self.new_scale_x is not None,
                self.new_scale_y is not None,
                self.new_spacing is not None,
                self.new_angle is not None,
                self.new_border_style is not None,
                self.new_outline is not None,
                self.new_shadow is not None,
                self.new_alignment is not None,
                self.new_margin_l is not None,
                self.new_margin_r is not None,
                self.new_margin_v is not None,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"style_name": self.style_name}
        for attr in [
            "new_fontname",
            "new_fontsize",
            "new_primary_color",
            "new_secondary_color",
            "new_outline_color",
            "new_back_color",
            "new_bold",
            "new_italic",
            "new_underline",
            "new_scale_x",
            "new_scale_y",
            "new_spacing",
            "new_angle",
            "new_border_style",
            "new_outline",
            "new_shadow",
            "new_alignment",
            "new_margin_l",
            "new_margin_r",
            "new_margin_v",
        ]:
            value = getattr(self, attr)
            if value is not None:
                result[attr] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StyleEdit:
        """Create from dictionary."""
        return cls(
            style_name=data["style_name"],
            new_fontname=data.get("new_fontname"),
            new_fontsize=data.get("new_fontsize"),
            new_primary_color=data.get("new_primary_color"),
            new_secondary_color=data.get("new_secondary_color"),
            new_outline_color=data.get("new_outline_color"),
            new_back_color=data.get("new_back_color"),
            new_bold=data.get("new_bold"),
            new_italic=data.get("new_italic"),
            new_underline=data.get("new_underline"),
            new_scale_x=data.get("new_scale_x"),
            new_scale_y=data.get("new_scale_y"),
            new_spacing=data.get("new_spacing"),
            new_angle=data.get("new_angle"),
            new_border_style=data.get("new_border_style"),
            new_outline=data.get("new_outline"),
            new_shadow=data.get("new_shadow"),
            new_alignment=data.get("new_alignment"),
            new_margin_l=data.get("new_margin_l"),
            new_margin_r=data.get("new_margin_r"),
            new_margin_v=data.get("new_margin_v"),
        )


@dataclass
class NewEventSpec:
    """Specification for a new event to be added."""

    start_ms: float
    end_ms: float
    text: str
    style: str = "Default"
    layer: int = 0
    name: str = ""
    effect: str = ""
    is_comment: bool = False
    group: str | None = None

    # Insert position (index in final event list, or None for append)
    insert_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "style": self.style,
            "layer": self.layer,
            "name": self.name,
            "effect": self.effect,
            "is_comment": self.is_comment,
            "group": self.group,
            "insert_at": self.insert_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NewEventSpec:
        """Create from dictionary."""
        return cls(
            start_ms=data["start_ms"],
            end_ms=data["end_ms"],
            text=data["text"],
            style=data.get("style", "Default"),
            layer=data.get("layer", 0),
            name=data.get("name", ""),
            effect=data.get("effect", ""),
            is_comment=data.get("is_comment", False),
            group=data.get("group"),
            insert_at=data.get("insert_at"),
        )


@dataclass
class NewStyleSpec:
    """Specification for a new style to be added."""

    name: str
    fontname: str = "Arial"
    fontsize: float = 48.0
    primary_color: str = "&H00FFFFFF"
    secondary_color: str = "&H000000FF"
    outline_color: str = "&H00000000"
    back_color: str = "&H00000000"
    bold: int = 0
    italic: int = 0
    underline: int = 0
    scale_x: float = 100.0
    scale_y: float = 100.0
    spacing: float = 0.0
    angle: float = 0.0
    border_style: int = 1
    outline: float = 2.0
    shadow: float = 2.0
    alignment: int = 2
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 10
    encoding: int = 1

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
    def from_dict(cls, data: dict[str, Any]) -> NewStyleSpec:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class GroupDefinition:
    """
    Definition of a custom event group.

    Groups can have associated styles and sync behavior.
    """

    name: str
    display_name: str = ""
    color: str = "#808080"  # UI display color
    style: str | None = None  # Default style for this group
    skip_sync: bool = False  # Whether to skip sync for this group
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "color": self.color,
            "style": self.style,
            "skip_sync": self.skip_sync,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupDefinition:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            color=data.get("color", "#808080"),
            style=data.get("style"),
            skip_sync=data.get("skip_sync", False),
            description=data.get("description", ""),
        )


@dataclass
class SubtitleEditPlan:
    """
    Non-destructive edit plan for subtitle modifications.

    Created by editor, saved to JSON, applied at job execution.

    Pipeline order:
    1. Editor creates EditPlan (user defines changes)
    2. EditPlan saved to temp JSON
    3. Job execution:
       a. Load SubtitleData from source
       b. Apply EditPlan (this class)
       c. Sync/stepping (timing analysis)
       d. Output final file
    """

    # Source identification
    source_path: str = ""
    source_format: str = ""  # 'ass', 'srt', 'ocr'

    # Event modifications (by original_index)
    event_edits: list[EventEdit] = field(default_factory=list)

    # Events to delete (by original_index)
    deleted_events: set[int] = field(default_factory=set)

    # New events to add
    new_events: list[NewEventSpec] = field(default_factory=list)

    # Style modifications
    style_edits: list[StyleEdit] = field(default_factory=list)

    # Styles to delete
    deleted_styles: set[str] = field(default_factory=set)

    # New styles to add
    new_styles: list[NewStyleSpec] = field(default_factory=list)

    # Group definitions (custom groups)
    group_definitions: list[GroupDefinition] = field(default_factory=list)

    # Global timing offset (applied to all events)
    global_timing_offset_ms: float = 0.0

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1

    # Notes/description
    notes: str = ""

    def has_changes(self) -> bool:
        """Check if this plan has any actual changes."""
        return any(
            [
                any(e.has_changes() for e in self.event_edits),
                self.deleted_events,
                self.new_events,
                any(s.has_changes() for s in self.style_edits),
                self.deleted_styles,
                self.new_styles,
                self.group_definitions,
                self.global_timing_offset_ms != 0.0,
            ]
        )

    def get_event_edit(self, event_index: int) -> EventEdit | None:
        """Get the edit for a specific event, or None if no edit exists."""
        for edit in self.event_edits:
            if edit.event_index == event_index:
                return edit
        return None

    def set_event_edit(self, edit: EventEdit) -> None:
        """Add or update an event edit."""
        # Remove existing edit for this event
        self.event_edits = [
            e for e in self.event_edits if e.event_index != edit.event_index
        ]
        if edit.has_changes():
            self.event_edits.append(edit)
        self.modified_at = datetime.now().isoformat()

    def mark_event_deleted(self, event_index: int) -> None:
        """Mark an event for deletion."""
        self.deleted_events.add(event_index)
        # Remove any edits for this event
        self.event_edits = [e for e in self.event_edits if e.event_index != event_index]
        self.modified_at = datetime.now().isoformat()

    def unmark_event_deleted(self, event_index: int) -> None:
        """Unmark an event for deletion."""
        self.deleted_events.discard(event_index)
        self.modified_at = datetime.now().isoformat()

    def get_style_edit(self, style_name: str) -> StyleEdit | None:
        """Get the edit for a specific style, or None if no edit exists."""
        for edit in self.style_edits:
            if edit.style_name == style_name:
                return edit
        return None

    def set_style_edit(self, edit: StyleEdit) -> None:
        """Add or update a style edit."""
        self.style_edits = [
            s for s in self.style_edits if s.style_name != edit.style_name
        ]
        if edit.has_changes():
            self.style_edits.append(edit)
        self.modified_at = datetime.now().isoformat()

    def add_new_event(self, spec: NewEventSpec) -> None:
        """Add a new event specification."""
        self.new_events.append(spec)
        self.modified_at = datetime.now().isoformat()

    def add_new_style(self, spec: NewStyleSpec) -> None:
        """Add a new style specification."""
        # Remove if already exists
        self.new_styles = [s for s in self.new_styles if s.name != spec.name]
        self.new_styles.append(spec)
        self.modified_at = datetime.now().isoformat()

    def get_group(self, group_name: str) -> GroupDefinition | None:
        """Get a group definition by name."""
        for group in self.group_definitions:
            if group.name == group_name:
                return group
        return None

    def add_group(self, group: GroupDefinition) -> None:
        """Add or update a group definition."""
        self.group_definitions = [
            g for g in self.group_definitions if g.name != group.name
        ]
        self.group_definitions.append(group)
        self.modified_at = datetime.now().isoformat()

    def get_events_in_group(self, group_name: str) -> list[int]:
        """Get indices of events assigned to a group."""
        return [
            edit.event_index for edit in self.event_edits if edit.group == group_name
        ]

    def assign_events_to_group(self, event_indices: list[int], group_name: str) -> None:
        """Assign multiple events to a group."""
        for idx in event_indices:
            edit = self.get_event_edit(idx)
            if edit is None:
                edit = EventEdit(event_index=idx)
            edit.group = group_name
            self.set_event_edit(edit)

    def apply(self, data: SubtitleData, runner=None) -> ApplyResult:
        """
        Apply this edit plan to SubtitleData.

        Args:
            data: SubtitleData to modify (IN PLACE)
            runner: Optional runner for logging

        Returns:
            ApplyResult with statistics
        """
        from .data import SubtitleEvent, SubtitleStyle

        result = ApplyResult()

        def log(msg: str):
            if runner:
                runner._log_message(f"[EditPlan] {msg}")

        # 1. Delete events first (before modifying indices)
        if self.deleted_events:
            # Build list of events to keep
            keep_events = []
            for i, event in enumerate(data.events):
                idx = event.original_index if event.original_index is not None else i
                if idx not in self.deleted_events:
                    keep_events.append(event)
                else:
                    result.events_deleted += 1

            data.events = keep_events
            log(f"Deleted {result.events_deleted} events")

        # 2. Delete styles
        for style_name in self.deleted_styles:
            if style_name in data.styles:
                del data.styles[style_name]
                result.styles_deleted += 1

        if result.styles_deleted:
            log(f"Deleted {result.styles_deleted} styles")

        # 3. Add new styles
        for spec in self.new_styles:
            style = SubtitleStyle(
                name=spec.name,
                fontname=spec.fontname,
                fontsize=spec.fontsize,
                primary_color=spec.primary_color,
                secondary_color=spec.secondary_color,
                outline_color=spec.outline_color,
                back_color=spec.back_color,
                bold=spec.bold,
                italic=spec.italic,
                underline=spec.underline,
                scale_x=spec.scale_x,
                scale_y=spec.scale_y,
                spacing=spec.spacing,
                angle=spec.angle,
                border_style=spec.border_style,
                outline=spec.outline,
                shadow=spec.shadow,
                alignment=spec.alignment,
                margin_l=spec.margin_l,
                margin_r=spec.margin_r,
                margin_v=spec.margin_v,
                encoding=spec.encoding,
            )
            data.styles[spec.name] = style
            result.styles_added += 1

        if result.styles_added:
            log(f"Added {result.styles_added} new styles")

        # 4. Apply style edits
        for edit in self.style_edits:
            if edit.style_name in data.styles:
                style = data.styles[edit.style_name]
                if edit.new_fontname is not None:
                    style.fontname = edit.new_fontname
                if edit.new_fontsize is not None:
                    style.fontsize = edit.new_fontsize
                if edit.new_primary_color is not None:
                    style.primary_color = edit.new_primary_color
                if edit.new_secondary_color is not None:
                    style.secondary_color = edit.new_secondary_color
                if edit.new_outline_color is not None:
                    style.outline_color = edit.new_outline_color
                if edit.new_back_color is not None:
                    style.back_color = edit.new_back_color
                if edit.new_bold is not None:
                    style.bold = edit.new_bold
                if edit.new_italic is not None:
                    style.italic = edit.new_italic
                if edit.new_underline is not None:
                    style.underline = edit.new_underline
                if edit.new_scale_x is not None:
                    style.scale_x = edit.new_scale_x
                if edit.new_scale_y is not None:
                    style.scale_y = edit.new_scale_y
                if edit.new_spacing is not None:
                    style.spacing = edit.new_spacing
                if edit.new_angle is not None:
                    style.angle = edit.new_angle
                if edit.new_border_style is not None:
                    style.border_style = edit.new_border_style
                if edit.new_outline is not None:
                    style.outline = edit.new_outline
                if edit.new_shadow is not None:
                    style.shadow = edit.new_shadow
                if edit.new_alignment is not None:
                    style.alignment = edit.new_alignment
                if edit.new_margin_l is not None:
                    style.margin_l = edit.new_margin_l
                if edit.new_margin_r is not None:
                    style.margin_r = edit.new_margin_r
                if edit.new_margin_v is not None:
                    style.margin_v = edit.new_margin_v
                result.styles_modified += 1

        if result.styles_modified:
            log(f"Modified {result.styles_modified} styles")

        # 5. Apply event edits
        # Build index map for remaining events
        index_to_event = {}
        for i, event in enumerate(data.events):
            idx = event.original_index if event.original_index is not None else i
            index_to_event[idx] = event

        for edit in self.event_edits:
            event = index_to_event.get(edit.event_index)
            if event is None:
                continue

            if edit.new_text is not None:
                event.text = edit.new_text
            if edit.new_style is not None:
                event.style = edit.new_style
            if edit.new_layer is not None:
                event.layer = edit.new_layer
            if edit.new_name is not None:
                event.name = edit.new_name
            if edit.new_effect is not None:
                event.effect = edit.new_effect
            if edit.set_comment is not None:
                event.is_comment = edit.set_comment

            # Timing adjustments (offsets add to existing)
            if edit.start_offset_ms is not None:
                event.start_ms = max(0.0, event.start_ms + edit.start_offset_ms)
            if edit.end_offset_ms is not None:
                event.end_ms = max(0.0, event.end_ms + edit.end_offset_ms)

            # Absolute timing (replaces existing)
            if edit.new_start_ms is not None:
                event.start_ms = edit.new_start_ms
            if edit.new_end_ms is not None:
                event.end_ms = edit.new_end_ms

            result.events_modified += 1

        if result.events_modified:
            log(f"Modified {result.events_modified} events")

        # 6. Add new events
        for spec in self.new_events:
            event = SubtitleEvent(
                start_ms=spec.start_ms,
                end_ms=spec.end_ms,
                text=spec.text,
                style=spec.style,
                layer=spec.layer,
                name=spec.name,
                effect=spec.effect,
                is_comment=spec.is_comment,
            )

            if spec.insert_at is not None and 0 <= spec.insert_at <= len(data.events):
                data.events.insert(spec.insert_at, event)
            else:
                data.events.append(event)

            result.events_added += 1

        if result.events_added:
            log(f"Added {result.events_added} new events")

        # 7. Apply global timing offset
        if self.global_timing_offset_ms != 0.0:
            for event in data.events:
                event.start_ms = max(0.0, event.start_ms + self.global_timing_offset_ms)
                event.end_ms = max(0.0, event.end_ms + self.global_timing_offset_ms)
            log(f"Applied global timing offset: {self.global_timing_offset_ms}ms")
            result.global_offset_applied = True

        result.success = True
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "source_path": self.source_path,
            "source_format": self.source_format,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "notes": self.notes,
            "global_timing_offset_ms": self.global_timing_offset_ms,
            "event_edits": [e.to_dict() for e in self.event_edits],
            "deleted_events": list(self.deleted_events),
            "new_events": [e.to_dict() for e in self.new_events],
            "style_edits": [s.to_dict() for s in self.style_edits],
            "deleted_styles": list(self.deleted_styles),
            "new_styles": [s.to_dict() for s in self.new_styles],
            "group_definitions": [g.to_dict() for g in self.group_definitions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubtitleEditPlan:
        """Create from dictionary."""
        return cls(
            version=data.get("version", 1),
            source_path=data.get("source_path", ""),
            source_format=data.get("source_format", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            modified_at=data.get("modified_at", datetime.now().isoformat()),
            notes=data.get("notes", ""),
            global_timing_offset_ms=data.get("global_timing_offset_ms", 0.0),
            event_edits=[EventEdit.from_dict(e) for e in data.get("event_edits", [])],
            deleted_events=set(data.get("deleted_events", [])),
            new_events=[NewEventSpec.from_dict(e) for e in data.get("new_events", [])],
            style_edits=[StyleEdit.from_dict(s) for s in data.get("style_edits", [])],
            deleted_styles=set(data.get("deleted_styles", [])),
            new_styles=[NewStyleSpec.from_dict(s) for s in data.get("new_styles", [])],
            group_definitions=[
                GroupDefinition.from_dict(g) for g in data.get("group_definitions", [])
            ],
        )

    def save(self, path: Path | str) -> None:
        """Save edit plan to JSON file."""
        path = Path(path)
        self.modified_at = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path | str) -> SubtitleEditPlan:
        """Load edit plan from JSON file."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


@dataclass
class ApplyResult:
    """Result of applying an edit plan."""

    success: bool = False
    events_deleted: int = 0
    events_modified: int = 0
    events_added: int = 0
    styles_deleted: int = 0
    styles_modified: int = 0
    styles_added: int = 0
    global_offset_applied: bool = False
    error: str | None = None

    @property
    def total_changes(self) -> int:
        """Total number of changes made."""
        return (
            self.events_deleted
            + self.events_modified
            + self.events_added
            + self.styles_deleted
            + self.styles_modified
            + self.styles_added
            + (1 if self.global_offset_applied else 0)
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "events_deleted": self.events_deleted,
            "events_modified": self.events_modified,
            "events_added": self.events_added,
            "styles_deleted": self.styles_deleted,
            "styles_modified": self.styles_modified,
            "styles_added": self.styles_added,
            "global_offset_applied": self.global_offset_applied,
            "total_changes": self.total_changes,
            "error": self.error,
        }
