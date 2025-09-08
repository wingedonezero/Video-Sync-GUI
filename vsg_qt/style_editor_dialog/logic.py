# vsg_qt/style_editor_dialog/logic.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from copy import deepcopy
import re
from PySide6.QtWidgets import QColorDialog
from PySide6.QtGui import QColor

from vsg_core.subtitles.style_engine import StyleEngine
from vsg_qt.resample_dialog import ResampleDialog

class StyleEditorLogic:
    def __init__(self, view: "StyleEditorDialog", subtitle_path: str):
        self.v = view
        self.engine = StyleEngine(subtitle_path)
        self.current_style_name = None
        self.original_styles = deepcopy(self.engine.subs.styles) if self.engine.subs else {}
        self.tag_pattern = re.compile(r'{[^}]+}')
        # NEW: Store snapshots of styles as they are selected for editing
        self.edit_snapshots = {}
        # NEW: Store the final generated patch of changes
        self.generated_patch = {}

    def open_resample_dialog(self):
        if not self.engine.subs:
            return

        current_x = int(self.engine.subs.info.get('PlayResX', 0))
        current_y = int(self.engine.subs.info.get('PlayResY', 0))
        video_path = self.v.player_thread.video_path

        dialog = ResampleDialog(current_x, current_y, video_path, self.v)
        if dialog.exec():
            new_x, new_y = dialog.get_resolution()
            self.engine.subs.info['PlayResX'] = str(new_x)
            self.engine.subs.info['PlayResY'] = str(new_y)
            self.engine.save()
            self.v.player_thread.reload_subtitle_track()

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
            event_obj = self.engine.subs.events[line_num - 1]
            if self.tag_pattern.search(event_obj.text):
                self.v.tag_warning_label.setText("⚠️ Note: This line contains override tags. Edits to the global style may not be visible.")
                self.v.tag_warning_label.setVisible(True)
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
        if not selected_rows: return
        style_tags_pattern = re.compile(r'\\(c|1c|2c|3c|4c|fn|fs|bord|shad|b|i|u|s)[^\\}]+')
        modified = False
        for row in selected_rows:
            try:
                line_num = int(self.v.events_table.item(row, 0).text())
                event_obj = self.engine.subs.events[line_num - 1]
                if self.tag_pattern.search(event_obj.text):
                    cleaned_text = style_tags_pattern.sub('', event_obj.text)
                    cleaned_text = cleaned_text.replace('{}', '')
                    if cleaned_text != event_obj.text:
                        event_obj.text = cleaned_text
                        modified = True
            except (ValueError, IndexError): continue
        if modified:
            self.engine.save()
            self.populate_events_table()
            self.v.player_thread.reload_subtitle_track()
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
        if not self.current_style_name: return
        current_attrs = self._get_current_ui_attrs()
        self.engine.update_style_attributes(self.current_style_name, current_attrs)
        self.engine.save()
        self.v.player_thread.reload_subtitle_track()

    def reset_current_style(self):
        if not self.current_style_name: return
        original_style = self.original_styles.get(self.current_style_name)
        if not original_style: return
        self.engine.subs.styles[self.current_style_name] = deepcopy(original_style)
        self.load_style_attributes(self.current_style_name)
        self.engine.save()
        self.v.player_thread.reload_subtitle_track()
