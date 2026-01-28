# vsg_qt/subtitle_editor/state/editor_state.py
# -*- coding: utf-8 -*-
"""
Central state management for the subtitle editor.

Holds:
- SubtitleData instance
- Current selection
- Modified state
- Filter configuration
- Style patch data
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, List, Set, Any

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from vsg_core.subtitles.data import SubtitleData


class EditorState(QObject):
    """
    Central state for the subtitle editor.

    Emits signals when state changes so UI components can update.
    """

    # Signals
    subtitle_data_changed = Signal()  # SubtitleData was replaced/reloaded
    selection_changed = Signal(list)  # Selected event indices changed
    style_changed = Signal(str)       # A style was modified
    event_changed = Signal(int)       # An event was modified
    filter_changed = Signal()         # Filter configuration changed
    modified_changed = Signal(bool)   # Modified state changed

    def __init__(
        self,
        parent=None,
        existing_style_patch: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_filter_config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(parent)

        # Core data
        self._subtitle_data: Optional['SubtitleData'] = None
        self._original_path: Optional[Path] = None
        self._preview_path: Optional[Path] = None

        # Selection state
        self._selected_indices: List[int] = []
        self._current_style: Optional[str] = None

        # Modified tracking
        self._is_modified: bool = False
        self._original_style_values: Dict[str, Dict[str, Any]] = {}

        # Filter configuration (for generated tracks)
        # Initialize from existing config if provided
        if existing_filter_config:
            # Support both old ('mode'/'styles') and new ('filter_mode'/'filter_styles') formats
            self._filter_mode = existing_filter_config.get('filter_mode') or existing_filter_config.get('mode', 'exclude')
            filter_styles = existing_filter_config.get('filter_styles') or existing_filter_config.get('styles', [])
            self._filter_styles = set(filter_styles)
            self._forced_include_indices = set(existing_filter_config.get('forced_include', []))
            self._forced_exclude_indices = set(existing_filter_config.get('forced_exclude', []))
        else:
            self._filter_mode = 'exclude'
            self._filter_styles = set()
            self._forced_include_indices = set()
            self._forced_exclude_indices = set()

        # Style patch data (changes to apply)
        # Initialize from existing patch if provided
        self._style_patch: Dict[str, Dict[str, Any]] = dict(existing_style_patch) if existing_style_patch else {}

        # Font replacements
        self._font_replacements: Dict[str, str] = {}

        # Video info
        self._video_path: Optional[Path] = None
        self._video_fps: float = 23.976

    def load_subtitle(self, subtitle_path: Path, video_path: Optional[Path] = None) -> bool:
        """
        Load a subtitle file into the editor.

        Args:
            subtitle_path: Path to subtitle file
            video_path: Optional path to video for preview

        Returns:
            True if loaded successfully
        """
        from vsg_core.subtitles.data import SubtitleData

        try:
            self._original_path = Path(subtitle_path)
            self._subtitle_data = SubtitleData.from_file(subtitle_path)

            # Create preview copy
            self._preview_path = self._original_path.with_suffix('.preview' + self._original_path.suffix)
            shutil.copy(self._original_path, self._preview_path)

            # Store original style values for reset (BEFORE applying existing patches)
            self._original_style_values = {}
            for style_name, style in self._subtitle_data.styles.items():
                self._original_style_values[style_name] = style.to_dict()

            # Apply any existing style patches (from previous session)
            # This makes the editor show the previously modified values
            if self._style_patch:
                self._apply_existing_style_patch()

            # Set video path
            if video_path:
                self._video_path = Path(video_path)

            # If we have existing patches, mark as modified
            if self._style_patch or self._filter_styles or self._forced_include_indices or self._forced_exclude_indices:
                self._is_modified = True
                self.modified_changed.emit(True)
            else:
                self._is_modified = False
                self.modified_changed.emit(False)

            self.subtitle_data_changed.emit()
            return True

        except Exception as e:
            print(f"[EditorState] Failed to load subtitle: {e}")
            return False

    def _apply_existing_style_patch(self):
        """Apply existing style patches to loaded subtitle data."""
        if not self._subtitle_data or not self._style_patch:
            return

        for style_name, changes in self._style_patch.items():
            if style_name not in self._subtitle_data.styles:
                continue

            style = self._subtitle_data.styles[style_name]
            for attr, value in changes.items():
                if hasattr(style, attr):
                    try:
                        setattr(style, attr, value)
                    except Exception as e:
                        print(f"[EditorState] Failed to apply {attr}={value} to {style_name}: {e}")

    @property
    def subtitle_data(self) -> Optional['SubtitleData']:
        """Get the current SubtitleData."""
        return self._subtitle_data

    @property
    def events(self) -> List:
        """Get the list of subtitle events."""
        if self._subtitle_data:
            return self._subtitle_data.events
        return []

    @property
    def styles(self) -> Dict:
        """Get the styles dictionary."""
        if self._subtitle_data:
            return self._subtitle_data.styles
        return {}

    @property
    def style_names(self) -> List[str]:
        """Get list of style names."""
        return list(self.styles.keys())

    @property
    def selected_indices(self) -> List[int]:
        """Get currently selected event indices."""
        return self._selected_indices.copy()

    def set_selection(self, indices: List[int]):
        """Set the current selection."""
        self._selected_indices = indices.copy()
        self.selection_changed.emit(self._selected_indices)

    @property
    def current_style(self) -> Optional[str]:
        """Get the currently selected style name."""
        return self._current_style

    def set_current_style(self, style_name: str):
        """Set the currently selected style."""
        if style_name in self.styles:
            self._current_style = style_name

    @property
    def is_modified(self) -> bool:
        """Check if the subtitle has been modified."""
        return self._is_modified

    def mark_modified(self):
        """Mark the subtitle as modified."""
        if not self._is_modified:
            self._is_modified = True
            self.modified_changed.emit(True)

    @property
    def preview_path(self) -> Optional[Path]:
        """Get the preview file path."""
        return self._preview_path

    @property
    def original_path(self) -> Optional[Path]:
        """Get the original file path."""
        return self._original_path

    @property
    def video_path(self) -> Optional[Path]:
        """Get the video path."""
        return self._video_path

    @property
    def video_fps(self) -> float:
        """Get the video FPS."""
        return self._video_fps

    def set_video_fps(self, fps: float):
        """Set the video FPS."""
        if fps > 0:
            self._video_fps = fps

    # --- Filter Configuration ---

    @property
    def filter_mode(self) -> str:
        """Get filter mode ('include' or 'exclude')."""
        return self._filter_mode

    def set_filter_mode(self, mode: str):
        """Set filter mode."""
        if mode in ('include', 'exclude'):
            self._filter_mode = mode
            self.filter_changed.emit()

    @property
    def filter_styles(self) -> Set[str]:
        """Get the set of styles to filter."""
        return self._filter_styles.copy()

    @property
    def forced_include_indices(self) -> Set[int]:
        """Get the forced-include indices."""
        return self._forced_include_indices.copy()

    @property
    def forced_exclude_indices(self) -> Set[int]:
        """Get the forced-exclude indices."""
        return self._forced_exclude_indices.copy()

    def force_include_event(self, index: int):
        """Force an event to be included regardless of filter style."""
        if index < 0 or index >= len(self.events):
            return
        if index in self._forced_exclude_indices:
            self._forced_exclude_indices.discard(index)
        if index not in self._forced_include_indices:
            self._forced_include_indices.add(index)
            self.filter_changed.emit()
            self.mark_modified()

    def force_exclude_event(self, index: int):
        """Force an event to be excluded regardless of filter style."""
        if index < 0 or index >= len(self.events):
            return
        if index in self._forced_include_indices:
            self._forced_include_indices.discard(index)
        if index not in self._forced_exclude_indices:
            self._forced_exclude_indices.add(index)
            self.filter_changed.emit()
            self.mark_modified()

    def clear_forced_event(self, index: int):
        """Clear any forced include/exclude overrides for an event."""
        if index < 0 or index >= len(self.events):
            return
        removed = False
        if index in self._forced_include_indices:
            self._forced_include_indices.discard(index)
            removed = True
        if index in self._forced_exclude_indices:
            self._forced_exclude_indices.discard(index)
            removed = True
        if removed:
            self.filter_changed.emit()
            self.mark_modified()

    def set_filter_styles(self, styles: Set[str]):
        """Set the styles to filter."""
        self._filter_styles = set(styles)
        self.filter_changed.emit()

    def get_filtered_event_indices(self) -> Set[int]:
        """
        Get indices of events that would be KEPT after filtering.

        Returns:
            Set of event indices that pass the filter
        """
        kept = set()
        for i, event in enumerate(self.events):
            if event.is_comment:
                continue

            style_match = event.style in self._filter_styles

            if self._filter_mode == 'include':
                # Include mode: keep events whose style IS in the set
                keep = style_match
            else:
                # Exclude mode: keep events whose style IS NOT in the set
                keep = not style_match

            # Apply manual overrides
            if i in self._forced_include_indices:
                keep = True
            if i in self._forced_exclude_indices:
                keep = False

            if keep:
                kept.add(i)

        return kept

    def get_overlapping_events(self, event_index: int) -> List[int]:
        """
        Get indices of events that overlap with the given event.

        Args:
            event_index: Index of the event to check

        Returns:
            List of indices of overlapping events
        """
        if event_index < 0 or event_index >= len(self.events):
            return []

        target = self.events[event_index]
        overlapping = []

        for i, event in enumerate(self.events):
            if i == event_index:
                continue
            if event.is_comment:
                continue

            # Check for time overlap
            # Events overlap if: start1 < end2 AND start2 < end1
            if target.start_ms < event.end_ms and event.start_ms < target.end_ms:
                overlapping.append(i)

        return overlapping

    def update_event_style(self, index: int, style_name: str):
        """Update the style for a specific event."""
        if not self._subtitle_data:
            return
        if index < 0 or index >= len(self._subtitle_data.events):
            return
        if style_name not in self.styles:
            return
        event = self._subtitle_data.events[index]
        if event.style == style_name:
            return
        event.style = style_name
        self.event_changed.emit(index)
        self.filter_changed.emit()
        self.mark_modified()

    # --- Style Patch ---

    @property
    def style_patch(self) -> Dict[str, Dict[str, Any]]:
        """Get the style patch (changes to apply)."""
        return self._style_patch.copy()

    def update_style_patch(self, style_name: str, changes: Dict[str, Any]):
        """Update the style patch for a style."""
        if style_name not in self._style_patch:
            self._style_patch[style_name] = {}
        self._style_patch[style_name].update(changes)
        self.mark_modified()
        self.style_changed.emit(style_name)

    def reset_style(self, style_name: str):
        """Reset a style to its original values."""
        if style_name in self._original_style_values and self._subtitle_data:
            original = self._original_style_values[style_name]
            if style_name in self._subtitle_data.styles:
                style = self._subtitle_data.styles[style_name]
                for key, value in original.items():
                    if hasattr(style, key):
                        setattr(style, key, value)

            # Remove from patch
            if style_name in self._style_patch:
                del self._style_patch[style_name]

            self.style_changed.emit(style_name)

    # --- Font Replacements ---

    @property
    def font_replacements(self) -> Dict[str, str]:
        """Get font replacements."""
        return self._font_replacements.copy()

    def set_font_replacements(self, replacements: Dict[str, str]):
        """Set font replacements."""
        self._font_replacements = dict(replacements)
        self.mark_modified()

    # --- Save Operations ---

    def save_preview(self):
        """Save current state to preview file."""
        if self._subtitle_data and self._preview_path:
            self._subtitle_data.save(self._preview_path)

    def save_to_original(self):
        """Save current state to original file."""
        if self._subtitle_data and self._original_path:
            self._subtitle_data.save(self._original_path)
            self._is_modified = False
            self.modified_changed.emit(False)

    def generate_style_patch(self) -> Dict[str, Dict[str, Any]]:
        """
        Generate a style patch by comparing current values to original.

        Returns:
            Dictionary of style changes
        """
        patch = {}
        if not self._subtitle_data:
            return patch

        for style_name, style in self._subtitle_data.styles.items():
            if style_name not in self._original_style_values:
                continue

            original = self._original_style_values[style_name]
            current = style.to_dict()

            changes = {}
            for key, orig_value in original.items():
                curr_value = current.get(key)
                if curr_value != orig_value:
                    changes[key] = curr_value

            if changes:
                patch[style_name] = changes

        return patch

    # --- Cleanup ---

    def cleanup(self):
        """Clean up resources."""
        # Remove preview file
        if self._preview_path and self._preview_path.exists():
            try:
                self._preview_path.unlink()
            except Exception:
                pass

        self._subtitle_data = None
        self._original_path = None
        self._preview_path = None
