# vsg_qt/subtitle_editor/state/undo_manager.py
# -*- coding: utf-8 -*-
"""
Undo/Redo manager for the subtitle editor.

Currently a stub - will be expanded in Phase 3.
"""
from __future__ import annotations

from typing import List, Any, Callable, Optional
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


@dataclass
class UndoAction:
    """Represents a single undoable action."""
    description: str
    undo_func: Callable[[], None]
    redo_func: Callable[[], None]


class UndoManager(QObject):
    """
    Manages undo/redo stack for the editor.

    TODO: Implement full undo/redo in Phase 3.
    """

    # Signals
    can_undo_changed = Signal(bool)
    can_redo_changed = Signal(bool)
    undo_text_changed = Signal(str)
    redo_text_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._undo_stack: List[UndoAction] = []
        self._redo_stack: List[UndoAction] = []
        self._max_stack_size = 100

    @property
    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        """Check if redo is available."""
        return len(self._redo_stack) > 0

    @property
    def undo_text(self) -> str:
        """Get description of the action that would be undone."""
        if self._undo_stack:
            return f"Undo: {self._undo_stack[-1].description}"
        return "Undo"

    @property
    def redo_text(self) -> str:
        """Get description of the action that would be redone."""
        if self._redo_stack:
            return f"Redo: {self._redo_stack[-1].description}"
        return "Redo"

    def push(self, action: UndoAction):
        """
        Push a new action onto the undo stack.

        Clears the redo stack.
        """
        self._undo_stack.append(action)
        self._redo_stack.clear()

        # Limit stack size
        while len(self._undo_stack) > self._max_stack_size:
            self._undo_stack.pop(0)

        self._emit_state_changes()

    def undo(self) -> bool:
        """
        Undo the last action.

        Returns:
            True if an action was undone
        """
        if not self._undo_stack:
            return False

        action = self._undo_stack.pop()
        action.undo_func()
        self._redo_stack.append(action)

        self._emit_state_changes()
        return True

    def redo(self) -> bool:
        """
        Redo the last undone action.

        Returns:
            True if an action was redone
        """
        if not self._redo_stack:
            return False

        action = self._redo_stack.pop()
        action.redo_func()
        self._undo_stack.append(action)

        self._emit_state_changes()
        return True

    def clear(self):
        """Clear both undo and redo stacks."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._emit_state_changes()

    def _emit_state_changes(self):
        """Emit signals for state changes."""
        self.can_undo_changed.emit(self.can_undo)
        self.can_redo_changed.emit(self.can_redo)
        self.undo_text_changed.emit(self.undo_text)
        self.redo_text_changed.emit(self.redo_text)
