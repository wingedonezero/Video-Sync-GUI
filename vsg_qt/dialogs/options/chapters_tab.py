# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox

class ChaptersTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rename_chapters = QCheckBox('Rename to "Chapter NN"')
        self.snap_chapters = QCheckBox("Snap chapter timestamps to nearest keyframe")
        self.snap_mode = QComboBox(); self.snap_mode.addItems(["previous", "nearest"])
        self.snap_threshold_ms = QSpinBox(); self.snap_threshold_ms.setRange(0, 5000)
        self.snap_starts_only = QCheckBox("Only snap chapter start times (not end times)")

        form = QFormLayout(self)
        form.addRow(self.rename_chapters)
        form.addRow(self.snap_chapters)
        form.addRow("Snap Mode:", self.snap_mode)
        form.addRow("Snap Threshold (ms):", self.snap_threshold_ms)
        form.addRow(self.snap_starts_only)

    def load_from(self, cfg):
        self.rename_chapters.setChecked(bool(cfg.get("rename_chapters")))
        self.snap_chapters.setChecked(bool(cfg.get("snap_chapters")))
        self.snap_mode.setCurrentText(cfg.get("snap_mode"))
        self.snap_threshold_ms.setValue(int(cfg.get("snap_threshold_ms")))
        self.snap_starts_only.setChecked(bool(cfg.get("snap_starts_only")))

    def store_into(self, cfg):
        cfg.set("rename_chapters", self.rename_chapters.isChecked())
        cfg.set("snap_chapters", self.snap_chapters.isChecked())
        cfg.set("snap_mode", self.snap_mode.currentText())
        cfg.set("snap_threshold_ms", self.snap_threshold_ms.value())
        cfg.set("snap_starts_only", self.snap_starts_only.isChecked())
