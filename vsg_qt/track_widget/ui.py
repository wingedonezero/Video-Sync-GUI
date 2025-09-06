from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QToolButton, QWidget as QtWidget, QFormLayout
)
from PySide6.QtCore import Qt
from .logic import TrackWidgetLogic

class TrackWidget(QWidget):
    """
    Reusable row widget shown in ManualSelectionDialog's Final list.
    Public API preserved:
      - attributes: track_data, track_type, codec_id, source
                    cb_default, cb_forced, cb_convert, cb_rescale, size_multiplier, cb_name
      - methods: refresh_badges(), refresh_summary(), get_config()
    """
    def __init__(self, track_data: dict, parent=None):
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

        # Initial visibility/enablement based on track type/codec
        is_subs = (self.track_type == 'subtitles')
        self.cb_forced.setVisible(is_subs)
        self.cb_convert.setVisible(is_subs)
        self.cb_rescale.setVisible(is_subs)
        self.size_multiplier.setVisible(is_subs)
        self.cb_convert.setEnabled(is_subs and 'S_TEXT/UTF8' in (self.codec_id or '').upper())

        # ---------- Visible layout ----------
        root = QVBoxLayout(self)
        root.setContentsMargins(5, 2, 5, 2); root.setSpacing(2)

        # Top row: label + dropdown
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
        self.label = QLabel("")   # text filled by logic
        self.label.setToolTip(f"Source: {self.source}")
        row.addWidget(self.label, 1)

        self.btn = QToolButton(self)
        self.btn.setText("Settings…")
        self.btn.setPopupMode(QToolButton.InstantPopup)
        row.addWidget(self.btn, 0, Qt.AlignRight)
        root.addLayout(row)

        # Second row: inline summary (hidden until content)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #cfcfcf; font-size: 12px;")
        self.summary.setVisible(False)
        root.addWidget(self.summary)

        # Install behavior
        self._logic = TrackWidgetLogic(self)

        # Connect widget changes to logic updater
        self.cb_default.toggled.connect(self._logic.apply_state_from_menu)
        self.cb_name.toggled.connect(self._logic.apply_state_from_menu)
        if is_subs:
            self.cb_forced.toggled.connect(self._logic.apply_state_from_menu)
            self.cb_convert.toggled.connect(self._logic.apply_state_from_menu)
            self.cb_rescale.toggled.connect(self._logic.apply_state_from_menu)
            self.size_multiplier.valueChanged.connect(lambda _v: self._logic.apply_state_from_menu())

    # ---------- Menu form factory (consumed by logic) ----------
    def _build_menu_form(self) -> QtWidget:
        """
        Builds a simple form layout made of the same hidden controls.
        Using the same widgets means state is always synchronized.
        """
        container = QtWidget(self)
        form = QFormLayout(container); form.setContentsMargins(8,8,8,8)

        form.addRow(self.cb_default)
        if self.track_type == 'subtitles':
            form.addRow(self.cb_forced)
            form.addRow(self.cb_convert)
            form.addRow(self.cb_rescale)
            form.addRow("Size multiplier:", self.size_multiplier)
        form.addRow(self.cb_name)
        return container

    # ---------- Public API (kept for backward compatibility) ----------
    def refresh_badges(self):
        self._logic.refresh_badges()

    def refresh_summary(self):
        self._logic.refresh_summary()

    def get_config(self) -> dict:
        return self._logic.get_config()
