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
    - Correlation target track: Which Source 1 track to correlate against
    - Use source separation: Whether to apply source separation for this source
    """

    def __init__(
        self,
        source_key: str,
        source1_audio_tracks: List[Dict[str, Any]],
        current_settings: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        """
        Initialize the source settings dialog.

        Args:
            source_key: The source being configured (e.g., "Source 2")
            source1_audio_tracks: List of audio track info dicts from Source 1
            current_settings: Current settings for this source (if any)
            parent: Parent widget
        """
        super().__init__(parent)
        self.source_key = source_key
        self.source1_tracks = source1_audio_tracks
        self.current_settings = current_settings or {}

        self.setWindowTitle(f"{source_key} Correlation Settings")
        self.setMinimumWidth(450)
        self.setModal(True)

        self._init_ui()
        self._apply_current_settings()

    def _init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)

        # --- Correlation Target Section ---
        target_group = QGroupBox("Correlation Target Track")
        target_layout = QVBoxLayout(target_group)

        # Explanation label
        explanation = QLabel(
            "Select which audio track from Source 1 to use for correlation.\n"
            "'Auto (Language Fallback)' uses global Analysis Language settings."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #666; font-size: 11px;")
        target_layout.addWidget(explanation)

        # Track dropdown
        form = QFormLayout()
        self.target_combo = QComboBox()
        self._populate_track_combo()
        form.addRow("Correlation Target:", self.target_combo)
        target_layout.addLayout(form)

        layout.addWidget(target_group)

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

    def _populate_track_combo(self):
        """Populate the track dropdown with Source 1's audio tracks."""
        self.target_combo.clear()

        # Add "Auto" option first
        self.target_combo.addItem("Auto (Language Fallback)", None)

        # Add each audio track from Source 1
        for i, track in enumerate(self.source1_tracks):
            props = track.get('properties', {})
            lang = props.get('language', 'und')
            name = props.get('track_name', '')
            codec = props.get('codec_id', 'unknown')
            channels = props.get('audio_channels', '')

            # Build display string
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
            self.target_combo.addItem(display_text, i)

    def _apply_current_settings(self):
        """Apply current settings to the UI controls."""
        # Correlation target
        target_track = self.current_settings.get('correlation_target_track')
        if target_track is not None:
            # Find the combo item with this track index
            for i in range(self.target_combo.count()):
                if self.target_combo.itemData(i) == target_track:
                    self.target_combo.setCurrentIndex(i)
                    break
        else:
            self.target_combo.setCurrentIndex(0)  # Auto

        # Source separation
        use_sep = self.current_settings.get('use_source_separation', False)
        self.use_separation_cb.setChecked(use_sep)

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        self.target_combo.setCurrentIndex(0)  # Auto
        self.use_separation_cb.setChecked(False)

    def get_settings(self) -> Dict[str, Any]:
        """
        Get the configured settings.

        Returns:
            Dict with:
            - 'correlation_target_track': int or None (None = auto/language fallback)
            - 'use_source_separation': bool
        """
        return {
            'correlation_target_track': self.target_combo.currentData(),
            'use_source_separation': self.use_separation_cb.isChecked()
        }

    def has_non_default_settings(self) -> bool:
        """Check if any non-default settings are configured."""
        settings = self.get_settings()
        return (
            settings['correlation_target_track'] is not None or
            settings['use_source_separation']
        )
