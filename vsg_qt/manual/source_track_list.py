# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Callable, Dict, List
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

IsBlockedFn = Callable[[dict], bool]
OnAddFn = Callable[[dict], None]

class SourceTrackList(QListWidget):
    """
    Read-only list of tracks for a single source (REF/SEC/TER).
    Supports drag & double-click -> notifies host via on_add callback.
    Host provides is_blocked(track) to disable SEC/TER video.
    """
    def __init__(self, *, is_blocked: IsBlockedFn, on_add: OnAddFn, parent=None):
        super().__init__(parent)
        self._is_blocked = is_blocked
        self._on_add = on_add
        self.setDragEnabled(True)
        self.setSelectionMode(self.SingleSelection)
        self.setDefaultDropAction(Qt.CopyAction)
        self.itemDoubleClicked.connect(self._on_double_click)

    def populate(self, tracks: List[Dict]):
        self.clear()
        for track in tracks or []:
            name_part = f" '{track['name']}'" if track.get('name') else ""
            item_text = (f"[{track['type'][0].upper()}-{track['id']}] "
                         f"{track.get('codec_id','')} ({track.get('lang','und')}){name_part}")
            it = QListWidgetItem(item_text, self)
            it.setData(Qt.UserRole, track)
            if self._is_blocked(track):
                flags = it.flags()
                flags &= ~Qt.ItemIsDragEnabled
                flags &= ~Qt.ItemIsEnabled
                it.setFlags(flags)
                it.setForeground(QColor('#888'))
                it.setToolTip("Video from Secondary/Tertiary is disabled. REF-only video is allowed.")

    # -- internal
    def _on_double_click(self, item: QListWidgetItem):
        if not item:
            return
        td = item.data(Qt.UserRole)
        if not td or self._is_blocked(td):
            return
        self._on_add(td)
