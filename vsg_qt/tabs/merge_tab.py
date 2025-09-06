# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox
from ._widgets import get_val, set_val

class MergeBehaviorTab(QWidget):
    """
    Merge behavior flags (container/mkvmerge level).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = {}
        form = QFormLayout(self)

        self.controls['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)')
        self.controls['disable_track_statistics_tags'] = QCheckBox('Disable track statistics tags (for purist remuxes)')

        form.addRow(self.controls['apply_dialog_norm_gain'])
        form.addRow(self.controls['disable_track_statistics_tags'])

    def load(self, cfg: dict):
        for k, w in self.controls.items():
            set_val(w, cfg.get(k))

    def dump(self) -> dict:
        return {k: get_val(w) for k, w in self.controls.items()}
