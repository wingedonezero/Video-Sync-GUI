from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QListWidget, QAbstractItemView, QListWidgetItem, QMenu
)
from PySide6.QtGui import QColor

from vsg_qt.track_widget import TrackWidget
from .logic import ManualLogic

class SourceList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDefaultDropAction(Qt.CopyAction)

    def add_track_item(self, track: dict, guard_block: bool):
        name_part = f" '{track['name']}'" if track.get('name') else ""
        item_text = (f"[{track['type'][0].upper()}-{track['id']}] "
                     f"{track.get('codec_id','')} ({track.get('lang','und')}){name_part}")
        it = QListWidgetItem(item_text, self)
        it.setData(Qt.UserRole, track)

        if guard_block:
            flags = it.flags()
            flags &= ~Qt.ItemIsDragEnabled
            flags &= ~Qt.ItemIsEnabled
            it.setFlags(flags)
            it.setForeground(QColor('#888'))
            it.setToolTip("Video from Secondary/Tertiary is disabled. REF-only video is allowed.")
        return it


class FinalList(QListWidget):
    """
    Final output list that accepts drops from SourceList and renders TrackWidget rows.
    Context menu implements move up/down, default/forced toggles, and delete.
    """
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ---- DnD ----
    def dropEvent(self, event):
        source = event.source()
        if source and source is not self:
            it = source.currentItem()
            if it:
                track = it.data(Qt.UserRole)
                if track and not ManualLogic.is_blocked_video(track):
                    self.add_track_widget(track)
            event.accept()
            return
        super().dropEvent(event)

    # ---- Add one TrackWidget row ----
    def add_track_widget(self, track_data: dict, preset=False):
        item = QListWidgetItem()
        self.addItem(item)

        widget = TrackWidget(track_data)

        # If pre-populating with saved flags
        if preset:
            if hasattr(widget, 'cb_default'):    widget.cb_default.setChecked(track_data.get('is_default', False))
            if hasattr(widget, 'cb_forced'):     widget.cb_forced.setChecked(track_data.get('is_forced_display', False))
            if hasattr(widget, 'cb_name'):       widget.cb_name.setChecked(track_data.get('apply_track_name', False))
            if hasattr(widget, 'cb_rescale'):    widget.cb_rescale.setChecked(track_data.get('rescale', False))
            if hasattr(widget, 'size_multiplier'): widget.size_multiplier.setValue(track_data.get('size_multiplier', 1.0))
            if 'S_TEXT/UTF8' in (getattr(widget, 'codec_id', '') or '').upper():
                if hasattr(widget, 'cb_convert'): widget.cb_convert.setChecked(track_data.get('convert_to_ass', False))
            if hasattr(widget, 'refresh_badges'):  widget.refresh_badges()
            if hasattr(widget, 'refresh_summary'): widget.refresh_summary()

        # enforce one-default-per-type in real time
        if hasattr(widget, 'cb_default'):
            widget.cb_default.clicked.connect(lambda checked, w=widget: self._enforce_single_default(checked, w))

        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)
        self.setCurrentItem(item)
        self.scrollToItem(item)

    # ---- Context menu ----
    def _show_context_menu(self, pos: QPoint):
        item = self.itemAt(pos)
        if not item:
            return
        widget = self.itemWidget(item)
        menu = QMenu(self)

        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()
        act_default = menu.addAction("Make Default")
        act_forced = menu.addAction("Toggle Forced") if getattr(widget, 'track_type', '') == 'subtitles' else None
        menu.addSeparator()
        act_del = menu.addAction("Delete")

        act = menu.exec_(self.mapToGlobal(pos))
        if not act:
            return
        if act == act_up:
            self._move_by(-1)
        elif act == act_down:
            self._move_by(+1)
        elif act == act_default and hasattr(widget, 'cb_default'):
            widget.cb_default.setChecked(True)
            ManualLogic.normalize_single_default_for_type(self._widgets_of_type('audio') + self._widgets_of_type('subtitles'),
                                                          widget.track_type, prefer_widget=widget)
            if hasattr(widget, 'refresh_badges'):  widget.refresh_badges()
            if hasattr(widget, 'refresh_summary'): widget.refresh_summary()
        elif act_forced and act == act_forced and hasattr(widget, 'cb_forced'):
            widget.cb_forced.setChecked(not widget.cb_forced.isChecked())
            ManualLogic.normalize_forced_subtitles(self._widgets_of_type('subtitles'))
            if hasattr(widget, 'refresh_badges'):  widget.refresh_badges()
            if hasattr(widget, 'refresh_summary'): widget.refresh_summary()
        elif act == act_del:
            row = self.row(item)
            self.takeItem(row)

    # ---- helpers ----
    def _move_by(self, delta: int):
        item = self.currentItem()
        if not item: return
        row = self.row(item)
        new_row = row + delta
        if 0 <= new_row < self.count():
            it = self.takeItem(row)
            self.insertItem(new_row, it)
            self.setCurrentItem(it)

    def _widgets_of_type(self, ttype: str):
        out = []
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if w and getattr(w, 'track_type', None) == ttype:
                out.append(w)
        return out

    def _enforce_single_default(self, checked, sender_widget):
        if not checked:
            return
        # ensure single default among same type
        ManualLogic.normalize_single_default_for_type(
            self._widgets_of_type(sender_widget.track_type),
            sender_widget.track_type,
            prefer_widget=sender_widget
        )
