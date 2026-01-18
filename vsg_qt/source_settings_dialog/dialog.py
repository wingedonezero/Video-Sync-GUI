# vsg_qt/source_settings_dialog/dialog.py
# -*- coding: utf-8 -*-
"""Dialog for configuring per-source correlation settings."""
from __future__ import annotations
from typing import Dict, List, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QCheckBox, QDialogButtonBox, QLabel
)
from PySide6.QtCore import Qt


class SourceSettingsDialog(QDialog):
    """
    Dialog for configuring per-source correlation settings.

    Allows setting:
    - Correlation source track: Which track from this source to use for correlation
    - Use source separation: Whether to apply source separation for this source

    Note: Source 1 track selection is configured globally via Analysis Language settings,
    not per-source. To change which Source 1 track is used, adjust the global settings.
    """

    def __init__(
        self,
        source_key: str,
        source_audio_tracks: List[Dict[str, Any]],
        source1_audio_tracks: List[Dict[str, Any]],  # Kept for backwards compatibility
        current_settings: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        """
        Initialize the source settings dialog.

        Args:
            source_key: The source being configured (e.g., "Source 2")
            source_audio_tracks: List of audio track info dicts from this source
            source1_audio_tracks: (Unused, kept for compatibility)
            current_settings: Current settings for this source (if any)
            parent: Parent widget
        """
        super().__init__(parent)
        self.source_key = source_key
        self.source_tracks = source_audio_tracks
        self.current_settings = current_settings or {}

        self.setWindowTitle(f"{source_key} Correlation Settings")
        self.setMinimumWidth(500)
        self.setModal(True)

        self._init_ui()
        self._apply_current_settings()

    def _init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)

        # --- Source Track Selection Section ---
        source_track_group = QGroupBox(f"{self.source_key} Audio Track")
        source_track_layout = QVBoxLayout(source_track_group)

        # Explanation label
        source_explanation = QLabel(
            f"Select which audio track from {self.source_key} to use for correlation.\n"
            "'Auto (Language Fallback)' uses the global Analysis Language setting."
        )
        source_explanation.setWordWrap(True)
        source_explanation.setStyleSheet("color: #666; font-size: 11px;")
        source_track_layout.addWidget(source_explanation)

        # Track dropdown
        source_form = QFormLayout()
        self.source_track_combo = QComboBox()
        self._populate_source_track_combo()
        source_form.addRow(f"Use {self.source_key} Track:", self.source_track_combo)
        source_track_layout.addLayout(source_form)

        layout.addWidget(source_track_group)

        # --- Source Separation Section ---
        separation_group = QGroupBox("Source Separation")
        separation_layout = QVBoxLayout(separation_group)

        self.use_separation_cb = QCheckBox("Use Source Separation for this source")
        self.use_separation_cb.setToolTip(
            "When enabled, applies source separation to both Source 1 and this source\n"
            "during correlation. Uses the separation mode and model configured in Settings.\n\n"
            "Use this when the audio contains music or effects that interfere with correlation\n"
            "(e.g., WEB-DL with no clean audio source)."
        )
        separation_layout.addWidget(self.use_separation_cb)

        separation_note = QLabel(
            "Note: Requires Source Separation Mode to be configured in Settings > Analysis."
        )
        separation_note.setWordWrap(True)
        separation_note.setStyleSheet("color: #888; font-size: 10px;")
        separation_layout.addWidget(separation_note)

        layout.addWidget(separation_group)

        # --- Buttons ---
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._reset_to_defaults)
        layout.addWidget(buttons)

    def _populate_source_track_combo(self):
        """Populate the dropdown with this source's audio tracks."""
        self.source_track_combo.clear()

        # Add "Auto" option first
        self.source_track_combo.addItem("Auto (Language Fallback)", None)

        # Add each audio track from this source
        # Note: get_track_info_for_dialog() returns flattened structure
        for i, track in enumerate(self.source_tracks):
            description = track.get('description', '')
            lang = track.get('lang', 'und')
            name = track.get('name', '')
            codec = track.get('codec_id', 'unknown')
            channels = track.get('audio_channels', '')

            # Build display string
            if description:
                display_text = f"Track {i}: {description}"
            else:
                parts = [f"Track {i}"]
                if lang and lang != 'und':
                    parts.append(f"[{lang.upper()}]")
                if name:
                    parts.append(f'"{name}"')
                if channels:
                    parts.append(f"({channels}ch)")
                if codec:
                    codec_short = codec.replace('A_', '').split('/')[0]
                    parts.append(f"- {codec_short}")
                display_text = " ".join(parts)

            self.source_track_combo.addItem(display_text, i)

    def _apply_current_settings(self):
        """Apply current settings to the UI controls."""
        # Source track
        source_track = self.current_settings.get('correlation_source_track')
        if source_track is not None:
            for i in range(self.source_track_combo.count()):
                if self.source_track_combo.itemData(i) == source_track:
                    self.source_track_combo.setCurrentIndex(i)
                    break
        else:
            self.source_track_combo.setCurrentIndex(0)  # Auto

        # Source separation
        use_sep = self.current_settings.get('use_source_separation', False)
        self.use_separation_cb.setChecked(use_sep)

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        self.source_track_combo.setCurrentIndex(0)  # Auto
        self.use_separation_cb.setChecked(False)

    def get_settings(self) -> Dict[str, Any]:
        """
        Get the configured settings.

        Returns:
            Dict with:
            - 'correlation_source_track': int or None (Source 2/3 track index, None = auto)
            - 'use_source_separation': bool
        """
        return {
            'correlation_source_track': self.source_track_combo.currentData(),
            'use_source_separation': self.use_separation_cb.isChecked()
        }

    def has_non_default_settings(self) -> bool:
        """Check if any non-default settings are configured."""
        settings = self.get_settings()
        return (
            settings['correlation_source_track'] is not None or
            settings['use_source_separation']
        )
