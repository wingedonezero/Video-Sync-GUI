# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar

class StatusPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.addWidget(QLabel('Status:'))
        self.label = QLabel('Ready')
        row.addWidget(self.label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        row.addWidget(self.progress)

    # public API
    def set_status(self, text: str):
        self.label.setText(text)

    def set_progress(self, value01: float):
        self.progress.setValue(int(value01 * 100))
