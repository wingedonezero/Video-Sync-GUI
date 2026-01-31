# vsg_qt/subtitle_editor/tabs/filtering_tab.py
"""
Filtering tab for subtitle editor.

Provides style filtering configuration for generated tracks.
This is used when creating filtered subtitle tracks (e.g., "signs only").
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .base_tab import BaseTab


class FilteringTab(BaseTab):
    """
    Tab for configuring style filtering.

    Used to create generated tracks that include/exclude certain styles.
    """

    TAB_NAME = "Filtering"

    # Signal emitted when filter config changes
    filter_preview_requested = Signal(bool)
    flag_effects_requested = Signal(bool)
    jump_to_next_flagged = Signal()  # Request jump to next flagged line

    def __init__(self, parent=None):
        super().__init__(parent)
        self._style_checkboxes: dict = {}

        self._build_ui()

    def _build_ui(self):
        """Build the filtering tab UI."""
        layout = self.content_layout

        # Description
        desc = QLabel(
            "Configure which styles to include or exclude when generating filtered tracks.\n"
            "Use 'Include' mode for tracks like 'signs only' or 'songs only'.\n"
            "Use 'Exclude' mode to remove specific styles."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Mode selection
        mode_group = QGroupBox("Filter Mode")
        mode_layout = QVBoxLayout(mode_group)

        self._mode_group = QButtonGroup(self)

        self._include_radio = QRadioButton("Include selected styles (keep only these)")
        self._exclude_radio = QRadioButton("Exclude selected styles (remove these)")
        self._exclude_radio.setChecked(True)

        self._mode_group.addButton(self._include_radio, 0)
        self._mode_group.addButton(self._exclude_radio, 1)

        self._include_radio.toggled.connect(self._on_mode_changed)

        mode_layout.addWidget(self._include_radio)
        mode_layout.addWidget(self._exclude_radio)
        layout.addWidget(mode_group)

        # Style selection
        styles_group = QGroupBox("Styles")
        styles_layout = QVBoxLayout(styles_group)

        # Select all/none buttons
        btn_layout = QHBoxLayout()
        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.clicked.connect(self._select_all_styles)
        self._select_none_btn = QPushButton("Select None")
        self._select_none_btn.clicked.connect(self._select_no_styles)
        btn_layout.addWidget(self._select_all_btn)
        btn_layout.addWidget(self._select_none_btn)
        btn_layout.addStretch()
        styles_layout.addLayout(btn_layout)

        # Style list (will be populated when state is set)
        self._styles_list = QWidget()
        self._styles_list_layout = QVBoxLayout(self._styles_list)
        self._styles_list_layout.setContentsMargins(0, 0, 0, 0)
        self._styles_list_layout.setSpacing(4)
        styles_layout.addWidget(self._styles_list)

        layout.addWidget(styles_group)

        # Preview toggle
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(preview_frame)

        self._preview_check = QCheckBox("Preview filter in events table")
        self._preview_check.setToolTip("Dim events that would be filtered out")
        self._preview_check.toggled.connect(self._on_preview_toggled)
        preview_layout.addWidget(self._preview_check)

        # Flag effects row with checkbox, count, and next button
        flag_layout = QHBoxLayout()
        flag_layout.setContentsMargins(0, 0, 0, 0)

        self._flag_effects_check = QCheckBox("Flag excluded lines with effects")
        self._flag_effects_check.setToolTip(
            "Show ⚠️ on excluded lines that have positioning, karaoke, or other effect tags.\n"
            "These may be signs/songs incorrectly styled as dialogue."
        )
        self._flag_effects_check.toggled.connect(self._on_flag_effects_toggled)
        flag_layout.addWidget(self._flag_effects_check)

        self._flagged_count_label = QLabel("")
        self._flagged_count_label.setStyleSheet("color: #ff9900; font-weight: bold;")
        flag_layout.addWidget(self._flagged_count_label)

        self._next_flagged_btn = QPushButton("Next ▶")
        self._next_flagged_btn.setFixedWidth(60)
        self._next_flagged_btn.setToolTip("Jump to next flagged line")
        self._next_flagged_btn.clicked.connect(self._on_next_flagged_clicked)
        self._next_flagged_btn.setEnabled(False)
        flag_layout.addWidget(self._next_flagged_btn)

        flag_layout.addStretch()
        preview_layout.addLayout(flag_layout)

        layout.addWidget(preview_frame)

        # Statistics
        self._stats_label = QLabel("Select styles to see statistics")
        self._stats_label.setStyleSheet("color: gray;")
        layout.addWidget(self._stats_label)

        layout.addStretch()

    def _on_state_set(self):
        """Initialize from state when set."""
        if not self._state:
            return

        self._populate_styles()
        self._state.filter_changed.connect(self._update_stats)

    def _populate_styles(self):
        """Populate the styles list from state."""
        if not self._state:
            return

        # Clear existing checkboxes
        for cb in self._style_checkboxes.values():
            cb.deleteLater()
        self._style_checkboxes.clear()

        # Count lines per style
        style_counts = {}
        for event in self._state.events:
            if not event.is_comment:
                style_counts[event.style] = style_counts.get(event.style, 0) + 1

        # Add checkbox for each style with line count
        for style_name in self._state.style_names:
            count = style_counts.get(style_name, 0)
            cb = QCheckBox(f"{style_name} ({count} lines)")
            cb.setProperty('style_name', style_name)  # Store actual name
            cb.toggled.connect(self._on_style_toggled)
            self._styles_list_layout.addWidget(cb)
            self._style_checkboxes[style_name] = cb

        # Load current filter config from state
        current_styles = self._state.filter_styles
        for name, cb in self._style_checkboxes.items():
            cb.setChecked(name in current_styles)

        # Set mode
        if self._state.filter_mode == 'include':
            self._include_radio.setChecked(True)
        else:
            self._exclude_radio.setChecked(True)

        self._update_stats()

    def _on_mode_changed(self, checked: bool):
        """Handle filter mode change."""
        if not self._state:
            return

        mode = 'include' if self._include_radio.isChecked() else 'exclude'
        self._state.set_filter_mode(mode)
        self._update_stats()

    def _on_style_toggled(self):
        """Handle style checkbox toggle."""
        if not self._state:
            return

        selected = set()
        for name, cb in self._style_checkboxes.items():
            if cb.isChecked():
                selected.add(name)

        self._state.set_filter_styles(selected)
        self._update_stats()

    def _select_all_styles(self):
        """Select all styles."""
        for cb in self._style_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._on_style_toggled()

    def _select_no_styles(self):
        """Deselect all styles."""
        for cb in self._style_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._on_style_toggled()

    def _on_preview_toggled(self, checked: bool):
        """Handle preview checkbox toggle."""
        self.filter_preview_requested.emit(checked)

    def _on_flag_effects_toggled(self, checked: bool):
        """Handle flag effects checkbox toggle."""
        self.flag_effects_requested.emit(checked)
        if not checked:
            self._flagged_count_label.setText("")
            self._next_flagged_btn.setEnabled(False)

    def _on_next_flagged_clicked(self):
        """Handle next flagged button click."""
        self.jump_to_next_flagged.emit()

    def update_flagged_count(self, count: int):
        """Update the flagged count display."""
        if count > 0:
            self._flagged_count_label.setText(f"({count} found)")
            self._next_flagged_btn.setEnabled(True)
        else:
            self._flagged_count_label.setText("")
            self._next_flagged_btn.setEnabled(False)

    def _update_stats(self):
        """Update statistics label."""
        if not self._state:
            return

        total = len(self._state.events)
        kept = len(self._state.get_filtered_event_indices())
        removed = total - kept

        mode = "included" if self._state.filter_mode == 'include' else "kept"
        self._stats_label.setText(
            f"Result: {kept} events {mode}, {removed} events removed (total: {total})"
        )

    def on_activated(self):
        """Called when tab becomes active."""
        self._populate_styles()

    def on_event_selected(self, event_index: int):
        """Handle event selection - highlight the event's style."""
        if not self._state or event_index < 0:
            return

        events = self._state.events
        if event_index >= len(events):
            return

        event = events[event_index]
        style_name = event.style

        # Highlight the style in the list (optional visual feedback)
        for name, cb in self._style_checkboxes.items():
            if name == style_name:
                cb.setStyleSheet("font-weight: bold;")
            else:
                cb.setStyleSheet("")

    def get_result(self) -> dict:
        """Get filter configuration as result."""
        if not self._state:
            return {}

        # Only save the configuration, not derived data
        # kept_indices is calculated at runtime by SubtitleData from filter_mode + filter_styles
        return {
            'filter_mode': self._state.filter_mode,
            'filter_styles': list(self._state.filter_styles),
            'forced_include': list(self._state.forced_include_indices),
            'forced_exclude': list(self._state.forced_exclude_indices)
        }

    def get_filter_config(self) -> dict:
        """Get the current filter configuration."""
        return self.get_result()
