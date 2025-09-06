# -*- coding: utf-8 -*-
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QFileDialog
from PySide6.QtCore import Signal

class InputPanel(QWidget):
    """
    Reference / Secondary / Tertiary inputs + Settings button row.
    Emits:
      - settingsRequested()
    """
    settingsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        # top row: settings
        row = QHBoxLayout()
        self.btn_settings = QPushButton('Settings…')
        self.btn_settings.clicked.connect(lambda: self.settingsRequested.emit())
        row.addWidget(self.btn_settings)
        row.addStretch(1)
        root.addLayout(row)

        # inputs
        grp = QGroupBox('Input Files (File or Directory)')
        gl = QVBoxLayout(grp)
        self.ref_input = QLineEdit()
        self.sec_input = QLineEdit()
        self.ter_input = QLineEdit()
        gl.addLayout(self._file_row('Reference:', self.ref_input, self._browse_ref))
        gl.addLayout(self._file_row('Secondary:', self.sec_input, self._browse_sec))
        gl.addLayout(self._file_row('Tertiary:', self.ter_input, self._browse_ter))
        root.addWidget(grp)

    # --- public API ---
    def get_paths(self) -> tuple[str, str | None, str | None]:
        return self.ref_input.text().strip(), self.sec_input.text().strip() or None, self.ter_input.text().strip() or None

    def set_paths(self, ref: str = '', sec: str = '', ter: str = ''):
        self.ref_input.setText(ref or '')
        self.sec_input.setText(sec or '')
        self.ter_input.setText(ter or '')

    # --- helpers ---
    def _file_row(self, label_text: str, line_edit: QLineEdit, slot):
        from PySide6.QtWidgets import QHBoxLayout, QLabel
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text), 1)
        layout.addWidget(line_edit, 8)
        btn = QPushButton('Browse…'); btn.clicked.connect(slot)
        layout.addWidget(btn, 1)
        return layout

    def _browse_ref(self): self._browse_any(self.ref_input, "Select Reference File or Directory")
    def _browse_sec(self): self._browse_any(self.sec_input, "Select Secondary File or Directory")
    def _browse_ter(self): self._browse_any(self.ter_input, "Select Tertiary File or Directory")

    def _browse_any(self, line_edit: QLineEdit, caption: str):
        dlg = QFileDialog(self, caption)
        dlg.setFileMode(QFileDialog.AnyFile)
        current = line_edit.text().strip()
        if current:
            try:
                dlg.setDirectory(str(Path(current).parent))
            except Exception:
                pass
        if dlg.exec():
            line_edit.setText(dlg.selectedFiles()[0])
