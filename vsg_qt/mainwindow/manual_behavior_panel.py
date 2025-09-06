# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QCheckBox, QLabel

class ManualBehaviorPanel(QGroupBox):
    """
    Manual Selection behavior controls:
      - Auto-apply this layout to all matching files in batch
      - Strict match (type + lang + codec)
    """
    def __init__(self, parent=None):
        super().__init__("Manual Selection Behavior", parent)
        v = QVBoxLayout(self)
        helper = QLabel("For Analyze & Merge, you’ll select tracks per file. "
                        "Auto-apply reuses your last layout when the track signature matches.")
        helper.setWordWrap(True)
        v.addWidget(helper)

        self.cb_auto_apply = QCheckBox("Auto-apply this layout to all matching files in batch")
        self.cb_strict = QCheckBox("Strict match (type + lang + codec)")

        v.addWidget(self.cb_auto_apply)
        v.addWidget(self.cb_strict)

    def get_auto_apply(self) -> bool:
        return self.cb_auto_apply.isChecked()

    def set_auto_apply(self, checked: bool):
        self.cb_auto_apply.setChecked(bool(checked))

    def get_strict(self) -> bool:
        return self.cb_strict.isChecked()

    def set_strict(self, checked: bool):
        self.cb_strict.setChecked(bool(checked))
