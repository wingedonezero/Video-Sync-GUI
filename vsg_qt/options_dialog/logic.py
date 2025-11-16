from __future__ import annotations
from typing import Dict, Any

class OptionsLogic:
    """
    Thin logic/helper for OptionsDialog to read/write a dict-like config.
    The dialog exposes a 'sections' dict mapping section names -> dict of widgets.
    """

    def __init__(self, dialog):
        self.dlg = dialog

    # --- load/save over a flat dict (same keys as before) ---
    def load_from_config(self, cfg: Dict[str, Any]):
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                value = cfg.get(key)
                # Special handling for OCR OEM mode (convert int to text)
                if key == 'ocr_tesseract_oem' and isinstance(value, int):
                    oem_map = {0: 'Legacy', 1: 'LSTM (Recommended)', 2: 'Legacy+LSTM', 3: 'Default'}
                    value = oem_map.get(value, 'LSTM (Recommended)')  # Default to LSTM
                self._set_widget_val(widget, value)

    def save_to_config(self, cfg: Dict[str, Any]):
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                value = self._get_widget_val(widget)
                # Special handling for OCR OEM mode (convert text to int)
                if key == 'ocr_tesseract_oem':
                    oem_map = {'Legacy': 0, 'LSTM (Recommended)': 1, 'Legacy+LSTM': 2, 'Default': 3}
                    value = oem_map.get(value, 1)  # Default to LSTM
                cfg[key] = value

    # --- widget helpers copied from previous OptionsDialog (kept behavior) ---
    def _get_widget_val(self, widget):
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QWidget, QLineEdit
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        # Composite [QWidget] with (QLineEdit, QPushButton) for file/dir pickers
        if isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            return widget.layout().itemAt(0).widget().text()
        return widget.text() if isinstance(widget, QLineEdit) else None

    def _set_widget_val(self, widget, value):
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QWidget, QLineEdit
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(value)
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(value))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            widget.layout().itemAt(0).widget().setText(str(value))
