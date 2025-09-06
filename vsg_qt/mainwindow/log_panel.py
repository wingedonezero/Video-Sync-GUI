# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QTextEdit

class LogPanel(QGroupBox):
    """
    Monospace read-only log view with simple autoscroll helper.
    """
    def __init__(self, parent=None):
        super().__init__("Log", parent)
        v = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFontFamily("monospace")
        v.addWidget(self.text)

    def clear(self):
        self.text.clear()

    def append(self, s: str, *, autoscroll: bool = True):
        self.text.append(s)
        if autoscroll:
            sb = self.text.verticalScrollBar()
            sb.setValue(sb.maximum())
