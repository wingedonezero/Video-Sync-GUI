# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QTextEdit

class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        grp = QGroupBox('Log')
        v = QVBoxLayout(grp)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFontFamily('monospace')
        v.addWidget(self.text)

        outer = QVBoxLayout(self)
        outer.addWidget(grp)

    # public API
    def clear(self):
        self.text.clear()

    def append(self, message: str, autoscroll: bool = True):
        self.text.append(message)
        if autoscroll:
            bar = self.text.verticalScrollBar()
            bar.setValue(bar.maximum())
