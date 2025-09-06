# vsg_qt/options_dialog.py
# -*- coding: utf-8 -*-
"""
Settings dialog (modular tabs host).
"""
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QTabWidget, QScrollArea, QWidget
)
from PySide6.QtCore import Qt

from vsg_qt.tabs import StorageTab, AnalysisTab, ChaptersTab, MergeBehaviorTab, LoggingTab

class OptionsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('Application Settings')
        self.setMinimumSize(900, 600)

        self.tabs = QTabWidget()
        self._pages = []

        def wrap(widget: QWidget) -> QScrollArea:
            sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(widget); return sa

        # instantiate tabs
        self.storage_tab = StorageTab(self);   self._pages.append(self.storage_tab)
        self.analysis_tab = AnalysisTab(self); self._pages.append(self.analysis_tab)
        self.chapters_tab = ChaptersTab(self); self._pages.append(self.chapters_tab)
        self.merge_tab = MergeBehaviorTab(self); self._pages.append(self.merge_tab)
        self.logging_tab = LoggingTab(self);   self._pages.append(self.logging_tab)

        # add wrapped tabs
        self.tabs.addTab(wrap(self.storage_tab), 'Storage')
        self.tabs.addTab(wrap(self.analysis_tab), 'Analysis')
        self.tabs.addTab(wrap(self.chapters_tab), 'Chapters')
        self.tabs.addTab(wrap(self.merge_tab), 'Merge Behavior')
        self.tabs.addTab(wrap(self.logging_tab), 'Logging')

        main = QVBoxLayout(self)
        main.addWidget(self.tabs)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)

        self.load_settings()

    # ---------- I/O ----------
    def load_settings(self):
        cfg = self.config.settings
        for page in self._pages:
            page.load(cfg)

    def accept(self):
        # collect values from each page and write into config
        merged = {}
        for page in self._pages:
            merged.update(page.dump())
        for k, v in merged.items():
            self.config.set(k, v)
        super().accept()
