# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QListWidget, QListWidgetItem, QAbstractItemView, QScrollArea
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

class SourcePanel(QWidget):
    """
    LEFT side panel with three sections: REF / SEC / TER.
    Emits trackActivated(dict) when a source item is double-clicked.
    """
    trackActivated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ref_list = self._make_list()
        self.sec_list = self._make_list()
        self.ter_list = self._make_list()

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)

        for title, lw in [
            ("Reference Tracks", self.ref_list),
            ("Secondary Tracks", self.sec_list),
            ("Tertiary Tracks", self.ter_list),
        ]:
            group = QGroupBox(title)
            gl = QVBoxLayout(group)
            gl.addWidget(lw)
            wrap.addWidget(group)

        wrap.addStretch(1)

        # wire double-click
        for lw in (self.ref_list, self.sec_list, self.ter_list):
            lw.itemDoubleClicked.connect(self._on_item_double_clicked)

        # drop rule hook (dialog sets it)
        self._is_blocked_fn = None

    def set_block_rule(self, fn):
        """fn(track_data) -> bool; True means blocked (disabled)."""
        self._is_blocked_fn = fn

    def populate(self, track_info: dict):
        """Fill the three lists from the dialog-provided track_info."""
        source_map = {'REF': self.ref_list, 'SEC': self.sec_list, 'TER': self.ter_list}
        for lw in (self.ref_list, self.sec_list, self.ter_list):
            lw.clear()
        for source_key, list_widget in source_map.items():
            for track in track_info.get(source_key, []):
                name_part = f" '{track['name']}'" if track.get('name') else ""
                item_text = (f"[{track['type'][0].upper()}-{track['id']}] "
                             f"{track.get('codec_id','')} ({track.get('lang','und')}){name_part}")
                item = QListWidgetItem(item_text, list_widget)
                item.setData(Qt.UserRole, track)
                # visual guardrail for blocked items
                if self._is_blocked(track):
                    flags = item.flags()
                    flags &= ~Qt.ItemIsDragEnabled
                    flags &= ~Qt.ItemIsEnabled
                    item.setFlags(flags)
                    item.setForeground(QColor('#888'))
                    item.setToolTip("Video from Secondary/Tertiary is disabled. REF-only video is allowed.")

    # helpers
    def _make_list(self) -> QListWidget:
        lw = QListWidget()
        lw.setDragEnabled(True)
        lw.setSelectionMode(QAbstractItemView.SingleSelection)
        lw.setDefaultDropAction(Qt.CopyAction)
        return lw

    def _is_blocked(self, track: dict) -> bool:
        try:
            return self._is_blocked_fn(track) if self._is_blocked_fn else False
        except Exception:
            return False

    def _on_item_double_clicked(self, item: QListWidgetItem):
        if not item:
            return
        td = item.data(Qt.UserRole)
        if td and not self._is_blocked(td):
            self.trackActivated.emit(td)
