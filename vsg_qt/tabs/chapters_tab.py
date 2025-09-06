# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox
from ._widgets import get_val, set_val

class ChaptersTab(QWidget):
    """
    Chapter processing settings.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = {}
        form = QFormLayout(self)

        self.controls['rename_chapters'] = QCheckBox('Rename to "Chapter NN"')
        self.controls['snap_chapters'] = QCheckBox('Snap chapter timestamps to nearest keyframe')
        self.controls['snap_mode'] = QComboBox(); self.controls['snap_mode'].addItems(['previous', 'nearest'])
        self.controls['snap_threshold_ms'] = QSpinBox(); self.controls['snap_threshold_ms'].setRange(0, 5000)
        self.controls['snap_starts_only'] = QCheckBox('Only snap chapter start times (not end times)')

        form.addRow(self.controls['rename_chapters'])
        form.addRow(self.controls['snap_chapters'])
        form.addRow('Snap Mode:', self.controls['snap_mode'])
        form.addRow('Snap Threshold (ms):', self.controls['snap_threshold_ms'])
        form.addRow(self.controls['snap_starts_only'])

    def load(self, cfg: dict):
        for k, w in self.controls.items():
            set_val(w, cfg.get(k))

    def dump(self) -> dict:
        return {k: get_val(w) for k, w in self.controls.items()}
