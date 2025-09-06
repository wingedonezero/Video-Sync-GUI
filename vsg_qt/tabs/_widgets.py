# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QCheckBox,
    QComboBox, QSpinBox, QDoubleSpinBox
)

def dir_input(initial: str = "") -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
    le = QLineEdit(initial)
    btn = QPushButton("Browse…")
    h.addWidget(le); h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_dir(le))
    return w

def file_input(initial: str = "") -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
    le = QLineEdit(initial)
    btn = QPushButton("Browse…")
    h.addWidget(le); h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_file(le))
    return w

def _browse_dir(le: QLineEdit):
    path = QFileDialog.getExistingDirectory(le.parentWidget(), "Select Directory", le.text())
    if path: le.setText(path)

def _browse_file(le: QLineEdit):
    path, _ = QFileDialog.getOpenFileName(le.parentWidget(), "Select File", le.text())
    if path: le.setText(path)

# ---------- generic get/set for controls we use across tabs ----------
def get_val(widget):
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    # composite dir/file input -> first child is QLineEdit
    if isinstance(widget, QWidget) and widget.layout() and widget.layout().itemAt(0) and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
        return widget.layout().itemAt(0).widget().text()
    if isinstance(widget, QLineEdit):
        return widget.text()
    return None

def set_val(widget, value):
    if isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value))
    elif isinstance(widget, QDoubleSpinBox):
        widget.setValue(float(value))
    elif isinstance(widget, QComboBox):
        widget.setCurrentText(str(value))
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value))
    elif isinstance(widget, QWidget) and widget.layout() and widget.layout().itemAt(0) and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
        widget.layout().itemAt(0).widget().setText(str(value))
