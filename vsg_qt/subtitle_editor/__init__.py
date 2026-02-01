# vsg_qt/subtitle_editor/__init__.py
"""
Subtitle Editor - Full-featured subtitle editing dialog.

Layout:
- Top: Video panel (40%) | Tab panel with dropdown (60%)
- Bottom: Events table with Aegisub-style columns

Provides:
- Video preview with subtitle overlay
- Style editing with live preview
- Event filtering for generated tracks
- Font management
- Overlap detection and highlighting
- CPS (characters per second) indicator

Usage:
    from vsg_qt.subtitle_editor import SubtitleEditorWindow

    dialog = SubtitleEditorWindow(
        subtitle_path="/path/to/file.ass",
        video_path="/path/to/video.mkv",
        fonts_dir="/path/to/fonts",
        existing_font_replacements={},  # For reopening: previous font replacements
        existing_style_patch={},        # For reopening: previous style changes
        existing_filter_config={},      # For reopening: previous filter config
        parent=self
    )

    if dialog.exec() == QDialog.Accepted:
        style_patch = dialog.get_style_patch()
        font_replacements = dialog.get_font_replacements()
        filter_config = dialog.get_filter_config()
"""

from .editor_window import SubtitleEditorWindow
from .events_table import EventsTable
from .state import EditorState
from .tab_panel import TabPanel
from .video_panel import VideoPanel

__all__ = [
    "EditorState",
    "EventsTable",
    "SubtitleEditorWindow",
    "TabPanel",
    "VideoPanel",
]
