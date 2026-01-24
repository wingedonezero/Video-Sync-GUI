# vsg_qt/generated_track_dialog/ui.py
# -*- coding: utf-8 -*-
"""
Dialog for creating generated tracks by filtering subtitle styles.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialogButtonBox, QListWidget, QListWidgetItem, QLineEdit,
    QCheckBox, QGroupBox, QRadioButton, QButtonGroup
)

from vsg_core.subtitles.data import SubtitleData


class GeneratedTrackDialog(QDialog):
    """
    Dialog for selecting which subtitle styles to include/exclude
    when creating a generated track.
    """

    def __init__(self, source_track: dict, existing_config: dict = None, parent=None):
        super().__init__(parent)
        self.source_track = source_track
        self.existing_config = existing_config  # For editing existing generated tracks
        self.filter_config = None  # Will be set if user clicks OK
        self.style_counts = {}
        self.style_checkboxes = {}

        is_editing = existing_config is not None
        self.setWindowTitle("Edit Generated Track" if is_editing else "Create Generated Track")
        self.setMinimumSize(500, 600)

        self._build_ui()
        self._load_styles()
        self._apply_existing_config()  # Apply existing settings if editing
        self._update_preview()

    def _build_ui(self):
        """Build the dialog UI."""
        layout = QVBoxLayout(self)

        # Info label
        info_text = (
            f"Create a filtered subtitle track from:\n"
            f"Source: {self.source_track.get('source', 'Unknown')}\n"
            f"Track ID: {self.source_track.get('id', 'N/A')}\n"
            f"Description: {self.source_track.get('description', 'N/A')}"
        )
        info_label = QLabel(info_text)
        info_label.setStyleSheet("font-weight: bold; padding: 10px; background-color: #f0f0f0; color: #000000;")
        layout.addWidget(info_label)

        # Filter mode selection
        mode_group = QGroupBox("Filter Mode")
        mode_layout = QVBoxLayout(mode_group)

        self.mode_button_group = QButtonGroup(self)
        self.exclude_radio = QRadioButton("Exclude selected styles (keep everything else)")
        self.include_radio = QRadioButton("Include only selected styles (remove everything else)")
        self.exclude_radio.setChecked(True)  # Default to exclude mode

        self.mode_button_group.addButton(self.exclude_radio)
        self.mode_button_group.addButton(self.include_radio)

        mode_layout.addWidget(self.exclude_radio)
        mode_layout.addWidget(self.include_radio)
        layout.addWidget(mode_group)

        # Connect mode change to preview update
        self.exclude_radio.toggled.connect(self._update_preview)

        # Style selection list
        styles_group = QGroupBox("Select Styles")
        styles_layout = QVBoxLayout(styles_group)

        help_label = QLabel("Check the styles you want to exclude/include:")
        help_label.setWordWrap(True)
        styles_layout.addWidget(help_label)

        self.styles_list = QListWidget()
        styles_layout.addWidget(self.styles_list)

        # Select All / Deselect All buttons
        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.deselect_all_btn = QPushButton("Deselect All")
        self.select_all_btn.clicked.connect(self._select_all_styles)
        self.deselect_all_btn.clicked.connect(self._deselect_all_styles)
        btn_layout.addWidget(self.select_all_btn)
        btn_layout.addWidget(self.deselect_all_btn)
        styles_layout.addLayout(btn_layout)

        layout.addWidget(styles_group)

        # Preview label
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-weight: bold; padding: 10px;")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        # Track naming
        name_group = QGroupBox("Generated Track Name")
        name_layout = QHBoxLayout(name_group)
        name_label = QLabel("Name:")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Leave empty for no custom name")

        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        layout.addWidget(name_group)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_styles(self):
        """Load available styles from the source subtitle file."""
        subtitle_path = self.source_track.get('original_path')
        if not subtitle_path:
            self.preview_label.setText("Error: No subtitle file path found")
            return

        try:
            # Get style counts from SubtitleData
            self.style_counts = SubtitleData.get_style_counts_from_file(subtitle_path)

            if not self.style_counts:
                self.preview_label.setText("⚠️ No styles found in subtitle file")
                self.preview_label.setStyleSheet("font-weight: bold; padding: 10px; color: #FFA500;")
                return

            # Add checkboxes for each style
            for style_name, count in sorted(self.style_counts.items()):
                item = QListWidgetItem(self.styles_list)
                checkbox = QCheckBox(f"{style_name} ({count} events)")
                checkbox.stateChanged.connect(self._update_preview)
                self.styles_list.addItem(item)
                self.styles_list.setItemWidget(item, checkbox)
                self.style_checkboxes[style_name] = checkbox

        except Exception as e:
            self.preview_label.setText(f"❌ Error loading styles:\n{str(e)}")
            self.preview_label.setStyleSheet("font-weight: bold; padding: 10px; color: #FF0000;")

    def _apply_existing_config(self):
        """Apply existing configuration when editing a generated track."""
        if not self.existing_config:
            return

        # Set the filter mode
        mode = self.existing_config.get('mode', 'exclude')
        if mode == 'include':
            self.include_radio.setChecked(True)
        else:
            self.exclude_radio.setChecked(True)

        # Check the previously selected styles
        selected_styles = self.existing_config.get('styles', [])
        for style_name in selected_styles:
            if style_name in self.style_checkboxes:
                self.style_checkboxes[style_name].setChecked(True)

        # Set the track name
        track_name = self.existing_config.get('name', '')
        if track_name:
            self.name_edit.setText(track_name)

    def _select_all_styles(self):
        """Check all style checkboxes."""
        for checkbox in self.style_checkboxes.values():
            checkbox.setChecked(True)

    def _deselect_all_styles(self):
        """Uncheck all style checkboxes."""
        for checkbox in self.style_checkboxes.values():
            checkbox.setChecked(False)

    def _get_selected_styles(self):
        """Get list of currently selected style names."""
        return [
            style_name for style_name, checkbox in self.style_checkboxes.items()
            if checkbox.isChecked()
        ]

    def _update_preview(self):
        """Update the preview label showing what will be filtered."""
        selected_styles = self._get_selected_styles()
        mode = 'exclude' if self.exclude_radio.isChecked() else 'include'

        if not selected_styles:
            self.preview_label.setText("⚠️ No styles selected - nothing will be filtered")
            self.preview_label.setStyleSheet("font-weight: bold; padding: 10px; color: #FFA500;")
            return

        total_events = sum(self.style_counts.values())
        selected_events = sum(self.style_counts.get(s, 0) for s in selected_styles)

        if mode == 'exclude':
            kept_events = total_events - selected_events
            removed_events = selected_events
            preview_text = (
                f"✓ Will keep {kept_events} events, "
                f"exclude {removed_events} events from styles: {', '.join(selected_styles)}"
            )
        else:  # include
            kept_events = selected_events
            removed_events = total_events - selected_events
            preview_text = (
                f"✓ Will keep {kept_events} events from styles: {', '.join(selected_styles)}, "
                f"exclude {removed_events} other events"
            )

        self.preview_label.setText(preview_text)
        self.preview_label.setStyleSheet("font-weight: bold; padding: 10px; color: #00AA00;")

    def _on_accept(self):
        """Validate and save the configuration when user clicks OK."""
        selected_styles = self._get_selected_styles()

        if not selected_styles:
            self.preview_label.setText("⚠️ Please select at least one style")
            self.preview_label.setStyleSheet("font-weight: bold; padding: 10px; color: #FF0000;")
            return

        track_name = self.name_edit.text().strip()

        mode = 'exclude' if self.exclude_radio.isChecked() else 'include'

        # Store both the selected filter styles AND the complete original style list
        # The complete list is used for validation when pasting layouts
        self.filter_config = {
            'mode': mode,
            'styles': selected_styles,
            'name': track_name,
            'original_style_list': sorted(self.style_counts.keys())  # Complete list for exact matching
        }

        self.accept()

    def get_filter_config(self):
        """
        Get the filter configuration if dialog was accepted.

        Returns:
            dict or None: {
                'mode': 'exclude'/'include',
                'styles': [...],  # Selected styles to filter
                'name': '...',
                'original_style_list': [...],  # Complete style list from source
                'skip_frame_validation': bool  # Skip duration-align frame validation
            } or None
        """
        return self.filter_config
