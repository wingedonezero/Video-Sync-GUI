# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QCheckBox

from PySide6.QtCore import Signal

class ActionsPanel(QWidget):
    """
    Analyze / Analyze & Merge buttons + archive logs checkbox.
    Emits:
      - analyzeRequested(and_merge: bool)
    """
    analyzeRequested = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        grp = QGroupBox('Actions')
        gl = QVBoxLayout(grp)

        row = QHBoxLayout()
        self.btn_analyze = QPushButton('Analyze Only')
        self.btn_merge = QPushButton('Analyze & Merge')
        self.btn_analyze.clicked.connect(lambda: self.analyzeRequested.emit(False))
        self.btn_merge.clicked.connect(lambda: self.analyzeRequested.emit(True))
        row.addWidget(self.btn_analyze)
        row.addWidget(self.btn_merge)
        row.addStretch(1)
        gl.addLayout(row)

        self.cb_archive_logs = QCheckBox("Archive logs to a zip file on batch completion")
        gl.addWidget(self.cb_archive_logs)

        root.addWidget(grp)

    # public API
    def archive_enabled(self) -> bool:
        return self.cb_archive_logs.isChecked()

    def set_archive_enabled(self, val: bool):
        self.cb_archive_logs.setChecked(val)
