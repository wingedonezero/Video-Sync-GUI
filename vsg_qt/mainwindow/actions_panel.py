# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QGroupBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox

class ActionsPanel(QGroupBox):
    """
    Analyze Only / Analyze & Merge buttons + Archive logs checkbox.
    Emits signals so MainWindow can react.
    """
    analyze_only = Signal()
    analyze_merge = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Actions", parent)
        v = QVBoxLayout(self)

        row = QHBoxLayout()
        self.btn_analyze = QPushButton("Analyze Only")
        self.btn_merge = QPushButton("Analyze & Merge")
        row.addWidget(self.btn_analyze)
        row.addWidget(self.btn_merge)
        row.addStretch(1)
        v.addLayout(row)

        self.archive_checkbox = QCheckBox("Archive logs to a zip file on batch completion")
        v.addWidget(self.archive_checkbox)

        self.btn_analyze.clicked.connect(self.analyze_only.emit)
        self.btn_merge.clicked.connect(self.analyze_merge.emit)

    def get_archive(self) -> bool:
        return self.archive_checkbox.isChecked()

    def set_archive(self, checked: bool):
        self.archive_checkbox.setChecked(bool(checked))
