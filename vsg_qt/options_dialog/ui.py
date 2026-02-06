# vsg_qt/options_dialog/ui.py
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .logic import OptionsLogic
from .tabs import (
    AnalysisTab,
    ChaptersTab,
    LoggingTab,
    MergeBehaviorTab,
    OCRTab,
    SteppingTab,
    StorageTab,
    SubtitleSyncTab,
)


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

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Settings")
        self.setMinimumSize(900, 600)
        self.config = config
        self.sections: dict[str, dict[str, object]] = {}

        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)

        # Instantiate tabs (each exposes .widgets: Dict[key, widget])
        self._storage_tab = StorageTab()
        self._analysis_tab = AnalysisTab()
        self._stepping_tab = SteppingTab()
        self._subtitle_sync_tab = SubtitleSyncTab()
        self._chapters_tab = ChaptersTab()
        self._ocr_tab = OCRTab()
        self._merge_tab = MergeBehaviorTab()
        self._logging_tab = LoggingTab()

        # Add tabs wrapped in scroll areas
        self.tabs.addTab(_wrap_scroll(self._storage_tab), "Storage & Tools")
        self.tabs.addTab(_wrap_scroll(self._analysis_tab), "Analysis")
        self.tabs.addTab(_wrap_scroll(self._stepping_tab), "Stepping Correction")
        self.tabs.addTab(_wrap_scroll(self._subtitle_sync_tab), "Subtitles")
        self.tabs.addTab(_wrap_scroll(self._chapters_tab), "Chapters")
        self.tabs.addTab(_wrap_scroll(self._ocr_tab), "OCR")
        self.tabs.addTab(_wrap_scroll(self._merge_tab), "Merge Behavior")
        self.tabs.addTab(_wrap_scroll(self._logging_tab), "Logging")

        # Collect widget maps by logical section name
        self.sections["storage"] = self._storage_tab.widgets
        self.sections["analysis"] = self._analysis_tab.widgets
        self.sections["stepping"] = self._stepping_tab.widgets
        self.sections["subtitle_sync"] = self._subtitle_sync_tab.widgets
        self.sections["chapters"] = self._chapters_tab.widgets
        self.sections["ocr"] = self._ocr_tab.widgets
        self.sections["merge"] = self._merge_tab.widgets
        self.sections["logging"] = self._logging_tab.widgets

        # Save/Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        # Logic
        self._logic = OptionsLogic(self)
        self.load_settings()

        # Connect storage tab maintenance button
        self._storage_tab.remove_invalid_btn.clicked.connect(
            self._on_remove_invalid_config
        )

    def _on_remove_invalid_config(self) -> None:
        """Handle remove invalid config entries button click."""
        if not hasattr(self.config, "get_orphaned_keys"):
            QMessageBox.warning(
                self, "Not Supported", "Config object doesn't support orphan detection."
            )
            return

        orphaned = self.config.get_orphaned_keys()
        if not orphaned:
            QMessageBox.information(
                self,
                "Config Clean",
                "No invalid config entries found.\nYour settings.json is clean!",
            )
            return

        # Show confirmation with list of keys to be removed
        keys_list = "\n".join(f"  - {k}" for k in sorted(orphaned))
        reply = QMessageBox.question(
            self,
            "Remove Invalid Entries?",
            f"Found {len(orphaned)} invalid/orphaned config entries:\n\n{keys_list}\n\n"
            "These are old settings no longer used by the application.\n"
            "Remove them from settings.json?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            removed = self.config.remove_orphaned_keys()
            QMessageBox.information(
                self,
                "Cleanup Complete",
                f"Removed {len(removed)} invalid entries from settings.json.",
            )

    # --- public (kept for compatibility) ---
    def load_settings(self) -> None:
        self._logic.load_from_config(self.config.settings)
        # Initialize font size preview after settings are loaded
        self._ocr_tab.initialize_font_preview()

    def accept(self) -> None:
        self._logic.save_to_config(self.config.settings)
        super().accept()
