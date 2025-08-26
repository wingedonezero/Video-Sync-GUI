# vsg_qt/track_widget.py

# -*- coding: utf-8 -*-
"""
Custom widget for displaying and configuring a single track in the
Manual Selection dialog's 'Final Output' list.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QCheckBox
from PySide6.QtCore import Qt

class TrackWidget(QWidget):
    """A widget for an item in the 'Final Output' list."""

    def __init__(self, track_data: dict, parent=None):
        super().__init__(parent)
        self.track_data = track_data
        self.track_type = track_data.get('type', 'unknown')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        # Track Label (e.g., "[A-1] AC3 (eng)")
        name_part = f" '{track_data['name']}'" if track_data['name'] else ""
        item_text = (f"[{self.track_type[0].upper()}-{track_data['id']}] "
                     f"{track_data['codec_id']} ({track_data['lang']}){name_part}")
        label = QLabel(item_text)
        label.setToolTip(f"Source: {track_data.get('source', 'N/A')}")
        layout.addWidget(label, 1) # Give it stretch factor

        # --- Checkboxes ---
        self.cb_default = QCheckBox("Default")
        self.cb_forced = QCheckBox("Forced")
        self.cb_name = QCheckBox("Keep Name")
        # --- THIS LINE IS CHANGED ---
        self.cb_name.setChecked(False) # Default to NOT keeping the name

        if self.track_type == 'audio':
            layout.addWidget(self.cb_default)
        elif self.track_type == 'subtitles':
            layout.addWidget(self.cb_default)
            layout.addWidget(self.cb_forced)

        layout.addWidget(self.cb_name)

    def get_config(self) -> dict:
        """Returns the configuration based on the checkbox states."""
        return {
            'is_default': self.cb_default.isChecked(),
            'is_forced_display': self.cb_forced.isChecked(),
            'apply_track_name': self.cb_name.isChecked()
        }
