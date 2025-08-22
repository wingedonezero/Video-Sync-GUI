
from __future__ import annotations
from PySide6 import QtWidgets, QtGui
from typing import Optional
from vsg.settings_io import CONFIG

def _set_layout_spacing(widget: QtWidgets.QWidget, spacing: int):
    lay = widget.layout()
    if lay:
        lay.setSpacing(spacing)
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left(), spacing, m.right(), spacing)
    for child in widget.findChildren(QtWidgets.QWidget):
        _set_layout_spacing(child, spacing)

def _set_input_heights(widget: QtWidgets.QWidget, px: int):
    for cls in (QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QSpinBox,
                QtWidgets.QDoubleSpinBox, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit,
                QtWidgets.QPushButton, QtWidgets.QCheckBox):
        for w in widget.findChildren(cls):
            w.setMinimumHeight(px)
            if isinstance(w, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
                w.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)

def apply_appearance(app: QtWidgets.QApplication, root: QtWidgets.QWidget, cfg: Optional[dict]=None):
    cfg = cfg or CONFIG
    font = app.font()
    if cfg.get("ui_font_family"):
        font.setFamilies([cfg["ui_font_family"]])
    font.setPointSize(int(cfg.get("ui_font_size_pt", 10)))
    app.setFont(font)
    _set_layout_spacing(root, int(cfg.get("row_spacing_px", 8)))
    _set_input_heights(root, int(cfg.get("input_height_px", 32)))
