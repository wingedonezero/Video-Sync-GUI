# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel

class ResultsPanel(QGroupBox):
    """
    Displays latest job results (secondary/tertiary delays).
    """
    def __init__(self, parent=None):
        super().__init__("Latest Job Results", parent)
        row = QHBoxLayout(self)
        row.addWidget(QLabel("Secondary Delay:"))
        self.lbl_sec = QLabel("—")
        row.addWidget(self.lbl_sec)
        row.addSpacing(20)
        row.addWidget(QLabel("Tertiary Delay:"))
        self.lbl_ter = QLabel("—")
        row.addWidget(self.lbl_ter)
        row.addStretch(1)
        self.setLayout(row)

    def set_delays(self, sec_ms: int | None, ter_ms: int | None):
        self.lbl_sec.setText(f"{sec_ms} ms" if sec_ms is not None else "—")
        self.lbl_ter.setText(f"{ter_ms} ms" if ter_ms is not None else "—")

    def reset(self):
        self.set_delays(None, None)
