# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QDialogButtonBox, QScrollArea
from .storage_tab import StorageTab
from .analysis_tab import AnalysisTab
from .chapters_tab import ChaptersTab
from .merge_behavior_tab import MergeBehaviorTab
from .logging_tab import LoggingTab

class OptionsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Application Settings")
        self.setMinimumSize(900, 600)

        self.tabs = QTabWidget()

        self.storage_tab = StorageTab()
        self.analysis_tab = AnalysisTab()
        self.chapters_tab = ChaptersTab()
        self.merge_tab = MergeBehaviorTab()
        self.logging_tab = LoggingTab()

        self.tabs.addTab(self._wrap(self.storage_tab), "Storage")
        self.tabs.addTab(self._wrap(self.analysis_tab), "Analysis")
        self.tabs.addTab(self._wrap(self.chapters_tab), "Chapters")
        self.tabs.addTab(self._wrap(self.merge_tab), "Merge Behavior")
        self.tabs.addTab(self._wrap(self.logging_tab), "Logging")

        main = QVBoxLayout(self)
        main.addWidget(self.tabs)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)

        self.load_settings()

    def _wrap(self, widget):
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(widget)
        return sa

    def load_settings(self):
        self.storage_tab.load_from(self.config)
        self.analysis_tab.load_from(self.config)
        self.chapters_tab.load_from(self.config)
        self.merge_tab.load_from(self.config)
        self.logging_tab.load_from(self.config)

    def accept(self):
        self.storage_tab.store_into(self.config)
        self.analysis_tab.store_into(self.config)
        self.chapters_tab.store_into(self.config)
        self.merge_tab.store_into(self.config)
        self.logging_tab.store_into(self.config)
        super().accept()
