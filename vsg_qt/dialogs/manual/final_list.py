# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QListWidget, QAbstractItemView
from PySide6.QtCore import Qt, Signal

class FinalListWidget(QListWidget):
    """
    Final output list that accepts drag/drop from source lists and supports
    move/delete helpers via its parent dialog.

    The dialog should provide:
      - set_drop_validator(callable) -> bool (track_data)  # block SEC/TER video
      - set_on_drop(callable) -> None (track_data)         # add a track
    """
    dropped = Signal(dict)  # emitted with track_data when an item is dropped from a source list

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_validator = None
        self._on_drop = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    # hooks
    def set_drop_validator(self, fn):
        self._drop_validator = fn

    def set_on_drop(self, fn):
        self._on_drop = fn

    # qt dnd
    def dropEvent(self, event):
        source = event.source()
        if source and source != self:
            source_item = source.currentItem()
            if source_item:
                track_data = source_item.data(Qt.UserRole)
                if track_data:
                    if self._drop_validator and not self._drop_validator(track_data):
                        # ok to drop
                        if self._on_drop:
                            self._on_drop(track_data)
                        self.dropped.emit(track_data)
                        event.accept()
                        return
                    # blocked
                    event.ignore()
                    return
            event.accept()
        else:
            super().dropEvent(event)
