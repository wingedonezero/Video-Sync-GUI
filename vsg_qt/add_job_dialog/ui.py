# vsg_qt/add_job_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
    QLineEdit, QLabel, QGroupBox, QMessageBox, QFileDialog
)

from vsg_core.job_discovery import discover_jobs

class AddJobDialog(QDialog):
    """
    A dialog for selecting source directories/files to discover jobs
    and add them to the main Job Queue.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Job(s) to Queue")
        self.setMinimumSize(600, 200)

        self.discovered_jobs: List[Dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        inputs_group = QGroupBox('Select Sources (Files or Directories)')
        inputs_layout = QVBoxLayout(inputs_group)

        self.ref_input = QLineEdit()
        self.sec_input = QLineEdit()
        self.ter_input = QLineEdit()

        inputs_layout.addLayout(self._create_file_input('Source 1 (Reference):', self.ref_input))
        inputs_layout.addLayout(self._create_file_input('Source 2:', self.sec_input))
        inputs_layout.addLayout(self._create_file_input('Source 3:', self.ter_input))

        layout.addWidget(inputs_group)

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        ok_button.setText("Find & Add Jobs")

        ok_button.clicked.connect(self.find_and_accept)
        dialog_btns.rejected.connect(self.reject)

        layout.addWidget(dialog_btns)

    def _create_file_input(self, label_text: str, line_edit: QLineEdit):
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
        ref_path = self.ref_input.text().strip()
        sec_path = self.sec_input.text().strip() or None
        ter_path = self.ter_input.text().strip() or None

        if not ref_path:
            QMessageBox.warning(self, "Input Required", "Source 1 (Reference) cannot be empty.")
            return

        try:
            self.discovered_jobs = discover_jobs(ref_path, sec_path, ter_path)
            if not self.discovered_jobs:
                QMessageBox.information(self, "No Jobs Found", "No matching jobs could be discovered from the provided paths.")
                return

            self.accept()
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.critical(self, "Error Discovering Jobs", str(e))

    def get_discovered_jobs(self) -> List[Dict]:
        return self.discovered_jobs
