# vsg_qt/options_dialog/ui.py
from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QDialogButtonBox, QScrollArea, QWidget
)
from .logic import OptionsLogic
from .tabs import StorageTab, AnalysisTab, ChaptersTab, MergeBehaviorTab, LoggingTab, SubtitleCleanupTab, TimingTab

def _wrap_scroll(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    return sa

class OptionsDialog(QDialog):
    """
    Drop-in replacement preserving public API/behavior of the previous OptionsDialog.

    Usage:
        dlg = OptionsDialog(config_dict, parent)
        if dlg.exec():
            config_dict is updated in-place via dlg.accept()

    Exposes:
        - self.sections: dict[str, dict[str, QWidget]] of all keyed widgets
    """
    def __init__(self, config: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Application Settings')
        self.setMinimumSize(900, 600)
        self.config = config
        self.sections: Dict[str, Dict[str, object]] = {}

        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)

        # Instantiate tabs (each exposes .widgets: Dict[key, widget])
        self._storage_tab = StorageTab()
        self._analysis_tab = AnalysisTab()
        self._chapters_tab = ChaptersTab()
        self._merge_tab = MergeBehaviorTab()
        self._logging_tab = LoggingTab()
        self._cleanup_tab = SubtitleCleanupTab()
        self._timing_tab = TimingTab()

        # Add tabs wrapped in scroll areas
        self.tabs.addTab(_wrap_scroll(self._storage_tab), 'Storage & Tools')
        self.tabs.addTab(_wrap_scroll(self._analysis_tab), 'Analysis')
        self.tabs.addTab(_wrap_scroll(self._chapters_tab), 'Chapters')
        self.tabs.addTab(_wrap_scroll(self._timing_tab), 'Timing')
        self.tabs.addTab(_wrap_scroll(self._cleanup_tab), 'Subtitle Cleanup')
        self.tabs.addTab(_wrap_scroll(self._merge_tab), 'Merge Behavior')
        self.tabs.addTab(_wrap_scroll(self._logging_tab), 'Logging')

        # Collect widget maps by logical section name
        self.sections['storage'] = self._storage_tab.widgets
        self.sections['analysis'] = self._analysis_tab.widgets
        self.sections['chapters'] = self._chapters_tab.widgets
        self.sections['merge'] = self._merge_tab.widgets
        self.sections['logging'] = self._logging_tab.widgets
        self.sections['cleanup'] = self._cleanup_tab.widgets
        self.sections['timing'] = self._timing_tab.widgets

        # Save/Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        # Logic
        self._logic = OptionsLogic(self)
        self.load_settings()

    # --- public (kept for compatibility) ---
    def load_settings(self):
        self._logic.load_from_config(self.config.settings if hasattr(self.config, "settings") else self.config)

    def accept(self):
        cfg = self.config.settings if hasattr(self.config, "settings") else self.config
        self._logic.save_to_config(cfg)
        super().accept()
