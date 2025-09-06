# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox

class MergeBehaviorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.apply_dialog_norm_gain = QCheckBox("Remove dialog normalization gain (AC3/E-AC3)")
        self.disable_track_statistics_tags = QCheckBox("Disable track statistics tags (for purist remuxes)")

        form = QFormLayout(self)
        form.addRow(self.apply_dialog_norm_gain)
        form.addRow(self.disable_track_statistics_tags)

    def load_from(self, cfg):
        self.apply_dialog_norm_gain.setChecked(bool(cfg.get("apply_dialog_norm_gain")))
        self.disable_track_statistics_tags.setChecked(bool(cfg.get("disable_track_statistics_tags")))

    def store_into(self, cfg):
        cfg.set("apply_dialog_norm_gain", self.apply_dialog_norm_gain.isChecked())
        cfg.set("disable_track_statistics_tags", self.disable_track_statistics_tags.isChecked())
