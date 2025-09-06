# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QHBoxLayout, QGroupBox, QLabel

class ResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        grp = QGroupBox('Latest Job Results')
        row = QHBoxLayout(grp)
        row.addWidget(QLabel('Secondary Delay:'))
        self.sec = QLabel('—')
        row.addWidget(self.sec)
        row.addSpacing(20)
        row.addWidget(QLabel('Tertiary Delay:'))
        self.ter = QLabel('—')
        row.addWidget(self.ter)
        row.addStretch(1)

        outer = QHBoxLayout(self)
        outer.addWidget(grp)

    # public API
    def set_sec_delay(self, ms: int | None):
        self.sec.setText(f"{ms} ms" if ms is not None else "—")

    def set_ter_delay(self, ms: int | None):
        self.ter.setText(f"{ms} ms" if ms is not None else "—")

    def reset(self):
        self.set_sec_delay(None)
        self.set_ter_delay(None)
