# vsg_qt/subtitle_editor/tabs/base_tab.py
# -*- coding: utf-8 -*-
"""
Base class for subtitle editor tabs.

All tabs inherit from this and implement their specific functionality.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import QWidget, QScrollArea, QVBoxLayout

if TYPE_CHECKING:
    from ..state import EditorState


class BaseTab(QScrollArea):
    """
    Base class for editor tabs.

    Provides:
    - Scrollable content area
    - Access to editor state
    - Standard interface for tabs
    """

    # Display name for the tab (shown in dropdown)
    TAB_NAME: str = "Base"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: Optional['EditorState'] = None

        # Set up scrollable area
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)

        # Content widget
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self.setWidget(self._content)

    def set_state(self, state: 'EditorState'):
        """
        Set the editor state.

        Args:
            state: EditorState instance
        """
        self._state = state
        self._on_state_set()

    @property
    def state(self) -> Optional['EditorState']:
        """Get the editor state."""
        return self._state

    @property
    def content_layout(self) -> QVBoxLayout:
        """Get the content layout to add widgets to."""
        return self._content_layout

    def _on_state_set(self):
        """
        Called when state is set.

        Override to connect to state signals and initialize from state.
        """
        pass

    @abstractmethod
    def on_activated(self):
        """
        Called when this tab becomes active (selected in dropdown).

        Override to refresh UI or perform actions when tab is shown.
        """
        pass

    def on_deactivated(self):
        """
        Called when this tab is deactivated (another tab selected).

        Override to save pending changes or clean up.
        """
        pass

    def on_event_selected(self, event_index: int):
        """
        Called when an event is selected in the events table.

        Override to update tab content based on selection.

        Args:
            event_index: Index of the selected event
        """
        pass

    def get_result(self) -> dict:
        """
        Get the result/changes from this tab.

        Override to return tab-specific results (e.g., style patch, filter config).

        Returns:
            Dictionary with tab results
        """
        return {}
