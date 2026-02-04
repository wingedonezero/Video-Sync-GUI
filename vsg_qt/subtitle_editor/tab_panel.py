# vsg_qt/subtitle_editor/tab_panel.py
"""
Tab panel with dropdown selector for subtitle editor.

Uses a dropdown (QComboBox) instead of traditional tabs to save vertical space.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .tabs import BaseTab, FilteringTab, FontsTab, StylesTab

if TYPE_CHECKING:
    from .state import EditorState


class TabPanel(QWidget):
    """
    Panel containing all editor tabs with dropdown selector.

    The dropdown replaces traditional tabs to save vertical space,
    following the user's request for a more compact UI.
    """

    # Signal emitted when tab changes
    tab_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: EditorState | None = None
        self._tabs: list[BaseTab] = []
        self._current_tab: BaseTab | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the tab panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header with dropdown
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        label = QLabel("Panel:")
        header_layout.addWidget(label)

        self._selector = QComboBox()
        self._selector.setMinimumWidth(120)
        self._selector.currentIndexChanged.connect(self._on_tab_selected)
        header_layout.addWidget(self._selector, 1)

        layout.addLayout(header_layout)

        # Stacked widget for tab contents
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # Create and add default tabs
        self._create_tabs()

    def _create_tabs(self) -> None:
        """Create the default set of tabs."""
        # Styles tab
        styles_tab = StylesTab()
        self._add_tab(styles_tab)

        # Filtering tab
        filtering_tab = FilteringTab()
        self._add_tab(filtering_tab)

        # Fonts tab
        fonts_tab = FontsTab()
        self._add_tab(fonts_tab)

    def _add_tab(self, tab: BaseTab) -> None:
        """
        Add a tab to the panel.

        Args:
            tab: Tab widget to add
        """
        self._tabs.append(tab)
        self._selector.addItem(tab.TAB_NAME)
        self._stack.addWidget(tab)

    def set_state(self, state: EditorState) -> None:
        """
        Set the editor state for all tabs.

        Args:
            state: EditorState instance
        """
        self._state = state

        for tab in self._tabs:
            tab.set_state(state)

    def _on_tab_selected(self, index: int) -> None:
        """Handle tab selection change."""
        if index < 0 or index >= len(self._tabs):
            return

        # Deactivate current tab
        if self._current_tab:
            self._current_tab.on_deactivated()

        # Switch to new tab
        self._current_tab = self._tabs[index]
        self._stack.setCurrentIndex(index)
        self._current_tab.on_activated()

        self.tab_changed.emit(self._current_tab.TAB_NAME)

    def on_event_selected(self, event_index: int) -> None:
        """
        Notify the current tab of event selection.

        Args:
            event_index: Index of selected event
        """
        if self._current_tab:
            self._current_tab.on_event_selected(event_index)

    def get_tab(self, tab_name: str) -> BaseTab | None:
        """
        Get a tab by name.

        Args:
            tab_name: Name of the tab

        Returns:
            Tab instance or None if not found
        """
        for tab in self._tabs:
            if tab_name == tab.TAB_NAME:
                return tab
        return None

    def get_styles_tab(self) -> StylesTab | None:
        """Get the styles tab."""
        tab = self.get_tab("Styles")
        return tab if isinstance(tab, StylesTab) else None

    def get_filtering_tab(self) -> FilteringTab | None:
        """Get the filtering tab."""
        tab = self.get_tab("Filtering")
        return tab if isinstance(tab, FilteringTab) else None

    def get_fonts_tab(self) -> FontsTab | None:
        """Get the fonts tab."""
        tab = self.get_tab("Fonts")
        return tab if isinstance(tab, FontsTab) else None

    def select_tab(self, tab_name: str) -> None:
        """
        Select a tab by name.

        Args:
            tab_name: Name of the tab to select
        """
        for i, tab in enumerate(self._tabs):
            if tab_name == tab.TAB_NAME:
                self._selector.setCurrentIndex(i)
                break

    def get_all_results(self) -> dict:
        """
        Get results from all tabs.

        Returns:
            Combined dictionary of all tab results
        """
        results = {}
        for tab in self._tabs:
            result = tab.get_result()
            results.update(result)
        return results

    @property
    def current_tab_name(self) -> str:
        """Get the name of the currently selected tab."""
        if self._current_tab:
            return self._current_tab.TAB_NAME
        return ""
