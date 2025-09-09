# vsg_qt/track_widget/ui.py
from __future__ import annotations
from typing import List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QToolButton, QWidget as QtWidget, QFormLayout, QPushButton, QComboBox
)
from PySide6.QtCore import Qt
from .logic import TrackWidgetLogic

class TrackWidget(QWidget):
    """
    Reusable row widget shown in ManualSelectionDialog's Final list.
    """
    def __init__(self, track_data: dict, available_sources: List[str] = None, parent=None):
        super().__init__(parent)
        self.track_data = track_data
        self.track_type = track_data.get('type', 'unknown')
        self.codec_id = track_data.get('codec_id', '')
        self.source = track_data.get('source', 'N/A')

        # ---------- Hidden state controls (single source of truth) ----------
        self.cb_default = QCheckBox("Default")
        self.cb_forced = QCheckBox("Forced")
        self.cb_convert = QCheckBox("Convert to ASS")
        self.cb_rescale = QCheckBox("Rescale")
        self.size_multiplier = QDoubleSpinBox(); self.size_multiplier.setRange(0.1, 5.0); self.size_multiplier.setSingleStep(0.1); self.size_multiplier.setValue(1.0); self.size_multiplier.setSuffix("x")
        self.cb_name = QCheckBox("Keep Name")

        is_subs = (self.track_type == 'subtitles')
        self.cb_forced.setVisible(is_subs)
        self.cb_convert.setVisible(is_subs)
        self.cb_rescale.setVisible(is_subs)
        self.size_multiplier.setVisible(is_subs)
        self.cb_convert.setEnabled(is_subs and 'S_TEXT/UTF8' in (self.codec_id or '').upper())

        # ---------- Visible layout ----------
        root = QVBoxLayout(self)
        root.setContentsMargins(5, 2, 5, 2); root.setSpacing(2)

        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
        self.label = QLabel("")
        self.label.setToolTip(f"Source: {self.source}, Path: {self.track_data.get('original_path', 'N/A')}")
        row.addWidget(self.label, 1)

        # --- NEW: Sync To Dropdown for External Files ---
        self.sync_to_combo = QComboBox()
        self.sync_to_combo.setVisible(False)
        if self.source == 'External' and available_sources:
            self.sync_to_combo.addItem("No Sync", None)
            for src_name in available_sources:
                self.sync_to_combo.addItem(src_name, src_name)
            self.sync_to_combo.setVisible(True)
            row.addWidget(QLabel("Sync to:"))
            row.addWidget(self.sync_to_combo)
        # ----------------------------------------------

        self.style_editor_btn = QPushButton("Style Editor...")
        self.style_editor_btn.setVisible(is_subs)
        editable_sub_codecs = ['S_TEXT/UTF8', 'S_TEXT/ASS', 'S_TEXT/SSA']
        is_editable = any(codec in (self.codec_id or '').upper() for codec in editable_sub_codecs)
        self.style_editor_btn.setEnabled(is_editable)
        if not is_editable and is_subs:
            self.style_editor_btn.setToolTip("Style editor is not available for image-based subtitles (e.g., PGS, VobSub).")
        row.addWidget(self.style_editor_btn)

        self.btn = QToolButton(self)
        self.btn.setText("Settings…")
        self.btn.setPopupMode(QToolButton.InstantPopup)
        row.addWidget(self.btn, 0, Qt.AlignRight)
        root.addLayout(row)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #cfcfcf; font-size: 12px;")
        self.summary.setVisible(False)
        root.addWidget(self.summary)

        self._logic = TrackWidgetLogic(self)

        # Connect widget changes to logic updater
        self.cb_default.toggled.connect(self._logic.apply_state_from_menu)
        self.cb_name.toggled.connect(self._logic.apply_state_from_menu)
        if is_subs:
            self.cb_forced.toggled.connect(self._logic.apply_state_from_menu)
            self.cb_convert.toggled.connect(self._logic.apply_state_from_menu)
            self.cb_rescale.toggled.connect(self._logic.apply_state_from_menu)
            self.size_multiplier.valueChanged.connect(lambda _v: self._logic.apply_state_from_menu())
        if self.sync_to_combo.isVisible():
            self.sync_to_combo.currentIndexChanged.connect(self._logic.apply_state_from_menu)

    def _build_menu_form(self) -> QWidget:
        container = QWidget(self)
        form = QFormLayout(container); form.setContentsMargins(8,8,8,8)
        form.addRow(self.cb_default)
        if self.track_type == 'subtitles':
            form.addRow(self.cb_forced)
            form.addRow(self.cb_convert)
            form.addRow(self.cb_rescale)
            form.addRow("Size multiplier:", self.size_multiplier)
        form.addRow(self.cb_name)
        return container

    def refresh_badges(self):
        self._logic.refresh_badges()

    def refresh_summary(self):
        self._logic.refresh_summary()

    def get_config(self) -> dict:
        return self._logic.get_config()
