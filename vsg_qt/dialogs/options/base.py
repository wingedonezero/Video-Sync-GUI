# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog

def make_dir_input() -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    lay.addWidget(le); lay.addWidget(btn)
    def browse():
        path = QFileDialog.getExistingDirectory(w, "Select Directory", le.text())
        if path: le.setText(path)
    btn.clicked.connect(browse)
    w._le = le
    return w

def make_file_input() -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    lay.addWidget(le); lay.addWidget(btn)
    def browse():
        path, _ = QFileDialog.getOpenFileName(w, "Select File", le.text())
        if path: le.setText(path)
    btn.clicked.connect(browse)
    w._le = le
    return w

def get_text(container: QWidget) -> str:
    return getattr(container, "_le", None).text() if hasattr(container, "_le") else ""

def set_text(container: QWidget, value: str):
    if hasattr(container, "_le") and container._le:
        container._le.setText(str(value or ""))
