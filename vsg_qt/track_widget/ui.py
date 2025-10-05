# vsg_qt/track_widget/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QDoubleSpinBox, QComboBox
)
from PySide6.QtCore import Qt

from .logic import TrackWidgetLogic
from vsg_qt.track_settings_dialog import TrackSettingsDialog

class TrackWidget(QWidget):
    """A self-contained widget for a single track in the final layout."""
    def __init__(self, track_data: Dict, available_sources: List[str], parent=None):
        super().__init__(parent)
        self.track_data = track_data
        self.track_type = track_data.get('type')
        self.codec_id = track_data.get('codec_id')

        # --- UI Elements ---
        self.summary_label = QLabel("...")
        self.summary_label.setStyleSheet("font-weight: bold;")
        self.source_label = QLabel("...")
        self.badge_label = QLabel("")
        self.badge_label.setStyleSheet("color: #E0A800; font-weight: bold;")

        # Quick-access controls
        self.cb_default = QCheckBox("Default")
        self.cb_forced = QCheckBox("Forced")
        self.cb_name = QCheckBox("Set Name")

        # Hidden controls whose state is managed by the settings dialog
        self.cb_ocr = QCheckBox("Perform OCR")
        self.cb_cleanup = QCheckBox("Perform Cleanup")
        self.cb_convert = QCheckBox("To ASS")
        self.cb_rescale = QCheckBox("Rescale")
        self.size_multiplier = QDoubleSpinBox()
        self.size_multiplier.setRange(0.1, 10.0)
        self.size_multiplier.setSingleStep(0.1)
        self.size_multiplier.setDecimals(2)
        self.size_multiplier.setPrefix("Size x")

        # Feature-specific controls
        self.sync_to_label = QLabel("Sync to Source:")
        self.sync_to_combo = QComboBox()
        self.style_editor_btn = QPushButton("Style Editor...")
        self.settings_btn = QPushButton("Settings...")

        # --- Logic Controller ---
        self.logic = TrackWidgetLogic(self, track_data, available_sources)

        # --- Layout ---
        self._build_layout()

        # --- Initial State ---
        self.logic.refresh_summary()
        self.logic.refresh_badges()

        # --- Connections ---
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        self.cb_default.stateChanged.connect(self.logic.refresh_badges)
        self.cb_forced.stateChanged.connect(self.logic.refresh_badges)

    def _build_layout(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(5, 5, 5, 5)
        top_row = QHBoxLayout()
        top_row.addWidget(self.summary_label, 1)
        top_row.addWidget(self.badge_label)
        top_row.addWidget(self.source_label)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        bottom_row.addWidget(self.sync_to_label)
        bottom_row.addWidget(self.sync_to_combo)
        bottom_row.addWidget(self.cb_default)
        bottom_row.addWidget(self.cb_forced)
        bottom_row.addWidget(self.cb_name)
        bottom_row.addWidget(self.style_editor_btn)
        bottom_row.addWidget(self.settings_btn)

        root_layout.addLayout(top_row)
        root_layout.addLayout(bottom_row)

    def _open_settings_dialog(self):
        """Open the detailed settings dialog and apply the results."""
        current_config = self.logic.get_config()

        dialog = TrackSettingsDialog(
            track_type=self.track_type,
            codec_id=self.codec_id,
            **current_config
        )

        if dialog.exec():
            new_config = dialog.read_values()
            # Update the hidden controls on this widget
            self.cb_ocr.setChecked(new_config.get('perform_ocr', False))
            self.cb_cleanup.setChecked(new_config.get('perform_ocr_cleanup', False))
            self.cb_convert.setChecked(new_config.get('convert_to_ass', False))
            self.cb_rescale.setChecked(new_config.get('rescale', False))
            self.size_multiplier.setValue(new_config.get('size_multiplier', 1.0))

            # NEW: Store custom language in track_data
            custom_lang = new_config.get('custom_lang', '')
            if custom_lang:
                self.track_data['custom_lang'] = custom_lang
            elif 'custom_lang' in self.track_data:
                del self.track_data['custom_lang']

            self.logic.refresh_badges()
            self.logic.refresh_summary()

    def get_config(self) -> Dict[str, Any]:
        """Public method to get the final configuration from the widget's controls."""
        return self.logic.get_config()
