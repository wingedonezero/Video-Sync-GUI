# vsg_qt/add_job_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
    QLineEdit, QLabel, QMessageBox, QFileDialog, QScrollArea, QWidget,
    QComboBox, QGroupBox
)

from vsg_core.job_discovery import discover_jobs

class SourceInputWidget(QWidget):
    """A self-contained widget for a single source input row that handles drag-and-drop."""
    def __init__(self, source_num: int, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QHBoxLayout(self)

        label_text = f"Source {source_num} (Reference):" if source_num == 1 else f"Source {source_num}:"
        label = QLabel(label_text)
        self.line_edit = QLineEdit()
        browse_btn = QPushButton("Browse…")

        browse_btn.clicked.connect(self._browse_for_path)

        layout.addWidget(label, 1)
        layout.addWidget(self.line_edit, 4)
        layout.addWidget(browse_btn)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # Use the path of the first dropped file
            path = event.mimeData().urls()[0].toLocalFile()
            self.line_edit.setText(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _browse_for_path(self):
        dialog = QFileDialog(self, "Select Source")
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if dialog.exec():
            self.line_edit.setText(dialog.selectedFiles()[0])

    def text(self) -> str:
        return self.line_edit.text()


class SubtitleFolderWidget(QWidget):
    """A widget for configuring subtitle folder path and sync source."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)

        # Path selection row
        path_layout = QHBoxLayout()
        path_label = QLabel("Subtitle Folder:")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Optional: Folder containing subtitle subfolders")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_for_folder)

        path_layout.addWidget(path_label, 1)
        path_layout.addWidget(self.path_edit, 4)
        path_layout.addWidget(browse_btn)

        # Sync source row
        sync_layout = QHBoxLayout()
        sync_label = QLabel("Sync to Source:")
        self.sync_combo = QComboBox()
        sync_layout.addWidget(sync_label, 1)
        sync_layout.addWidget(self.sync_combo, 4)
        sync_layout.addStretch()  # Align with browse button above

        layout.addLayout(path_layout)
        layout.addLayout(sync_layout)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            self.path_edit.setText(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _browse_for_folder(self):
        dialog = QFileDialog(self, "Select Subtitle Folder")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        if dialog.exec():
            self.path_edit.setText(dialog.selectedFiles()[0])

    def get_path(self) -> str:
        return self.path_edit.text().strip()

    def get_sync_source(self) -> str:
        return self.sync_combo.currentData() or "Source 1"

    def update_available_sources(self, source_count: int):
        """Updates the sync source dropdown based on number of configured sources."""
        self.sync_combo.blockSignals(True)
        current_selection = self.sync_combo.currentData()
        self.sync_combo.clear()

        # Add available sources
        for i in range(1, source_count + 1):
            source_key = f"Source {i}"
            display_text = f"Source {i}" if i > 1 else "Source 1 (Reference)"
            self.sync_combo.addItem(display_text, source_key)

        # Restore previous selection if still valid
        if current_selection:
            index = self.sync_combo.findData(current_selection)
            if index != -1:
                self.sync_combo.setCurrentIndex(index)

        self.sync_combo.blockSignals(False)


class AddJobDialog(QDialog):
    """
    A dialog for dynamically adding sources to discover jobs.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Job(s) to Queue")
        self.setMinimumSize(700, 300)

        self.discovered_jobs: List[Dict] = []
        self.source_widgets: List[SourceInputWidget] = []
        self._build_ui()

        # Start with 2 sources by default
        self.add_source_input()
        self.add_source_input()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        container = QWidget()
        self.inputs_layout = QVBoxLayout(container)
        scroll_area.setWidget(container)

        layout.addWidget(scroll_area)

        add_source_btn = QPushButton("Add Another Source")
        add_source_btn.clicked.connect(self.add_source_input)
        layout.addWidget(add_source_btn)

        # Subtitle folder configuration section
        subtitle_group = QGroupBox("Subtitle Folder (Optional)")
        subtitle_layout = QVBoxLayout()
        self.subtitle_folder_widget = SubtitleFolderWidget()
        subtitle_layout.addWidget(self.subtitle_folder_widget)
        subtitle_group.setLayout(subtitle_layout)
        layout.addWidget(subtitle_group)

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        ok_button.setText("Find & Add Jobs")

        ok_button.clicked.connect(self.find_and_accept)
        dialog_btns.rejected.connect(self.reject)

        layout.addWidget(dialog_btns)

    def add_source_input(self):
        """Adds a new SourceInputWidget to the dialog."""
        source_num = len(self.source_widgets) + 1
        source_widget = SourceInputWidget(source_num)
        self.source_widgets.append(source_widget)
        self.inputs_layout.addWidget(source_widget)

        # Update subtitle folder widget's available sources
        self.subtitle_folder_widget.update_available_sources(source_num)

    def populate_sources_from_paths(self, paths: List[str]):
        """Pre-fills the source inputs from a list of paths."""
        # Clear any default inputs
        while self.inputs_layout.count():
            child = self.inputs_layout.takeAt(0)
            if child and child.widget():
                child.widget().deleteLater()
        self.source_widgets.clear()

        # Add an input for each dropped path
        for path in paths:
            self.add_source_input()
            self.source_widgets[-1].line_edit.setText(path)

        # Ensure at least two inputs exist if user drops only one file
        if len(self.source_widgets) < 2:
            self.add_source_input()

    def find_and_accept(self):
        """Discover jobs from paths and accept the dialog if any are found."""
        sources: Dict[str, str] = {}
        for i, source_widget in enumerate(self.source_widgets):
            path = source_widget.text().strip()
            if path:
                sources[f"Source {i+1}"] = path

        if "Source 1" not in sources:
            QMessageBox.warning(self, "Input Required", "Source 1 (Reference) cannot be empty.")
            return

        # Get subtitle folder configuration
        subtitle_folder_path = self.subtitle_folder_widget.get_path()
        subtitle_folder_sync_source = self.subtitle_folder_widget.get_sync_source()

        try:
            self.discovered_jobs = discover_jobs(
                sources,
                subtitle_folder_path=subtitle_folder_path if subtitle_folder_path else None,
                subtitle_folder_sync_source=subtitle_folder_sync_source
            )
            if not self.discovered_jobs:
                QMessageBox.information(self, "No Jobs Found", "No matching jobs could be discovered from the provided paths.")
                return

            self.accept()
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.critical(self, "Error Discovering Jobs", str(e))

    def get_discovered_jobs(self) -> List[Dict]:
        return self.discovered_jobs
