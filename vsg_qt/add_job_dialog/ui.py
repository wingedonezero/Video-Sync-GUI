# vsg_qt/add_job_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
    QLineEdit, QLabel, QMessageBox, QFileDialog, QScrollArea, QWidget
)

from vsg_core.job_discovery import discover_jobs

class AddJobDialog(QDialog):
    """
    A dialog for dynamically adding sources to discover jobs
    and add them to the main Job Queue.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Job(s) to Queue")
        self.setMinimumSize(700, 300)

        self.discovered_jobs: List[Dict] = []
        self.source_inputs: List[QLineEdit] = []
        self._build_ui()
        # Start with 2 sources by default for a new job
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

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        ok_button.setText("Find & Add Jobs")

        ok_button.clicked.connect(self.find_and_accept)
        dialog_btns.rejected.connect(self.reject)

        layout.addWidget(dialog_btns)

    def add_source_input(self):
        """Dynamically adds a new source input row to the dialog."""
        source_num = len(self.source_inputs) + 1
        label_text = f"Source {source_num} (Reference):" if source_num == 1 else f"Source {source_num}:"

        line_edit = QLineEdit()
        self.source_inputs.append(line_edit)

        row = self._create_file_input(label_text, line_edit)
        self.inputs_layout.addLayout(row)

    def _create_file_input(self, label_text: str, line_edit: QLineEdit) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text), 1)
        layout.addWidget(line_edit, 4)
        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(lambda: self._browse_for_path(line_edit, "Select Source"))
        layout.addWidget(browse_btn)
        return layout

    def _browse_for_path(self, line_edit: QLineEdit, caption: str):
        dialog = QFileDialog(self, caption)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if dialog.exec():
            line_edit.setText(dialog.selectedFiles()[0])

    def find_and_accept(self):
        """Discover jobs from paths and accept the dialog if any are found."""
        sources: Dict[str, str] = {}
        for i, line_edit in enumerate(self.source_inputs):
            path = line_edit.text().strip()
            if path:
                sources[f"Source {i+1}"] = path

        if "Source 1" not in sources:
            QMessageBox.warning(self, "Input Required", "Source 1 (Reference) cannot be empty.")
            return

        try:
            self.discovered_jobs = discover_jobs(sources)
            if not self.discovered_jobs:
                QMessageBox.information(self, "No Jobs Found", "No matching jobs could be discovered from the provided paths.")
                return

            self.accept()
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.critical(self, "Error Discovering Jobs", str(e))

    def get_discovered_jobs(self) -> List[Dict]:
        return self.discovered_jobs
