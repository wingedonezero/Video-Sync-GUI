# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import QWidget, QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog

class InputsPanel(QGroupBox):
    """
    Three path inputs (file or directory) with Browse… buttons:
      Reference, Secondary, Tertiary
    """
    def __init__(self, *, title: str = "Input Files (File or Directory)", parent: QWidget | None = None):
        super().__init__(title, parent)
        self.ref_input = QLineEdit()
        self.sec_input = QLineEdit()
        self.ter_input = QLineEdit()

        layout = QVBoxLayout(self)
        layout.addLayout(self._row("Reference:", self.ref_input, self._browse_ref))
        layout.addLayout(self._row("Secondary:", self.sec_input, self._browse_sec))
        layout.addLayout(self._row("Tertiary:", self.ter_input, self._browse_ter))

        self._last_dir_hint: str | None = None

    def _row(self, label_text: str, edit: QLineEdit, slot):
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text), 1)
        row.addWidget(edit, 8)
        b = QPushButton("Browse…")
        b.clicked.connect(slot)
        row.addWidget(b, 1)
        return row

    # ---- browsing ----
    def _browse_ref(self): self._browse_for_path(self.ref_input, "Select Reference File or Directory")
    def _browse_sec(self): self._browse_for_path(self.sec_input, "Select Secondary File or Directory")
    def _browse_ter(self): self._browse_for_path(self.ter_input, "Select Tertiary File or Directory")

    def _browse_for_path(self, edit: QLineEdit, caption: str):
        dialog = QFileDialog(self, caption)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if self._last_dir_hint:
            dialog.setDirectory(self._last_dir_hint)
        if dialog.exec():
            selected = dialog.selectedFiles()[0]
            edit.setText(selected)
            try:
                self._last_dir_hint = str(Path(selected).parent)
            except Exception:
                pass

    # ---- getters/setters (for MainWindow glue) ----
    def get_values(self) -> tuple[str, str | None, str | None]:
        r = self.ref_input.text().strip()
        s = self.sec_input.text().strip() or None
        t = self.ter_input.text().strip() or None
        return (r, s, t)

    def set_values(self, ref: str, sec: str, ter: str):
        self.ref_input.setText(ref or "")
        self.sec_input.setText(sec or "")
        self.ter_input.setText(ter or "")
