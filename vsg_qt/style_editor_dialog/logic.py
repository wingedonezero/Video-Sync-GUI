# vsg_qt/style_editor_dialog/logic.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re
from typing import Dict, Any, Optional
from PySide6.QtWidgets import QColorDialog, QMenu, QInputDialog, QMessageBox
from PySide6.QtGui import QColor, QAction

from vsg_core.subtitles.style_engine import StyleEngine
from vsg_core.favorite_colors import FavoriteColorsManager
from vsg_core.config import AppConfig
from vsg_qt.resample_dialog import ResampleDialog

class StyleEditorLogic:
    def __init__(self, view: "StyleEditorDialog", subtitle_path: str,
                 existing_font_replacements: Optional[Dict] = None,
                 fonts_dir: Optional[str] = None):
        self.v = view
        self.engine = StyleEngine(subtitle_path)
        self.fonts_dir = fonts_dir  # Directory for preview fonts
        self.current_style_name = None
        self.tag_pattern = re.compile(r'{[^}]+}')
        # Store snapshots of styles as they are selected for editing
        self.edit_snapshots = {}
        # Store the final generated patch of changes
        self.generated_patch = {}
        # Initialize favorite colors manager
        config = AppConfig()
        self.favorites_manager = FavoriteColorsManager(config.get_config_dir())
        # Font replacements tracking - load existing if provided
        self.font_replacements: Dict = existing_font_replacements.copy() if existing_font_replacements else {}

    def open_resample_dialog(self):
        if not self.engine.data:
            return

        current_x = int(self.engine.info.get('PlayResX', 0))
        current_y = int(self.engine.info.get('PlayResY', 0))
        video_path = self.v.player_thread.video_path

        dialog = ResampleDialog(current_x, current_y, video_path, self.v)
        if dialog.exec():
            new_x, new_y = dialog.get_resolution()
            self.engine.set_info('PlayResX', str(new_x))
            self.engine.set_info('PlayResY', str(new_y))
            self.engine.save()
            self.v.player_thread.reload_subtitle_track(self.engine.get_preview_path())

    def populate_initial_state(self):
        self.populate_styles_dropdown()
        self.populate_events_table()

    def populate_styles_dropdown(self):
        self.v.style_selector.blockSignals(True)
        self.v.style_selector.clear()
        style_names = self.engine.get_style_names()
        if style_names:
            self.v.style_selector.addItems(style_names)
            if not self.current_style_name or self.current_style_name not in style_names:
                self.current_style_name = style_names[0]
            self.v.style_selector.setCurrentText(self.current_style_name)
            self.load_style_attributes(self.current_style_name)
        self.v.style_selector.blockSignals(False)

    def populate_events_table(self):
        self.v.events_table.setRowCount(0)
        events = self.engine.get_events()
        self.v.events_table.setRowCount(len(events))
        for row, event in enumerate(events):
            plain_text = event.get("plaintext", "").replace("\\N", " ")
            self._set_table_item(row, 0, str(event["line_num"]))
            self._set_table_item(row, 1, str(event["start"]))
            self._set_table_item(row, 2, str(event["end"]))
            self._set_table_item(row, 3, event["style"])
            self._set_table_item(row, 4, plain_text)
        self.v.events_table.resizeColumnsToContents()

    def _set_table_item(self, row, col, text):
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        self.v.events_table.setItem(row, col, item)

    def on_style_selected(self, style_name: str):
        if style_name:
            self.current_style_name = style_name
            self.load_style_attributes(style_name)

    def on_event_selected(self):
        selected_items = self.v.events_table.selectedItems()
        if not selected_items:
            self.v.tag_warning_label.setVisible(False)
            return
        row = selected_items[0].row()
        style_item = self.v.events_table.item(row, 3)
        if style_item:
            style_name = style_item.text()
            if self.v.style_selector.currentText() != style_name:
                self.v.style_selector.setCurrentText(style_name)
        try:
            line_num_str = self.v.events_table.item(row, 0).text()
            line_num = int(line_num_str)
            # Access events through SubtitleData
            if self.engine.data and line_num - 1 < len(self.engine.data.events):
                event_obj = self.engine.data.events[line_num - 1]
                if self.tag_pattern.search(event_obj.text):
                    self.v.tag_warning_label.setText("⚠️ Note: This line contains override tags. Edits to the global style may not be visible.")
                    self.v.tag_warning_label.setVisible(True)
                else:
                    self.v.tag_warning_label.setVisible(False)
            else:
                self.v.tag_warning_label.setVisible(False)
        except (ValueError, IndexError):
            self.v.tag_warning_label.setVisible(False)

    def load_style_attributes(self, style_name: str):
        attrs = self.engine.get_style_attributes(style_name)
        if not attrs: return

        # NEW: Take a snapshot of the original attributes before loading them into the UI
        if style_name not in self.edit_snapshots:
            self.edit_snapshots[style_name] = attrs

        for widget in self.v.style_widgets.values(): widget.blockSignals(True)
        self.v.style_widgets['fontname'].setText(attrs.get("fontname", ""))
        self.v.style_widgets['fontsize'].setValue(attrs.get("fontsize", 0))
        self._set_color_button_style(self.v.style_widgets['primarycolor'], attrs.get("primarycolor", "#FFFFFFFF"))
        self._set_color_button_style(self.v.style_widgets['secondarycolor'], attrs.get("secondarycolor", "#FFFFFFFF"))
        self._set_color_button_style(self.v.style_widgets['outlinecolor'], attrs.get("outlinecolor", "#FF000000"))
        self._set_color_button_style(self.v.style_widgets['backcolor'], attrs.get("backcolor", "#FF000000"))
        self.v.style_widgets['bold'].setChecked(bool(attrs.get("bold", False)))
        self.v.style_widgets['italic'].setChecked(bool(attrs.get("italic", False)))
        self.v.style_widgets['underline'].setChecked(bool(attrs.get("underline", False)))
        self.v.style_widgets['strikeout'].setChecked(bool(attrs.get("strikeout", False)))
        self.v.style_widgets['outline'].setValue(attrs.get("outline", 0))
        self.v.style_widgets['shadow'].setValue(attrs.get("shadow", 0))
        self.v.style_widgets['marginl'].setValue(attrs.get("marginl", 0))
        self.v.style_widgets['marginr'].setValue(attrs.get("marginr", 0))
        self.v.style_widgets['marginv'].setValue(attrs.get("marginv", 0))
        for widget in self.v.style_widgets.values(): widget.blockSignals(False)

    def generate_patch(self):
        """Compares edited styles against snapshots and creates a patch of changes."""
        patch = {}
        # Use _get_current_ui_attrs once, as it reads the state of the currently displayed style
        current_attrs = self._get_current_ui_attrs()

        for style_name, original_attrs in self.edit_snapshots.items():
            changes = {}
            # If this is the style currently displayed, compare against the live UI values
            if style_name == self.current_style_name:
                attrs_to_compare = current_attrs
            else:
                # For other styles that were snapshotted but not currently displayed,
                # their "current" state is their original state unless we assume edits.
                # The safest assumption is that only the visible style is edited.
                # However, our logic updates the engine on-the-fly, so let's get the most recent state.
                attrs_to_compare = self.engine.get_style_attributes(style_name)

            for key, original_value in original_attrs.items():
                current_value = attrs_to_compare.get(key)
                # Ensure we handle floating point comparisons gracefully
                is_different = False
                if isinstance(original_value, float):
                    if not isinstance(current_value, float) or abs(current_value - original_value) > 1e-6:
                        is_different = True
                elif current_value != original_value:
                    is_different = True

                if is_different:
                    changes[key] = current_value

            if changes:
                patch[style_name] = changes
        self.generated_patch = patch

    def _get_current_ui_attrs(self):
        """Helper to get all style attributes from the current UI state."""
        w = self.v.style_widgets
        return {
            "fontname": w['fontname'].text(), "fontsize": w['fontsize'].value(),
            "primarycolor": w['primarycolor'].palette().button().color().name(QColor.HexArgb),
            "secondarycolor": w['secondarycolor'].palette().button().color().name(QColor.HexArgb),
            "outlinecolor": w['outlinecolor'].palette().button().color().name(QColor.HexArgb),
            "backcolor": w['backcolor'].palette().button().color().name(QColor.HexArgb),
            "bold": w['bold'].isChecked(), "italic": w['italic'].isChecked(),
            "underline": w['underline'].isChecked(), "strikeout": w['strikeout'].isChecked(),
            "outline": w['outline'].value(), "shadow": w['shadow'].value(),
            "marginl": w['marginl'].value(), "marginr": w['marginr'].value(),
            "marginv": w['marginv'].value(),
        }

    def strip_tags_from_selected(self):
        selected_rows = {it.row() for it in self.v.events_table.selectedItems()}
        if not selected_rows or not self.engine.data:
            return
        style_tags_pattern = re.compile(r'\\(c|1c|2c|3c|4c|fn|fs|bord|shad|b|i|u|s)[^\\}]+')
        modified = False
        for row in selected_rows:
            try:
                line_num = int(self.v.events_table.item(row, 0).text())
                if line_num - 1 < len(self.engine.data.events):
                    event_obj = self.engine.data.events[line_num - 1]
                    if self.tag_pattern.search(event_obj.text):
                        cleaned_text = style_tags_pattern.sub('', event_obj.text)
                        cleaned_text = cleaned_text.replace('{}', '')
                        if cleaned_text != event_obj.text:
                            event_obj.text = cleaned_text
                            modified = True
            except (ValueError, IndexError):
                continue
        if modified:
            self.engine.save()
            self.populate_events_table()
            self.v.player_thread.reload_subtitle_track(self.engine.get_preview_path())
            self.on_event_selected()

    def pick_color(self, button, attribute_name):
        initial_color = button.palette().button().color()
        color = QColorDialog.getColor(initial_color, self.v, "Select Color")
        if color.isValid():
            self._set_color_button_style(button, color.name(QColor.HexArgb))
            self.update_current_style()

    def _set_color_button_style(self, button, hex_color_str):
        button.setStyleSheet(f"background-color: {QColor(hex_color_str).name()};")

    def update_current_style(self):
        if not self.current_style_name:
            return
        current_attrs = self._get_current_ui_attrs()
        self.engine.update_style_attributes(self.current_style_name, current_attrs)
        self.engine.save()
        self.v.player_thread.reload_subtitle_track(self.engine.get_preview_path())

    def reset_current_style(self):
        if not self.current_style_name:
            return
        # Use the engine's built-in reset functionality
        self.engine.reset_style(self.current_style_name)
        self.load_style_attributes(self.current_style_name)
        self.engine.save()
        self.v.player_thread.reload_subtitle_track(self.engine.get_preview_path())

    # --- Favorite Colors Methods ---

    def save_color_to_favorites(self, button, attribute_name: str):
        """Save the current color from a button to favorites."""
        current_color = button.palette().button().color()
        hex_color = current_color.name(QColor.HexArgb)

        # Prompt for a name
        name, ok = QInputDialog.getText(
            self.v,
            "Save to Favorites",
            "Enter a name for this color:",
            text=attribute_name.replace('color', '').title()
        )

        if ok and name:
            self.favorites_manager.add(name.strip(), hex_color)
            # Update the star button to show it's saved (filled star)
            if attribute_name in self.v.favorite_save_btns:
                self.v.favorite_save_btns[attribute_name].setText("\u2605")  # Filled star

    def show_favorites_menu(self, button, color_button, attribute_name: str):
        """Show a menu of favorite colors to apply."""
        menu = QMenu(self.v)

        favorites = self.favorites_manager.get_all()

        if not favorites:
            no_favorites_action = menu.addAction("No favorites saved")
            no_favorites_action.setEnabled(False)
        else:
            for fav in favorites:
                # Create action with color swatch in text
                hex_display = fav['hex']
                if len(hex_display) == 9:  # #AARRGGBB
                    hex_display = '#' + hex_display[3:]  # Show as #RRGGBB

                action = menu.addAction(f"{fav['name']} ({hex_display})")
                action.setData(fav['hex'])

                # Set icon color (create a colored icon would be nice but text works)
                color = QColor(fav['hex'])
                # We can't easily add colored icons without more complex code,
                # so the menu text will suffice

        menu.addSeparator()
        manage_action = menu.addAction("Manage Favorites...")

        # Show the menu at the button
        action = menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

        if action:
            if action == manage_action:
                self.open_favorites_manager()
            elif action.data():
                self.apply_favorite_color(color_button, attribute_name, action.data())

    def apply_favorite_color(self, button, attribute_name: str, hex_color: str):
        """Apply a favorite color to a color button."""
        self._set_color_button_style(button, hex_color)
        self.update_current_style()

    def open_favorites_manager(self):
        """Open the Favorites Manager dialog."""
        from vsg_qt.favorites_dialog import FavoritesManagerDialog
        dialog = FavoritesManagerDialog(self.favorites_manager, self.v)
        dialog.exec()

    # --- Font Manager Methods ---

    def open_font_manager(self):
        """Open the Font Manager dialog."""
        import shutil
        from vsg_qt.font_manager_dialog import FontManagerDialog
        from vsg_core.font_manager import apply_font_replacements_to_subtitle

        # Store original font names before any changes
        original_replacements = self.font_replacements.copy()

        dialog = FontManagerDialog(
            str(self.engine.path),
            current_replacements=self.font_replacements,
            parent=self.v
        )
        if dialog.exec():
            new_replacements = dialog.get_replacements()

            # Check if replacements changed
            if new_replacements != original_replacements:
                # Find removed replacements (need to revert these styles)
                removed_styles = set(original_replacements.keys()) - set(new_replacements.keys())

                # Revert removed replacements by applying reverse mapping
                if removed_styles:
                    revert_replacements = {}
                    for style_name in removed_styles:
                        # The style currently has new_font_name, change it back to original_font
                        repl_data = original_replacements[style_name]
                        original_font = repl_data.get('original_font')
                        new_font = repl_data.get('new_font_name')
                        if original_font and new_font:
                            revert_replacements[style_name] = {
                                'original_font': new_font,  # Current font in file
                                'new_font_name': original_font,  # Restore to original
                                'font_file_path': None
                            }

                    if revert_replacements:
                        try:
                            apply_font_replacements_to_subtitle(str(self.engine.path), revert_replacements)
                        except Exception as e:
                            QMessageBox.warning(
                                self.v,
                                "Font Revert",
                                f"Could not revert font changes: {e}"
                            )

                self.font_replacements = new_replacements

                # Apply new replacements if any
                if new_replacements:
                    try:
                        # Copy only the specific replacement font files to fonts_dir for preview
                        if self.fonts_dir:
                            fonts_dir_path = Path(self.fonts_dir)
                            for repl_data in new_replacements.values():
                                font_file = repl_data.get('font_file_path')
                                if font_file:
                                    src = Path(font_file)
                                    if src.exists():
                                        dst = fonts_dir_path / src.name
                                        if not dst.exists():
                                            shutil.copy2(src, dst)

                        apply_font_replacements_to_subtitle(
                            str(self.engine.path),
                            new_replacements
                        )
                    except Exception as e:
                        QMessageBox.warning(
                            self.v,
                            "Font Preview",
                            f"Could not apply font changes to preview: {e}"
                        )

                # Reload the subtitle in the player to show changes
                self.v.player_thread.reload_subtitle_track(self.engine.get_preview_path())
                # Also reload the engine so UI reflects changes
                self.engine = StyleEngine(str(self.engine.path))
                self.populate_initial_state()

    def get_font_replacements(self) -> Dict[str, Any]:
        """Get the configured font replacements."""
        return self.font_replacements
