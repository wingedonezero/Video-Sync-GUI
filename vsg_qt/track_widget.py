# vsg_qt/track_widget.py

# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QCheckBox, QDoubleSpinBox
from PySide6.QtCore import Qt

class TrackWidget(QWidget):
    def __init__(self, track_data: dict, parent=None):
        super().__init__(parent)
        self.track_data = track_data
        self.track_type = track_data.get('type', 'unknown')
        self.codec_id = track_data.get('codec_id', '')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        name_part = f" '{track_data['name']}'" if track_data['name'] else ""
        item_text = (f"[{self.track_type[0].upper()}-{track_data['id']}] "
                     f"{self.codec_id} ({track_data['lang']}){name_part}")
        label = QLabel(item_text)
        label.setToolTip(f"Source: {track_data.get('source', 'N/A')}")
        layout.addWidget(label, 1)

        self.cb_default = QCheckBox("Default")
        self.cb_forced = QCheckBox("Forced")
        self.cb_convert = QCheckBox("Convert to ASS")
        self.cb_rescale = QCheckBox("Rescale")
        self.size_multiplier = QDoubleSpinBox()
        self.size_multiplier.setRange(0.1, 5.0)
        self.size_multiplier.setSingleStep(0.1)
        self.size_multiplier.setValue(1.0)
        self.size_multiplier.setSuffix("x Size")

        self.cb_name = QCheckBox("Keep Name")
        self.cb_name.setChecked(False)

        if self.track_type == 'audio':
            layout.addWidget(self.cb_default)
        elif self.track_type == 'subtitles':
            layout.addWidget(self.cb_default)
            layout.addWidget(self.cb_forced)
            if 'S_TEXT/UTF8' in self.codec_id.upper(): # Only show for SRT
                layout.addWidget(self.cb_convert)
            layout.addWidget(self.cb_rescale)
            layout.addWidget(self.size_multiplier)

        layout.addWidget(self.cb_name)

    def get_config(self) -> dict:
        return {
            'is_default': self.cb_default.isChecked(),
            'is_forced_display': self.cb_forced.isChecked(),
            'apply_track_name': self.cb_name.isChecked(),
            'convert_to_ass': self.cb_convert.isChecked(),
            'rescale': self.cb_rescale.isChecked(),
            'size_multiplier': self.size_multiplier.value() if self.track_type == 'subtitles' else 1.0
        }
