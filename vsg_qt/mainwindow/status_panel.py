# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar

class StatusPanel(QWidget):
    """
    Status text + progress bar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.addWidget(QLabel("Status:"))
        self.label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        row.addWidget(self.label, 1)
        row.addWidget(self.progress)

    def set_status(self, text: str):
        self.label.setText(text)

    def set_progress(self, frac_0_1: float):
        self.progress.setValue(int(max(0.0, min(1.0, frac_0_1)) * 100))

    def reset(self):
        self.set_status("Ready")
        self.set_progress(0.0)
