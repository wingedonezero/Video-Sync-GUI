# vsg_qt/subtitle_editor/editor_window.py
# -*- coding: utf-8 -*-
"""
Main subtitle editor window.

Layout:
- Top row: Video panel (40%) | Tab panel (60%)
- Bottom row: Events table (full width)

The window provides a unified interface for:
- Viewing video with subtitle overlay
- Editing styles
- Configuring filters for generated tracks
- Managing font replacements
"""
from __future__ import annotations

import gc
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QDialogButtonBox, QMessageBox
)

from .state import EditorState
from .video_panel import VideoPanel
from .tab_panel import TabPanel
from .events_table import EventsTable

if TYPE_CHECKING:
    pass


class SubtitleEditorWindow(QDialog):
    """
    Main subtitle editor window.

    Provides a full-featured interface for editing subtitles with:
    - Video preview with subtitle overlay
    - Style editing
    - Filter configuration for generated tracks
    - Font management

    Args:
        subtitle_path: Path to the subtitle file to edit
        video_path: Path to video for preview (uses subtitle's source if available)
        fonts_dir: Optional directory containing fonts for preview
        existing_font_replacements: Optional dict of existing font replacements
        existing_style_patch: Optional dict of existing style changes
        existing_filter_config: Optional dict of existing filter configuration
        parent: Parent widget
    """

    def __init__(
        self,
        subtitle_path: str,
        video_path: str,
        fonts_dir: Optional[str] = None,
        existing_font_replacements: Optional[Dict] = None,
        existing_style_patch: Optional[Dict] = None,
        existing_filter_config: Optional[Dict] = None,
        parent=None
    ):
        super().__init__(parent)

        self._subtitle_path = Path(subtitle_path)
        self._video_path = Path(video_path)
        self._fonts_dir = Path(fonts_dir) if fonts_dir else None
        self._existing_replacements = existing_font_replacements or {}
        self._existing_style_patch = existing_style_patch or {}
        self._existing_filter_config = existing_filter_config or {}

        # Initialize state with existing values
        self._state = EditorState(
            parent=self,
            existing_style_patch=self._existing_style_patch,
            existing_filter_config=self._existing_filter_config
        )

        # Cached results (populated on accept)
        self._cached_style_patch: Dict[str, Dict[str, Any]] = {}
        self._cached_font_replacements: Dict[str, Dict[str, Any]] = {}
        self._cached_filter_config: Dict[str, Any] = {}

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._load_data()

    def _setup_window(self):
        """Configure window properties."""
        self.setWindowTitle("Subtitle Editor")
        self.setMinimumSize(1400, 900)

        # Allow maximize
        self.setWindowFlags(
            self.windowFlags() |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowMinimizeButtonHint
        )

        # Ensure proper cleanup when closed
        self.setAttribute(Qt.WA_DeleteOnClose)

    def _build_ui(self):
        """Build the main UI layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Main splitter (top/bottom)
        self._main_splitter = QSplitter(Qt.Vertical)

        # Top section: Video | Tabs
        top_widget = QSplitter(Qt.Horizontal)

        # Video panel (50%)
        self._video_panel = VideoPanel()
        top_widget.addWidget(self._video_panel)

        # Tab panel (50%)
        self._tab_panel = TabPanel()
        top_widget.addWidget(self._tab_panel)

        # Set initial sizes (50/50 split)
        top_widget.setSizes([500, 500])

        self._main_splitter.addWidget(top_widget)

        # Bottom section: Events table
        self._events_table = EventsTable()
        self._main_splitter.addWidget(self._events_table)

        # Set initial sizes (60% top, 40% bottom)
        self._main_splitter.setSizes([600, 400])

        main_layout.addWidget(self._main_splitter, 1)

        # Dialog buttons
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        main_layout.addWidget(self._button_box)

    def _connect_signals(self):
        """Connect all signals."""
        # Events table -> video seek and tab notification
        self._events_table.event_selected.connect(self._on_event_selected)
        self._events_table.event_double_clicked.connect(self._on_event_double_clicked)

        # Tab panel filter preview
        filtering_tab = self._tab_panel.get_filtering_tab()
        if filtering_tab:
            filtering_tab.filter_preview_requested.connect(
                self._events_table.set_filter_preview_mode
            )

        # Fonts tab changes
        fonts_tab = self._tab_panel.get_fonts_tab()
        if fonts_tab:
            fonts_tab.fonts_changed.connect(self._on_fonts_changed)

        # State signals for video reload
        self._state.style_changed.connect(self._reload_video_subtitles)

    def _load_data(self):
        """Load subtitle data and start video player."""
        # Load subtitle into state
        if not self._state.load_subtitle(self._subtitle_path, self._video_path):
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load subtitle file:\n{self._subtitle_path}"
            )
            return

        # Set state on all components
        self._video_panel.set_state(self._state)
        self._tab_panel.set_state(self._state)
        self._events_table.set_state(self._state)

        # Initialize fonts tab with existing replacements
        fonts_tab = self._tab_panel.get_fonts_tab()
        if fonts_tab:
            # Always set fonts_dir (even if None) to trigger font scanning
            fonts_tab.set_fonts_dir(self._fonts_dir)
            fonts_tab.set_replacements(self._existing_replacements)

        # Populate events table
        self._events_table.refresh()

        # Start video player with preview subtitle
        preview_path = self._state.preview_path
        if preview_path:
            self._video_panel.start_player(
                str(self._video_path),
                str(preview_path),
                str(self._fonts_dir) if self._fonts_dir else None
            )

    def _on_event_selected(self, event_index: int):
        """Handle event selection in table."""
        if event_index < 0:
            return

        # Seek video to event start time
        events = self._state.events
        if event_index < len(events):
            event = events[event_index]
            self._video_panel.seek_to(int(event.start_ms))

        # Notify tab panel
        self._tab_panel.on_event_selected(event_index)

    def _on_event_double_clicked(self, event_index: int):
        """Handle double-click on event."""
        # Same as single click for now - seek and select
        self._on_event_selected(event_index)

    def _on_fonts_changed(self):
        """Handle font replacement changes."""
        # Apply font replacements and reload video
        self._apply_font_replacements()
        self._reload_video_subtitles()

    def _apply_font_replacements(self):
        """Apply font replacements to the preview subtitle."""
        fonts_tab = self._tab_panel.get_fonts_tab()
        if not fonts_tab or not self._state.subtitle_data:
            return

        replacements = fonts_tab.get_replacements()
        if not replacements:
            return

        # Apply to subtitle data styles
        for style_name, repl_data in replacements.items():
            if style_name in self._state.styles:
                style = self._state.styles[style_name]
                new_font = repl_data.get('new_font_name')
                if new_font and hasattr(style, 'fontname'):
                    style.fontname = new_font

        # Save preview
        self._state.save_preview()

    def _reload_video_subtitles(self, style_name: str = None):
        """Reload video subtitles after changes."""
        if self._state.preview_path:
            self._video_panel.reload_subtitles(str(self._state.preview_path))

    def accept(self):
        """Save changes and close."""
        # Cache results before cleanup
        self._cached_style_patch = self._state.generate_style_patch()

        fonts_tab = self._tab_panel.get_fonts_tab()
        if fonts_tab:
            self._cached_font_replacements = fonts_tab.get_replacements()

        filtering_tab = self._tab_panel.get_filtering_tab()
        if filtering_tab:
            self._cached_filter_config = filtering_tab.get_filter_config()

        # Save to original file
        self._state.save_to_original()

        super().accept()

    def reject(self):
        """Cancel and close without saving."""
        super().reject()

    def closeEvent(self, event):
        """Clean up resources on close."""
        # Stop video player
        self._video_panel.stop_player()

        # Clean up state
        self._state.cleanup()

        # Force garbage collection
        gc.collect()

        super().closeEvent(event)

    # --- Public API ---

    def get_style_patch(self) -> Dict[str, Dict[str, Any]]:
        """
        Get the style changes made in this session.

        Returns:
            Dictionary mapping style names to their changed attributes
        """
        return self._cached_style_patch.copy()

    def get_font_replacements(self) -> Dict[str, Dict[str, Any]]:
        """
        Get the configured font replacements.

        Returns:
            Dictionary mapping style names to font replacement info
        """
        return self._cached_font_replacements.copy()

    def get_filter_config(self) -> Dict[str, Any]:
        """
        Get the filter configuration.

        Returns:
            Dictionary with filter mode, styles, and kept indices
        """
        return self._cached_filter_config.copy()
