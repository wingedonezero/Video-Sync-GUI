from __future__ import annotations

from enum import Enum
from typing import Any

from vsg_core.models.enums import AnalysisMode, SnapMode

# Map of field names to their enum types for automatic conversion
_ENUM_FIELDS: dict[str, type[Enum]] = {
    "analysis_mode": AnalysisMode,
    "snap_mode": SnapMode,
}


class OptionsLogic:
    """
    Thin logic/helper for OptionsDialog to read/write a dict-like config.
    The dialog exposes a 'sections' dict mapping section names -> dict of widgets.
    """

    def __init__(self, dialog):
        self.dlg = dialog

    # --- load/save over a flat dict or AppSettings dataclass ---
    def load_from_config(self, cfg: dict[str, Any]) -> None:
        # Handle both dict and AppSettings dataclass
        is_dataclass = hasattr(cfg, "__dataclass_fields__")
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                if is_dataclass:
                    value = getattr(cfg, key, None)
                else:
                    value = cfg.get(key)
                self._set_widget_val(widget, value)

    def save_to_config(self, cfg: dict[str, Any]) -> None:
        # Handle both dict and AppSettings dataclass
        is_dataclass = hasattr(cfg, "__dataclass_fields__")
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                value = self._get_widget_val(widget)

                # Convert string values to enum for enum fields
                if key in _ENUM_FIELDS and isinstance(value, str):
                    enum_type = _ENUM_FIELDS[key]
                    try:
                        value = enum_type(value)
                    except ValueError:
                        pass  # Keep string value if conversion fails

                if is_dataclass:
                    # Only set if the attribute exists on the dataclass
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
                else:
                    cfg[key] = value

    # --- widget helpers copied from previous OptionsDialog (kept behavior) ---
    def _get_widget_val(self, widget):
        from PySide6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QDoubleSpinBox,
            QLineEdit,
            QSpinBox,
            QWidget,
        )

        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QComboBox):
            # If the combo has custom data stored, return that instead of text
            data = widget.currentData()
            if data is not None:
                return data
            return widget.currentText()
        # Composite [QWidget] with (QLineEdit, QPushButton) for file/dir pickers
        if (
            isinstance(widget, QWidget)
            and widget.layout()
            and isinstance(widget.layout().itemAt(0).widget(), QLineEdit)
        ):
            return widget.layout().itemAt(0).widget().text()
        return widget.text() if isinstance(widget, QLineEdit) else None

    def _set_widget_val(self, widget, value) -> None:
        from PySide6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QDoubleSpinBox,
            QLineEdit,
            QSpinBox,
            QWidget,
        )

        # Skip if value is None (config key doesn't exist yet)
        if value is None:
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QSpinBox):
            # QSpinBox requires int - coerce if value is string
            try:
                widget.setValue(
                    int(float(value)) if isinstance(value, str) else int(value)
                )
            except (ValueError, TypeError):
                pass  # Keep current value if coercion fails
        elif isinstance(widget, QDoubleSpinBox):
            # QDoubleSpinBox requires float - coerce if value is string
            try:
                widget.setValue(float(value) if isinstance(value, str) else value)
            except (ValueError, TypeError):
                pass  # Keep current value if coercion fails
        elif isinstance(widget, QComboBox):
            # Handle Enum values by using their .value property
            search_value = value.value if hasattr(value, "value") else value
            # Try to find item by data first (for combos with stored integer/data values)
            index = widget.findData(search_value)
            if index >= 0:
                widget.setCurrentIndex(index)
            else:
                # Fallback to text matching for combos without custom data
                widget.setCurrentText(str(search_value))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif (
            isinstance(widget, QWidget)
            and widget.layout()
            and isinstance(widget.layout().itemAt(0).widget(), QLineEdit)
        ):
            widget.layout().itemAt(0).widget().setText(str(value))
