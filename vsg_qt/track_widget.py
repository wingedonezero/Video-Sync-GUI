# vsg_qt/track_widget.py
# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QDoubleSpinBox,
    QToolButton, QMenu, QWidgetAction, QWidget as QtWidget
)
from PySide6.QtCore import Qt

class TrackWidget(QWidget):
    def __init__(self, track_data: dict, parent=None):
        super().__init__(parent)
        self.track_data = track_data
        self.track_type = track_data.get('type', 'unknown')
        self.codec_id = track_data.get('codec_id', '')
        self.source = track_data.get('source', 'N/A')

        # ===== Hidden state controls (pipeline compatibility) =====
        self.cb_default = QCheckBox("Default"); self.cb_default.setVisible(False)
        self.cb_forced = QCheckBox("Forced"); self.cb_forced.setVisible(False)
        self.cb_convert = QCheckBox("Convert to ASS"); self.cb_convert.setVisible(False)
        self.cb_rescale = QCheckBox("Rescale"); self.cb_rescale.setVisible(False)
        self.size_multiplier = QDoubleSpinBox()
        self.size_multiplier.setRange(0.1, 5.0)
        self.size_multiplier.setSingleStep(0.1)
        self.size_multiplier.setValue(1.0)
        self.size_multiplier.setSuffix("x")
        self.size_multiplier.setVisible(False)
        self.cb_name = QCheckBox("Keep Name"); self.cb_name.setVisible(False)

        # ===== Visible rows =====
        root = QVBoxLayout(self); root.setContentsMargins(5, 2, 5, 2); root.setSpacing(2)

        # Top row: label + settings dropdown
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
        self.label = QLabel(self._compose_label_text())
        self.label.setToolTip(f"Source: {self.source}")
        row.addWidget(self.label, 1)

        self.btn = QToolButton(self)
        self.btn.setText("Settings…")
        self.btn.setPopupMode(QToolButton.InstantPopup)
        self._ensure_menu()
        self.btn.setMenu(self.menu)
        row.addWidget(self.btn, 0, Qt.AlignRight)

        root.addLayout(row)

        # Second row: inline options summary
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #cfcfcf; font-size: 12px;")
        self.summary.setVisible(False)
        root.addWidget(self.summary)

        # Ensure initial render reflects current state
        self.refresh_badges()
        self.refresh_summary()

    # ---------- Menu construction / synchronization ----------
    def _ensure_menu(self):
        if hasattr(self, 'menu') and self.menu is not None:
            return
        self.menu = QMenu(self)

        container = QtWidget(self.menu)
        v = QVBoxLayout(container); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        # Default (all types)
        self.m_default = QCheckBox("Default")

        # Subtitle-only controls
        self.m_forced = QCheckBox("Forced display (subtitles)")  # subs only
        self.m_convert = QCheckBox("Convert SRT → ASS")          # enabled for SRT only
        self.m_rescale = QCheckBox("Rescale to video resolution") # subs only
        self.m_size = QDoubleSpinBox(); self.m_size.setRange(0.1, 5.0); self.m_size.setSingleStep(0.1); self.m_size.setSuffix("x")

        self.m_name = QCheckBox("Keep original track name")

        v.addWidget(self.m_default)

        if self.track_type == 'subtitles':
            v.addWidget(self.m_forced)
            v.addWidget(self.m_convert)
            self.m_convert.setEnabled('S_TEXT/UTF8' in (self.codec_id or '').upper())
            v.addWidget(self.m_rescale)
            v.addWidget(self.m_size)
        v.addWidget(self.m_name)

        wa = QWidgetAction(self.menu)
        wa.setDefaultWidget(container)
        self.menu.addAction(wa)

        # Sync values when menu shows
        self.menu.aboutToShow.connect(self._sync_state_to_menu)
        # Apply on any toggle changes live
        self.m_default.toggled.connect(self._apply_menu_to_state)
        self.m_name.toggled.connect(self._apply_menu_to_state)
        if self.track_type == 'subtitles':
            self.m_forced.toggled.connect(self._apply_menu_to_state)
            self.m_convert.toggled.connect(self._apply_menu_to_state)
            self.m_rescale.toggled.connect(self._apply_menu_to_state)
            self.m_size.valueChanged.connect(self._apply_menu_to_state)

    def _sync_state_to_menu(self):
        self.m_default.setChecked(self.cb_default.isChecked())
        self.m_name.setChecked(self.cb_name.isChecked())
        if self.track_type == 'subtitles':
            self.m_forced.setChecked(self.cb_forced.isChecked())
            self.m_convert.setChecked(self.cb_convert.isChecked() and self.m_convert.isEnabled())
            self.m_rescale.setChecked(self.cb_rescale.isChecked())
            self.m_size.setValue(self.size_multiplier.value())

    def _apply_menu_to_state(self, *args):
        # Push menu widget values into hidden state controls
        was_default = self.cb_default.isChecked()
        self.cb_default.setChecked(self.m_default.isChecked())
        self.cb_name.setChecked(self.m_name.isChecked())
        if self.track_type == 'subtitles':
            self.cb_forced.setChecked(self.m_forced.isChecked())
            self.cb_convert.setChecked(self.m_convert.isChecked() and self.m_convert.isEnabled())
            self.cb_rescale.setChecked(self.m_rescale.isChecked())
            self.size_multiplier.setValue(self.m_size.value())

        # Emit toggled if default changed to trigger single-default enforcement upstream
        if was_default != self.cb_default.isChecked():
            try:
                self.cb_default.toggled.emit(self.cb_default.isChecked())
            except Exception:
                pass

        # Refresh UI summary/badges
        self.refresh_badges()
        self.refresh_summary()

    # ---------- Label & summary rendering ----------
    def _compose_label_text(self) -> str:
        base = f"[{self.source}] [{self.track_type[0].upper()}-{self.track_data.get('id')}] {self.codec_id} ({self.track_data.get('lang', 'und')})"
        name_part = f" '{self.track_data.get('name')}'" if self.track_data.get('name') else ""
        badges = []
        if self.cb_default.isChecked():
            badges.append("⭐")
        if self.track_type == 'subtitles':
            if self.cb_forced.isChecked():
                badges.append("📌")
            if self.cb_rescale.isChecked():
                badges.append("📏")
            # Badge when size multiplier != 1.0
            try:
                if abs(float(self.size_multiplier.value()) - 1.0) > 1e-6:
                    badges.append("🔤")
            except Exception:
                pass
        badge_str = ("  " + " ".join(badges)) if badges else ""
        return base + name_part + badge_str

    def refresh_badges(self):
        self.label.setText(self._compose_label_text())

    def refresh_summary(self):
        parts = []
        if self.cb_default.isChecked():
            parts.append("⭐ Default")
        if self.track_type == 'subtitles':
            if self.cb_forced.isChecked():
                parts.append("📌 Forced Display")
            if self.cb_rescale.isChecked():
                parts.append("📏 Rescale")
            if abs(self.size_multiplier.value() - 1.0) > 1e-6:
                parts.append(f"{self.size_multiplier.value():.2f}x Size")
            if self.cb_convert.isChecked():
                parts.append("Convert to ASS")
        if self.cb_name.isChecked():
            parts.append("Keep Name")

        if parts:
            self.summary.setText("└  ⚙ Options: " + ", ".join(parts))
            self.summary.setVisible(True)
        else:
            self.summary.clear()
            self.summary.setVisible(False)

    # ---------- Public API ----------
    def get_config(self) -> dict:
        return {
            'is_default': self.cb_default.isChecked(),
            'is_forced_display': self.cb_forced.isChecked(),
            'apply_track_name': self.cb_name.isChecked(),
            'convert_to_ass': self.cb_convert.isChecked(),
            'rescale': self.cb_rescale.isChecked(),
            'size_multiplier': self.size_multiplier.value() if self.track_type == 'subtitles' else 1.0
        }
