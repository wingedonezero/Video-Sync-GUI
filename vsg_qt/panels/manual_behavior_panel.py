# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QCheckBox

class ManualBehaviorPanel(QWidget):
    """
    Auto-apply behavior controls (used only when merging).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        grp = QGroupBox("Manual Selection Behavior")
        gl = QVBoxLayout(grp)

        helper = QLabel("For Analyze & Merge, you’ll select tracks per file. "
                        "Auto-apply reuses your last layout when the track signature matches.")
        helper.setWordWrap(True)
        gl.addWidget(helper)

        self.cb_auto_apply = QCheckBox("Auto-apply this layout to all matching files in batch")
        self.cb_strict = QCheckBox("Strict match (type + lang + codec)")

        gl.addWidget(self.cb_auto_apply)
        gl.addWidget(self.cb_strict)
        root.addWidget(grp)

    # public API
    def is_auto_apply(self) -> bool:
        return self.cb_auto_apply.isChecked()

    def is_strict(self) -> bool:
        return self.cb_strict.isChecked()

    def set_values(self, auto_apply: bool, strict: bool):
        self.cb_auto_apply.setChecked(auto_apply)
        self.cb_strict.setChecked(strict)
