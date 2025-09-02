# vsg_qt/track_settings_dialog.py
# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox,
    QCheckBox, QLabel, QDoubleSpinBox, QWidget
)
from PySide6.QtCore import Qt

class TrackSettingsDialog(QDialog):
    """
    Small popup dialog to edit per-track options.
    Mirrors the fields already stored on TrackWidget but in a compact UI.
    """
    def __init__(self, *, track_type: str, codec_id: str,
                 is_default: bool, is_forced_display: bool,
                 apply_track_name: bool, convert_to_ass: bool,
                 rescale: bool, size_multiplier: float, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle("Track Settings")
        self.setMinimumWidth(360)

        vbox = QVBoxLayout(self)

        self.cb_default = QCheckBox("Default")
        self.cb_default.setChecked(is_default)
        vbox.addWidget(self.cb_default)

        # Subtitle-only options
        is_subs = (track_type == 'subtitles')
        if is_subs:
            self.cb_forced = QCheckBox("Forced")
            self.cb_forced.setChecked(is_forced_display)
            vbox.addWidget(self.cb_forced)

            self.cb_convert = QCheckBox("Convert to ASS (SRT only)")
            self.cb_convert.setChecked(convert_to_ass and 'S_TEXT/UTF8' in (codec_id or '').upper())
            self.cb_convert.setEnabled('S_TEXT/UTF8' in (codec_id or '').upper())
            vbox.addWidget(self.cb_convert)

            self.cb_rescale = QCheckBox("Rescale to video resolution")
            self.cb_rescale.setChecked(rescale)
            vbox.addWidget(self.cb_rescale)

            size_row = QHBoxLayout()
            size_label = QLabel("Size multiplier:")
            self.size_multiplier = QDoubleSpinBox()
            self.size_multiplier.setRange(0.1, 5.0)
            self.size_multiplier.setSingleStep(0.1)
            self.size_multiplier.setValue(size_multiplier if size_multiplier else 1.0)
            self.size_multiplier.setSuffix("x")
            size_row.addWidget(size_label)
            size_row.addWidget(self.size_multiplier, 1)
            vbox.addLayout(size_row)
        else:
            # Placeholders to simplify get_values()
            self.cb_forced = QCheckBox("Forced"); self.cb_forced.setChecked(False); self.cb_forced.setVisible(False)
            self.cb_convert = QCheckBox("Convert to ASS"); self.cb_convert.setChecked(False); self.cb_convert.setVisible(False)
            self.cb_rescale = QCheckBox("Rescale"); self.cb_rescale.setChecked(False); self.cb_rescale.setVisible(False)
            self.size_multiplier = QDoubleSpinBox(); self.size_multiplier.setValue(1.0); self.size_multiplier.setVisible(False)

        self.cb_name = QCheckBox("Keep Name")
        self.cb_name.setChecked(apply_track_name)
        vbox.addWidget(self.cb_name)

        vbox.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        vbox.addWidget(btns)

    def get_values(self) -> dict:
        return {
            'is_default': self.cb_default.isChecked(),
            'is_forced_display': self.cb_forced.isChecked(),
            'apply_track_name': self.cb_name.isChecked(),
            'convert_to_ass': self.cb_convert.isChecked(),
            'rescale': self.cb_rescale.isChecked(),
            'size_multiplier': self.size_multiplier.value()
        }
