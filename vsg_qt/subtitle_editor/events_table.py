# vsg_qt/subtitle_editor/events_table.py
# -*- coding: utf-8 -*-
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

from typing import TYPE_CHECKING, Optional, List, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QWidget, QVBoxLayout
)

from .utils import ms_to_ass_time, calculate_cps, cps_color, cps_tooltip

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
        self._state: Optional['EditorState'] = None
        self._highlighted_indices: Set[int] = set()
        self._filter_preview_mode: bool = False

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

        layout.addWidget(self._table)

    def set_state(self, state: 'EditorState'):
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
        num_item = QTableWidgetItem(str(row + 1))
        num_item.setTextAlignment(Qt.AlignCenter)
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

    def _on_state_selection_changed(self, indices: List[int]):
        """Handle selection change from state."""
        if indices and len(indices) == 1:
            self.select_row(indices[0])

    def get_selected_row(self) -> int:
        """Get the currently selected row index, or -1 if none."""
        selected_rows = self._table.selectionModel().selectedRows()
        if selected_rows:
            return selected_rows[0].row()
        return -1

    def get_selected_rows(self) -> List[int]:
        """Get all selected row indices."""
        return [idx.row() for idx in self._table.selectionModel().selectedRows()]
