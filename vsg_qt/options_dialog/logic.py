from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.models.settings import AppSettings

logger = logging.getLogger(__name__)


class OptionsLogic:
    """
    Thin logic/helper for OptionsDialog to read/write AppSettings.
    The dialog exposes a 'sections' dict mapping section names -> dict of widgets.
    """

    def __init__(self, dialog):
        self.dlg = dialog

    # --- load/save over AppSettings (always attribute access) ---
    def load_from_config(self, cfg: AppSettings) -> None:
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                value = getattr(cfg, key, None)
                if value is None and not hasattr(cfg, key):
                    warnings.warn(
                        f"Options widget '{key}' has no matching AppSettings field",
                        UserWarning,
                        stacklevel=2,
                    )
                self._set_widget_val(widget, value)

    def save_to_config(self, cfg: AppSettings) -> list[str]:
        """Save widget values to config.  Returns list of rejected keys."""
        from pydantic import ValidationError

        rejected: list[str] = []
        for section in self.dlg.sections.values():
            for key, widget in section.items():
                value = self._get_widget_val(widget)
                if hasattr(cfg, key):
                    try:
                        setattr(cfg, key, value)
                    except (ValidationError, ValueError, TypeError) as exc:
                        rejected.append(key)
                        warnings.warn(
                            f"Setting '{key}' rejected value {value!r}: {exc}",
                            UserWarning,
                            stacklevel=2,
                        )
                else:
                    rejected.append(key)
                    warnings.warn(
                        f"Options widget '{key}' has no matching AppSettings field — value not saved",
                        UserWarning,
                        stacklevel=2,
                    )
        return rejected

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
            and widget.layout().itemAt(0)
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
            # Try to find item by data first (for combos with stored integer/data values)
            index = widget.findData(value)
            if index >= 0:
                widget.setCurrentIndex(index)
            else:
                # Fallback to text matching for combos without custom data
                widget.setCurrentText(str(value))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif (
            isinstance(widget, QWidget)
            and widget.layout()
            and isinstance(widget.layout().itemAt(0).widget(), QLineEdit)
        ):
            widget.layout().itemAt(0).widget().setText(str(value))
