# vsg_qt/subtitle_editor/tabs/styles_tab.py
"""
Styles tab for subtitle editor.

Provides style editing functionality migrated from StyleEditorDialog.
"""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QToolButton,
    QWidget,
)

from .base_tab import BaseTab


class StylesTab(BaseTab):
    """
    Tab for editing subtitle styles.

    Features:
    - Style selector dropdown
    - All style attributes (font, colors, margins, etc.)
    - Color favorites integration
    - Reset to original values
    """

    TAB_NAME = "Styles"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_style_name: str | None = None
        self._edit_snapshots: dict[str, dict[str, Any]] = {}
        self._favorites_manager = None
        self._style_widgets: dict[str, QWidget] = {}
        self._favorite_save_btns: dict[str, QPushButton] = {}
        self._favorite_load_btns: dict[str, QToolButton] = {}

        self._tag_pattern = re.compile(r"{[^}]+}")

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the styles tab UI."""
        layout = self.content_layout

        # Style selector row
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Style:"))

        self._style_selector = QComboBox()
        self._style_selector.currentTextChanged.connect(self._on_style_selected)
        selector_layout.addWidget(self._style_selector, 1)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setToolTip("Reset style to original values")
        self._reset_btn.clicked.connect(self._reset_current_style)
        selector_layout.addWidget(self._reset_btn)

        layout.addLayout(selector_layout)

        # Tools row (Resample, Strip Tags)
        tools_layout = QHBoxLayout()

        self._resample_btn = QPushButton("Resample...")
        self._resample_btn.setToolTip("Rescale subtitle to different resolution")
        self._resample_btn.clicked.connect(self._open_resample_dialog)
        tools_layout.addWidget(self._resample_btn)

        self._strip_tags_btn = QPushButton("Strip Tags")
        self._strip_tags_btn.setToolTip("Remove inline style tags from selected lines")
        self._strip_tags_btn.clicked.connect(self._strip_tags_from_selected)
        tools_layout.addWidget(self._strip_tags_btn)

        tools_layout.addStretch()
        layout.addLayout(tools_layout)

        # Tag warning label
        self._tag_warning = QLabel()
        self._tag_warning.setStyleSheet("color: #E0A800; font-weight: bold;")
        self._tag_warning.setWordWrap(True)
        self._tag_warning.setVisible(False)
        layout.addWidget(self._tag_warning)

        # Font group
        font_group = QGroupBox("Font")
        font_layout = QFormLayout(font_group)

        self._style_widgets["fontname"] = QLineEdit()
        self._style_widgets["fontname"].editingFinished.connect(self._update_style)
        font_layout.addRow("Name:", self._style_widgets["fontname"])

        self._style_widgets["fontsize"] = QDoubleSpinBox()
        self._style_widgets["fontsize"].setRange(1, 500)
        self._style_widgets["fontsize"].valueChanged.connect(
            lambda _: self._update_style()
        )
        font_layout.addRow("Size:", self._style_widgets["fontsize"])

        layout.addWidget(font_group)

        # Colors group
        colors_group = QGroupBox("Colors")
        colors_layout = QFormLayout(colors_group)

        for color_key, label in [
            ("primarycolor", "Primary:"),
            ("secondarycolor", "Secondary:"),
            ("outlinecolor", "Outline:"),
            ("backcolor", "Shadow:"),
        ]:
            btn = QPushButton("Pick...")
            btn.clicked.connect(lambda checked, k=color_key: self._pick_color(k))
            self._style_widgets[color_key] = btn

            # Favorite buttons
            save_btn = QPushButton("\u2606")  # Star outline
            save_btn.setFixedSize(28, 28)
            save_btn.setToolTip("Save to favorites")
            save_btn.clicked.connect(
                lambda checked, k=color_key: self._save_to_favorites(k)
            )
            self._favorite_save_btns[color_key] = save_btn

            load_btn = QToolButton()
            load_btn.setText("\u25bc")  # Down triangle
            load_btn.setFixedSize(28, 28)
            load_btn.setToolTip("Load from favorites")
            load_btn.setPopupMode(QToolButton.InstantPopup)
            load_btn.clicked.connect(
                lambda checked, k=color_key: self._show_favorites_menu(k)
            )
            self._favorite_load_btns[color_key] = load_btn

            row = QHBoxLayout()
            row.addWidget(btn, 1)
            row.addWidget(save_btn)
            row.addWidget(load_btn)
            colors_layout.addRow(label, row)

        layout.addWidget(colors_group)

        # Text style group
        text_group = QGroupBox("Text Style")
        text_layout = QFormLayout(text_group)

        for key in ["bold", "italic", "underline", "strikeout"]:
            cb = QCheckBox()
            cb.stateChanged.connect(lambda _: self._update_style())
            self._style_widgets[key] = cb
            text_layout.addRow(f"{key.title()}:", cb)

        layout.addWidget(text_group)

        # Border group
        border_group = QGroupBox("Border")
        border_layout = QFormLayout(border_group)

        self._style_widgets["outline"] = QDoubleSpinBox()
        self._style_widgets["outline"].setRange(0, 20)
        self._style_widgets["outline"].valueChanged.connect(
            lambda _: self._update_style()
        )
        border_layout.addRow("Outline:", self._style_widgets["outline"])

        self._style_widgets["shadow"] = QDoubleSpinBox()
        self._style_widgets["shadow"].setRange(0, 20)
        self._style_widgets["shadow"].valueChanged.connect(
            lambda _: self._update_style()
        )
        border_layout.addRow("Shadow:", self._style_widgets["shadow"])

        layout.addWidget(border_group)

        # Margins group
        margins_group = QGroupBox("Margins")
        margins_layout = QFormLayout(margins_group)

        for key, label in [
            ("marginl", "Left:"),
            ("marginr", "Right:"),
            ("marginv", "Vertical:"),
        ]:
            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.valueChanged.connect(lambda _: self._update_style())
            self._style_widgets[key] = spin
            margins_layout.addRow(label, spin)

        layout.addWidget(margins_group)

        layout.addStretch()

    def _on_state_set(self) -> None:
        """Initialize from state when set."""
        if not self._state:
            return

        # Initialize favorites manager
        from vsg_core.config import AppConfig
        from vsg_core.favorite_colors import FavoriteColorsManager

        config = AppConfig()
        self._favorites_manager = FavoriteColorsManager(config.get_config_dir())

        # Populate styles dropdown
        self._populate_styles()

        # Connect to state signals
        self._state.style_changed.connect(self._on_style_changed_externally)

    def _populate_styles(self) -> None:
        """Populate the styles dropdown from state."""
        if not self._state:
            return

        self._style_selector.blockSignals(True)
        self._style_selector.clear()

        style_names = self._state.style_names
        if style_names:
            self._style_selector.addItems(style_names)
            if (
                not self._current_style_name
                or self._current_style_name not in style_names
            ):
                self._current_style_name = style_names[0]
            self._style_selector.setCurrentText(self._current_style_name)
            self._load_style_attributes(self._current_style_name)

        self._style_selector.blockSignals(False)

    def _on_style_selected(self, style_name: str) -> None:
        """Handle style selection change."""
        if style_name and self._state:
            self._current_style_name = style_name
            self._state.set_current_style(style_name)
            self._load_style_attributes(style_name)

    def _load_style_attributes(self, style_name: str) -> None:
        """Load style attributes into the UI."""
        if not self._state or style_name not in self._state.styles:
            return

        style = self._state.styles[style_name]

        # Convert style to UI-friendly dict (ASS -> Qt format)
        from vsg_core.subtitles.style_engine import ass_color_to_qt

        attrs = {
            "fontname": style.fontname,
            "fontsize": style.fontsize,
            "primarycolor": ass_color_to_qt(style.primary_color),
            "secondarycolor": ass_color_to_qt(style.secondary_color),
            "outlinecolor": ass_color_to_qt(style.outline_color),
            "backcolor": ass_color_to_qt(style.back_color),
            "bold": style.bold != 0,  # Convert -1/0 to bool
            "italic": style.italic != 0,
            "underline": style.underline != 0,
            "strikeout": style.strike_out != 0,
            "outline": style.outline,
            "shadow": style.shadow,
            "marginl": style.margin_l,
            "marginr": style.margin_r,
            "marginv": style.margin_v,
        }

        # Store snapshot for reset
        if style_name not in self._edit_snapshots:
            self._edit_snapshots[style_name] = attrs.copy()

        # Block signals during load
        for widget in self._style_widgets.values():
            widget.blockSignals(True)

        self._style_widgets["fontname"].setText(attrs.get("fontname", ""))
        self._style_widgets["fontsize"].setValue(attrs.get("fontsize", 0))

        # Colors (now in Qt format)
        self._set_color_button(
            self._style_widgets["primarycolor"], attrs.get("primarycolor", "#FFFFFFFF")
        )
        self._set_color_button(
            self._style_widgets["secondarycolor"],
            attrs.get("secondarycolor", "#FFFFFFFF"),
        )
        self._set_color_button(
            self._style_widgets["outlinecolor"], attrs.get("outlinecolor", "#FF000000")
        )
        self._set_color_button(
            self._style_widgets["backcolor"], attrs.get("backcolor", "#FF000000")
        )

        # Text style (now bool)
        self._style_widgets["bold"].setChecked(attrs.get("bold", False))
        self._style_widgets["italic"].setChecked(attrs.get("italic", False))
        self._style_widgets["underline"].setChecked(attrs.get("underline", False))
        self._style_widgets["strikeout"].setChecked(attrs.get("strikeout", False))

        # Border
        self._style_widgets["outline"].setValue(attrs.get("outline", 0))
        self._style_widgets["shadow"].setValue(attrs.get("shadow", 0))

        # Margins
        self._style_widgets["marginl"].setValue(attrs.get("marginl", 0))
        self._style_widgets["marginr"].setValue(attrs.get("marginr", 0))
        self._style_widgets["marginv"].setValue(attrs.get("marginv", 0))

        for widget in self._style_widgets.values():
            widget.blockSignals(False)

    def _set_color_button(self, button: QPushButton, hex_color: str) -> None:
        """Set color button background from hex color."""
        color = QColor(hex_color)
        button.setStyleSheet(f"background-color: {color.name()};")
        # Store the color as a property so we can read it back
        button.setProperty("hex_color", hex_color)

    def _get_color_from_button(self, button: QPushButton) -> str:
        """Get hex color from button property."""
        stored = button.property("hex_color")
        if stored:
            return stored
        # Fallback - shouldn't happen if set_color_button was called
        return "#FFFFFFFF"

    def _update_style(self) -> None:
        """Update style from UI values."""
        if not self._current_style_name or not self._state:
            return

        # Get current values from UI (in Qt format)
        attrs = self._get_ui_attrs()

        # Update style using proper conversion
        # UI uses 'primarycolor' with Qt format, style uses 'primary_color' with ASS format
        from vsg_core.subtitles.style_engine import qt_color_to_ass

        style = self._state.styles.get(self._current_style_name)
        if style:
            # Font
            style.fontname = attrs["fontname"]
            style.fontsize = float(attrs["fontsize"])

            # Colors (convert Qt #AARRGGBB to ASS &HAABBGGRR)
            style.primary_color = qt_color_to_ass(attrs["primarycolor"])
            style.secondary_color = qt_color_to_ass(attrs["secondarycolor"])
            style.outline_color = qt_color_to_ass(attrs["outlinecolor"])
            style.back_color = qt_color_to_ass(attrs["backcolor"])

            # Text style (ASS uses -1 for enabled, 0 for disabled)
            style.bold = -1 if attrs["bold"] else 0
            style.italic = -1 if attrs["italic"] else 0
            style.underline = -1 if attrs["underline"] else 0
            style.strike_out = -1 if attrs["strikeout"] else 0

            # Border
            style.outline = float(attrs["outline"])
            style.shadow = float(attrs["shadow"])

            # Margins
            style.margin_l = int(attrs["marginl"])
            style.margin_r = int(attrs["marginr"])
            style.margin_v = int(attrs["marginv"])

            # Mark modified and save preview
            self._state.mark_modified()
            self._state.save_preview()
            self._state.style_changed.emit(self._current_style_name)

    def _get_ui_attrs(self) -> dict[str, Any]:
        """Get all style attributes from UI."""
        return {
            "fontname": self._style_widgets["fontname"].text(),
            "fontsize": self._style_widgets["fontsize"].value(),
            "primarycolor": self._get_color_from_button(
                self._style_widgets["primarycolor"]
            ),
            "secondarycolor": self._get_color_from_button(
                self._style_widgets["secondarycolor"]
            ),
            "outlinecolor": self._get_color_from_button(
                self._style_widgets["outlinecolor"]
            ),
            "backcolor": self._get_color_from_button(self._style_widgets["backcolor"]),
            "bold": self._style_widgets["bold"].isChecked(),
            "italic": self._style_widgets["italic"].isChecked(),
            "underline": self._style_widgets["underline"].isChecked(),
            "strikeout": self._style_widgets["strikeout"].isChecked(),
            "outline": self._style_widgets["outline"].value(),
            "shadow": self._style_widgets["shadow"].value(),
            "marginl": self._style_widgets["marginl"].value(),
            "marginr": self._style_widgets["marginr"].value(),
            "marginv": self._style_widgets["marginv"].value(),
        }

    def _reset_current_style(self) -> None:
        """Reset current style to original values."""
        if not self._current_style_name or not self._state:
            return

        self._state.reset_style(self._current_style_name)
        self._load_style_attributes(self._current_style_name)
        self._state.save_preview()

    def _pick_color(self, color_key: str) -> None:
        """Open color picker for a color attribute."""
        button = self._style_widgets[color_key]
        # Get initial color from stored property
        stored_hex = button.property("hex_color") or "#FFFFFFFF"
        initial = QColor(stored_hex)

        color = QColorDialog.getColor(
            initial, self, "Select Color", QColorDialog.ShowAlphaChannel
        )
        if color.isValid():
            self._set_color_button(button, color.name(QColor.HexArgb))
            self._update_style()

    def _save_to_favorites(self, color_key: str) -> None:
        """Save current color to favorites."""
        if not self._favorites_manager:
            return

        button = self._style_widgets[color_key]
        hex_color = self._get_color_from_button(button)

        name, ok = QInputDialog.getText(
            self,
            "Save to Favorites",
            "Enter a name for this color:",
            text=color_key.replace("color", "").title(),
        )

        if ok and name:
            self._favorites_manager.add(name.strip(), hex_color)
            self._favorite_save_btns[color_key].setText("\u2605")  # Filled star

    def _show_favorites_menu(self, color_key: str) -> None:
        """Show favorites menu for a color button."""
        if not self._favorites_manager:
            return

        button = self._favorite_load_btns[color_key]
        menu = QMenu(self)

        favorites = self._favorites_manager.get_all()

        if not favorites:
            action = menu.addAction("No favorites saved")
            action.setEnabled(False)
        else:
            for fav in favorites:
                hex_display = fav["hex"]
                if len(hex_display) == 9:
                    hex_display = "#" + hex_display[3:]
                action = menu.addAction(f"{fav['name']} ({hex_display})")
                action.setData(fav["hex"])

        menu.addSeparator()
        manage_action = menu.addAction("Manage Favorites...")

        action = menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

        if action:
            if action == manage_action:
                self._open_favorites_manager()
            elif action.data():
                color_btn = self._style_widgets[color_key]
                self._set_color_button(color_btn, action.data())
                self._update_style()

    def _open_favorites_manager(self) -> None:
        """Open the favorites manager dialog."""
        from vsg_qt.favorites_dialog import FavoritesManagerDialog

        dialog = FavoritesManagerDialog(self._favorites_manager, self)
        dialog.exec()

    def _on_style_changed_externally(self, style_name: str) -> None:
        """Handle style change from external source."""
        if style_name == self._current_style_name:
            self._load_style_attributes(style_name)

    def on_activated(self) -> None:
        """Called when tab becomes active."""
        self._populate_styles()

    def on_event_selected(self, event_index: int) -> None:
        """Handle event selection - switch to event's style."""
        if not self._state or event_index < 0:
            return

        events = self._state.events
        if event_index >= len(events):
            return

        event = events[event_index]
        style_name = event.style

        if style_name and style_name != self._style_selector.currentText():
            self._style_selector.setCurrentText(style_name)

        # Check for override tags and update warning with strip option
        if self._tag_pattern.search(event.text):
            self._tag_warning.setText(
                "⚠️ This line contains inline style tags. Style edits may not be visible. "
                "Click 'Strip Tags' to remove them."
            )
            self._tag_warning.setVisible(True)
        else:
            self._tag_warning.setVisible(False)

    def _open_resample_dialog(self) -> None:
        """Open the resample dialog to rescale subtitle resolution."""
        if not self._state or not self._state.subtitle_data:
            return

        from vsg_qt.resample_dialog import ResampleDialog

        # Get current resolution from subtitle
        info = self._state.subtitle_data.info
        current_x = int(info.get("PlayResX", 0) or 0)
        current_y = int(info.get("PlayResY", 0) or 0)

        # Get video path for "From Video" button
        video_path = str(self._state.video_path) if self._state.video_path else ""

        dialog = ResampleDialog(current_x, current_y, video_path, self)
        if dialog.exec():
            new_x, new_y = dialog.get_resolution()

            # Apply rescale (Aegisub-style: scales all style values)
            self._state.subtitle_data.apply_rescale((new_x, new_y))

            # Mark as modified and save preview
            self._state.mark_modified()
            self._state.save_preview()

            # Refresh UI to show new style values
            self._populate_styles()

            # Notify video panel to reload subtitle
            self._state.subtitle_data_changed.emit()

    def _strip_tags_from_selected(self) -> None:
        """Strip inline style tags from selected lines."""
        if not self._state or not self._state.subtitle_data:
            return

        selected_indices = self._state.selected_indices
        if not selected_indices:
            self._tag_warning.setText(
                "No lines selected. Select lines in the Events table first."
            )
            self._tag_warning.setVisible(True)
            return

        # Pattern for style override tags (colors, font, size, border, shadow, bold, etc.)
        style_tags_pattern = re.compile(
            r"\\(c|1c|2c|3c|4c|fn|fs|bord|shad|b|i|u|s|an|pos|move|fad|fade|org|clip|frx|fry|frz|fax|fay|fscx|fscy|fsp|fe|q|r|t|p)[^\\}]*"
        )

        modified_count = 0
        events = self._state.events

        for idx in selected_indices:
            if idx < 0 or idx >= len(events):
                continue

            event = events[idx]
            original_text = event.text

            # Check if line has tags
            if not self._tag_pattern.search(original_text):
                continue

            # Remove style tags
            cleaned_text = style_tags_pattern.sub("", original_text)
            # Remove empty tag blocks {}
            cleaned_text = cleaned_text.replace("{}", "")

            if cleaned_text != original_text:
                event.text = cleaned_text
                modified_count += 1
                self._state.event_changed.emit(idx)

        if modified_count > 0:
            # Mark as modified and save preview
            self._state.mark_modified()
            self._state.save_preview()

            # Update tag warning
            self._tag_warning.setText(f"✓ Stripped tags from {modified_count} line(s).")
            self._tag_warning.setStyleSheet("color: #00AA00; font-weight: bold;")
            self._tag_warning.setVisible(True)

            # Notify subtitle data changed for video reload
            self._state.subtitle_data_changed.emit()
        else:
            self._tag_warning.setText("No lines with style tags in selection.")
            self._tag_warning.setStyleSheet("color: #E0A800; font-weight: bold;")
            self._tag_warning.setVisible(True)

    def get_result(self) -> dict:
        """Get style patch as result."""
        if not self._state:
            return {}
        return {"style_patch": self._state.generate_style_patch()}
