# vsg_qt/subtitle_editor/events_table.py
"""
Events table widget for subtitle editor.

Displays all subtitle events with columns:
- # (row number)
- L (Layer)
- Start (H:MM:SS.cc format)
- End (H:MM:SS.cc format)
- CPS (characters per second)
- Style
- Actor
- Text

Features:
- Click to select event and seek video
- Highlight overlapping events
- Word wrap for text column
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QInputDialog,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Regex patterns for detecting effect/positioning tags that suggest non-dialogue content
# These are override tags typically used for signs, karaoke, and effects
EFFECT_TAG_PATTERNS = [
    r'\\pos\s*\(',       # Positioning
    r'\\move\s*\(',      # Movement animation
    r'\\org\s*\(',       # Transform origin
    r'\\k[fo]?\d',       # Karaoke timing (\k, \kf, \ko)
    r'\\an[1-9]',        # Alignment (non-default positioning)
    r'\\fad\s*\(',       # Fade in/out
    r'\\fade\s*\(',      # Advanced fade
    r'\\t\s*\(',         # Animation/transform
    r'\\clip\s*\(',      # Clipping (often used for signs)
    r'\\iclip\s*\(',     # Inverse clipping
    r'\\p[1-9]',         # Drawing mode (vector graphics)
]
EFFECT_TAG_REGEX = re.compile('|'.join(EFFECT_TAG_PATTERNS), re.IGNORECASE)

from .utils import calculate_cps, cps_color, cps_tooltip, ms_to_ass_time

if TYPE_CHECKING:
    from .state import EditorState


class EventsTable(QWidget):
    """
    Table widget displaying all subtitle events.

    Signals:
        event_selected: Emitted with event index when user clicks a row
        event_double_clicked: Emitted with event index on double-click
    """

    event_selected = Signal(int)
    event_double_clicked = Signal(int)
    preview_updated = Signal()
    flagged_count_changed = Signal(int)  # Emitted when effect flag count changes

    # Column indices
    COL_NUM = 0
    COL_LAYER = 1
    COL_START = 2
    COL_END = 3
    COL_CPS = 4
    COL_STYLE = 5
    COL_ACTOR = 6
    COL_TEXT = 7

    # Highlight colors
    COLOR_SELECTED = QColor(60, 100, 160)      # Blue for selected row
    COLOR_OVERLAP = QColor(80, 80, 50)         # Yellow-ish for overlapping
    COLOR_FILTERED_OUT = QColor(60, 60, 60)    # Dimmed for filtered out

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: EditorState | None = None
        self._highlighted_indices: set[int] = set()
        self._filter_preview_mode: bool = False
        self._flag_effects_mode: bool = False
        self._cached_kept_indices: set[int] | None = None  # Cache to avoid O(N²)
        self._flagged_effect_indices: list[int] = []  # Cached list of flagged row indices

        self._setup_ui()

    def _setup_ui(self):
        """Set up the table UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            '#', 'L', 'Start', 'End', 'CPS', 'Style', 'Actor', 'Text'
        ])

        # Selection behavior
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAutoScroll(False)

        # Column sizing
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self.COL_NUM, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_LAYER, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_START, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_END, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_CPS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_STYLE, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_ACTOR, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_TEXT, QHeaderView.Stretch)

        # Set reasonable default widths
        self._table.setColumnWidth(self.COL_STYLE, 100)
        self._table.setColumnWidth(self.COL_ACTOR, 80)

        # Enable word wrap for text column
        self._table.setWordWrap(True)

        # Connect signals
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self._table)

    def set_state(self, state: EditorState):
        """
        Set the editor state.

        Args:
            state: EditorState instance to bind to
        """
        self._state = state
        self._state.subtitle_data_changed.connect(self.refresh)
        self._state.selection_changed.connect(self._on_state_selection_changed)
        self._state.filter_changed.connect(self._update_filter_highlights)

    def refresh(self):
        """Refresh the table from the current state."""
        if not self._state:
            return

        events = self._state.events
        self._table.setRowCount(len(events))

        for i, event in enumerate(events):
            self._populate_row(i, event)

        # Resize rows to content
        self._table.resizeRowsToContents()

    def _populate_row(self, row: int, event):
        """
        Populate a table row with event data.

        Args:
            row: Row index
            event: SubtitleEvent instance
        """
        # Row number (1-indexed for display)
        # Add ⚠️ warning if this is an excluded line with effect tags
        row_text = str(row + 1)
        if self._flag_effects_mode and self._cached_kept_indices is not None:
            if row not in self._cached_kept_indices and self._has_effect_tags(event.text):
                row_text = f"⚠️ {row + 1}"

        num_item = QTableWidgetItem(row_text)
        num_item.setTextAlignment(Qt.AlignCenter)
        if "⚠️" in row_text:
            num_item.setToolTip(
                "This excluded line has positioning/effect tags.\n"
                "It may be a sign or karaoke incorrectly styled.\n"
                "Right-click to force include if needed."
            )
        self._table.setItem(row, self.COL_NUM, num_item)

        # Layer
        layer_item = QTableWidgetItem(str(event.layer))
        layer_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, self.COL_LAYER, layer_item)

        # Start time (H:MM:SS.cc format)
        start_item = QTableWidgetItem(ms_to_ass_time(event.start_ms))
        start_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, self.COL_START, start_item)

        # End time
        end_item = QTableWidgetItem(ms_to_ass_time(event.end_ms))
        end_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, self.COL_END, end_item)

        # CPS (characters per second)
        duration_ms = event.end_ms - event.start_ms
        cps = calculate_cps(event.text, duration_ms)
        cps_item = QTableWidgetItem(f"{cps:.0f}" if cps > 0 else "-")
        cps_item.setTextAlignment(Qt.AlignCenter)
        cps_item.setToolTip(cps_tooltip(cps) if cps > 0 else "")

        # Color the CPS cell based on reading speed
        r, g, b = cps_color(cps)
        cps_item.setBackground(QBrush(QColor(r, g, b)))
        self._table.setItem(row, self.COL_CPS, cps_item)

        # Style
        style_item = QTableWidgetItem(event.style)
        self._table.setItem(row, self.COL_STYLE, style_item)

        # Actor
        actor_item = QTableWidgetItem(event.name or "")
        self._table.setItem(row, self.COL_ACTOR, actor_item)

        # Text (with * prefix if contains override tags)
        text = event.text
        has_tags = '{' in text and '}' in text
        display_text = f"* {text}" if has_tags else text
        text_item = QTableWidgetItem(display_text)
        self._table.setItem(row, self.COL_TEXT, text_item)

        # Mark commented lines
        if event.is_comment:
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item:
                    item.setForeground(QBrush(QColor(128, 128, 128)))

    def _on_selection_changed(self):
        """Handle table selection change."""
        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()

        # Update highlighted overlapping events
        self._update_overlap_highlights(row)

        # Emit signal
        self.event_selected.emit(row)

    def _on_double_click(self, item: QTableWidgetItem):
        """Handle double-click on a row."""
        if item:
            self.event_double_clicked.emit(item.row())

    def _show_context_menu(self, pos):
        """Show context menu for row actions."""
        if not self._state:
            return

        row = self._table.indexAt(pos).row()
        if row < 0:
            return

        self._table.selectRow(row)

        menu = QMenu(self)
        force_include = menu.addAction("Force include (keep)")
        force_exclude = menu.addAction("Force exclude (remove)")
        clear_override = menu.addAction("Clear filter override")
        menu.addSeparator()
        change_style = menu.addAction("Change style...")

        action = menu.exec_(self._table.mapToGlobal(pos))
        if action == force_include:
            self._state.force_include_event(row)
            self._update_filter_highlights()
        elif action == force_exclude:
            self._state.force_exclude_event(row)
            self._update_filter_highlights()
        elif action == clear_override:
            self._state.clear_forced_event(row)
            self._update_filter_highlights()
        elif action == change_style:
            self._change_event_style(row)

    def _change_event_style(self, row: int):
        """Prompt for a style change for the selected event."""
        if not self._state:
            return

        events = self._state.events
        if row < 0 or row >= len(events):
            return

        style_names = self._state.style_names
        if not style_names:
            return

        current_style = events[row].style
        current_index = style_names.index(current_style) if current_style in style_names else 0
        new_style, ok = QInputDialog.getItem(
            self,
            "Change Style",
            "Select a new style:",
            style_names,
            current_index,
            False
        )
        if ok and new_style:
            self._state.update_event_style(row, new_style)
            self._state.save_preview()
            self._state.subtitle_data_changed.emit()
            self.preview_updated.emit()

    def _update_overlap_highlights(self, selected_row: int):
        """
        Highlight events that overlap with the selected event.

        Args:
            selected_row: Index of the selected event
        """
        # Clear previous highlights
        self._clear_highlights()

        if not self._state:
            return

        # Get overlapping events
        overlapping = self._state.get_overlapping_events(selected_row)
        self._highlighted_indices = set(overlapping)

        # Apply highlight color to overlapping rows
        for row in overlapping:
            self._set_row_background(row, self.COLOR_OVERLAP)

    def _update_filter_highlights(self):
        """Update highlights based on filter preview."""
        if not self._filter_preview_mode or not self._state:
            return

        # Get events that would be kept
        kept_indices = self._state.get_filtered_event_indices()

        # Dim events that would be filtered out
        for row in range(self._table.rowCount()):
            if row not in kept_indices:
                self._set_row_background(row, self.COLOR_FILTERED_OUT)
            else:
                self._clear_row_background(row)

        for row in self._highlighted_indices:
            self._set_row_background(row, self.COLOR_OVERLAP)

    def set_filter_preview_mode(self, enabled: bool):
        """
        Enable/disable filter preview mode.

        When enabled, events that would be filtered out are dimmed.

        Args:
            enabled: Whether to enable filter preview
        """
        self._filter_preview_mode = enabled
        if enabled:
            self._update_filter_highlights()
        else:
            self._clear_highlights()

    def set_flag_effects_mode(self, enabled: bool):
        """
        Enable/disable effect flagging mode.

        When enabled, excluded lines with effect/positioning tags
        show a ⚠️ warning in the row number column.

        Args:
            enabled: Whether to enable effect flagging
        """
        self._flag_effects_mode = enabled
        self._update_effect_flags()

    def _update_effect_flags(self):
        """Update effect warning flags on row numbers (fast, no refresh)."""
        if not self._state:
            self._flagged_effect_indices = []
            self.flagged_count_changed.emit(0)
            return

        events = self._state.events
        kept_indices = self._state.get_filtered_event_indices() if self._flag_effects_mode else set()

        # Build list of flagged indices
        new_flagged = []

        for row in range(self._table.rowCount()):
            if row >= len(events):
                break

            num_item = self._table.item(row, self.COL_NUM)
            if not num_item:
                continue

            # Determine if this row should have a warning
            is_flagged = (self._flag_effects_mode and
                          row not in kept_indices and
                          self._has_effect_tags(events[row].text))

            if is_flagged:
                new_flagged.append(row)
                row_text = f"⚠️ {row + 1}"
                tooltip = (
                    "This excluded line has positioning/effect tags.\n"
                    "It may be a sign or karaoke incorrectly styled.\n"
                    "Right-click to force include if needed."
                )
            else:
                row_text = str(row + 1)
                tooltip = ""

            # Only update if changed
            if num_item.text() != row_text:
                num_item.setText(row_text)
                num_item.setToolTip(tooltip)

        # Update cached list and emit if changed
        if new_flagged != self._flagged_effect_indices:
            self._flagged_effect_indices = new_flagged
            self.flagged_count_changed.emit(len(new_flagged))

    def _has_effect_tags(self, text: str) -> bool:
        """
        Check if text contains effect/positioning override tags.

        These tags suggest the line is a sign, karaoke, or effect
        rather than normal dialogue.

        Args:
            text: The event text to check

        Returns:
            True if effect tags are found
        """
        return bool(EFFECT_TAG_REGEX.search(text))

    def _set_row_background(self, row: int, color: QColor):
        """Set background color for all cells in a row."""
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                item.setBackground(QBrush(color))

    def _clear_row_background(self, row: int):
        """Clear background color for all cells in a row."""
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                item.setBackground(QBrush())

    def _clear_highlights(self):
        """Clear all row highlights."""
        if self._filter_preview_mode and self._state:
            kept_indices = self._state.get_filtered_event_indices()
            for row in self._highlighted_indices:
                if row not in kept_indices:
                    self._set_row_background(row, self.COLOR_FILTERED_OUT)
                else:
                    self._clear_row_background(row)
        else:
            for row in self._highlighted_indices:
                # Don't clear CPS column (it has its own coloring)
                for col in range(self._table.columnCount()):
                    if col == self.COL_CPS:
                        continue
                    item = self._table.item(row, col)
                    if item:
                        item.setBackground(QBrush())

        self._highlighted_indices.clear()

    def select_row(self, row: int):
        """
        Select a specific row.

        Args:
            row: Row index to select
        """
        if 0 <= row < self._table.rowCount():
            self._table.selectRow(row)
            self._table.scrollToItem(self._table.item(row, 0))

    def _on_state_selection_changed(self, indices: list[int]):
        """Handle selection change from state."""
        if indices and len(indices) == 1:
            self.select_row(indices[0])

    def get_selected_row(self) -> int:
        """Get the currently selected row index, or -1 if none."""
        selected_rows = self._table.selectionModel().selectedRows()
        if selected_rows:
            return selected_rows[0].row()
        return -1

    def get_selected_rows(self) -> list[int]:
        """Get all selected row indices."""
        return [idx.row() for idx in self._table.selectionModel().selectedRows()]

    def jump_to_next_flagged(self) -> bool:
        """
        Jump to the next flagged effect row, looping if needed.

        Returns:
            True if jumped to a row, False if no flagged rows
        """
        if not self._flagged_effect_indices:
            return False

        current_row = self.get_selected_row()

        # Find next flagged row after current
        for row in self._flagged_effect_indices:
            if row > current_row:
                self.select_row(row)
                return True

        # Loop to first flagged row
        self.select_row(self._flagged_effect_indices[0])
        return True

    def get_flagged_count(self) -> int:
        """Get the current count of flagged effect lines."""
        return len(self._flagged_effect_indices)
