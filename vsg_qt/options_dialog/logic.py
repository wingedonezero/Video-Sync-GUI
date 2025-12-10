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
                self._set_widget_val(widget, cfg.get(key))

    def save_to_config(self, cfg: Dict[str, Any]):
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                cfg[key] = self._get_widget_val(widget)

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
        # Skip if value is None (config key doesn't exist yet)
        if value is None:
            return
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
