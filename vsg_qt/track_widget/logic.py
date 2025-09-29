# vsg_qt/track_widget/logic.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List, Any

class TrackWidgetLogic:
    def __init__(self, view: "TrackWidget", track_data: Dict, available_sources: List[str]):
        self.v = view
        self.track_data = track_data
        self.available_sources = available_sources
        self.init_ui_state()

    def init_ui_state(self):
        """Sets the initial state of the UI based on track data."""
        is_subs = self.track_data.get('type') == 'subtitles'
        is_external = self.track_data.get('source') == 'External'

        # Show/hide controls based on track type
        self.v.cb_forced.setVisible(is_subs)
        self.v.style_editor_btn.setVisible(is_subs)

        # Initialize hidden controls from track_data if available (e.g., from a copied layout)
        if is_subs:
            current_value = self.track_data.get('size_multiplier')
            self.v.size_multiplier.setValue(1.0 if current_value is None else float(current_value))
            self.v.cb_ocr.setChecked(self.track_data.get('perform_ocr', False))
            self.v.cb_cleanup.setChecked(self.track_data.get('perform_ocr_cleanup', False))
            self.v.cb_convert.setChecked(self.track_data.get('convert_to_ass', False))
            self.v.cb_rescale.setChecked(self.track_data.get('rescale', False))

        # Show the sync dropdown ONLY for external subtitles
        self.v.sync_to_label.setVisible(is_subs and is_external)
        self.v.sync_to_combo.setVisible(is_subs and is_external)
        if is_subs and is_external:
            self.populate_sync_sources()

    def populate_sync_sources(self):
        """Populates the dropdown with sources to sync an external sub against."""
        combo = self.v.sync_to_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Default (Source 1)", "Source 1")
        for src in self.available_sources:
             if src != "Source 1":
                combo.addItem(src, src)
        saved_sync_source = self.track_data.get('sync_to')
        if saved_sync_source:
            index = combo.findData(saved_sync_source)
            if index != -1:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def refresh_summary(self):
        """Updates the main summary label and the inline options summary."""
        track_type = self.track_data.get('type', 'U')
        track_id = self.track_data.get('id', 0)
        source = self.track_data.get('source')
        description = self.track_data.get('description', 'N/A')

        summary_text = f"[{source}] [{track_type[0].upper()}-{track_id}] {description}"
        self.v.summary_label.setText(summary_text)

        # Update the inline summary (which uses the 'source_label' widget for display)
        parts = []
        # --- FIX: Only check subtitle-specific options for subtitles ---
        if self.track_data.get('type') == 'subtitles':
            if self.v.cb_ocr.isChecked(): parts.append("OCR")
            if self.v.cb_cleanup.isChecked(): parts.append("Cleanup")
            if self.v.cb_convert.isChecked(): parts.append("→ASS")
            if self.v.cb_rescale.isChecked(): parts.append("Rescale")

            size_mult = self.v.size_multiplier.value()
            if abs(size_mult - 1.0) > 1e-6:
                parts.append(f"{size_mult:.2f}x Size")
        # --- END FIX ---

        if not parts:
            self.v.source_label.setText("")
        else:
            self.v.source_label.setText(f"└ ⚙ {', '.join(parts)}")

    def refresh_badges(self):
        """Updates the badge label based on the current settings."""
        badges = []
        if self.v.cb_default.isChecked():
            badges.append("Default")
        if self.track_data.get('type') == 'subtitles' and self.v.cb_forced.isChecked():
            badges.append("Forced")
        if self.track_data.get('user_modified_path'):
            badges.append("Edited")
        elif self.track_data.get('style_patch'):
            badges.append("Styled")

        self.v.badge_label.setText(" | ".join(badges))
        self.v.badge_label.setVisible(bool(badges))

    def get_config(self) -> Dict[str, Any]:
        """Returns the current configuration from the widget's controls."""
        is_subs = self.track_data.get('type') == 'subtitles'

        size_mult_value = 1.0
        if is_subs:
            try:
                size_mult_value = float(self.v.size_multiplier.value())
                if size_mult_value <= 0 or size_mult_value > 10:
                    size_mult_value = 1.0
            except (ValueError, TypeError):
                size_mult_value = 1.0

        config = {
            "is_default": self.v.cb_default.isChecked(),
            "apply_track_name": self.v.cb_name.isChecked(),
            "is_forced_display": self.v.cb_forced.isChecked() if is_subs else False,
            "perform_ocr": self.v.cb_ocr.isChecked() if is_subs else False,
            "perform_ocr_cleanup": self.v.cb_cleanup.isChecked() if is_subs else False,
            "convert_to_ass": self.v.cb_convert.isChecked() if is_subs else False,
            "rescale": self.v.cb_rescale.isChecked() if is_subs else False,
            "size_multiplier": size_mult_value,
            "style_patch": self.track_data.get('style_patch'),
            "user_modified_path": self.track_data.get('user_modified_path'),
            "sync_to": self.v.sync_to_combo.currentData() if (is_subs and self.v.sync_to_combo.isVisible()) else None
        }

        return config
