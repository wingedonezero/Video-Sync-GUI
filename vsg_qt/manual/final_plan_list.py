# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List, Optional
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu
from PySide6.QtCore import Qt, QPoint
from vsg_qt.track_widget import TrackWidget

class FinalPlanList(QListWidget):
    """
    Destination list that holds ordered TrackWidgets.
    Exposes helpers: add_track(), move_selected(), normalize_*(), build_layout()
    and handles context menu actions locally.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(self.SingleSelection)

        # context menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # -- drag from source lists
    def dropEvent(self, event):
        source = event.source()
        if source and source != self:
            src_item = source.currentItem()
            if src_item:
                td = src_item.data(Qt.UserRole)
                if td:
                    self.add_track(td)
            event.accept()
        else:
            super().dropEvent(event)

    # -- add / render
    def add_track(self, track_data: Dict, *, from_prepopulation: bool = False):
        item = QListWidgetItem()
        self.addItem(item)
        widget = TrackWidget(track_data)

        if from_prepopulation:
            # re-apply flags if present on dict
            if hasattr(widget, 'cb_default'): widget.cb_default.setChecked(track_data.get('is_default', False))
            if hasattr(widget, 'cb_forced'): widget.cb_forced.setChecked(track_data.get('is_forced_display', False))
            if hasattr(widget, 'cb_name'): widget.cb_name.setChecked(track_data.get('apply_track_name', False))
            if hasattr(widget, 'cb_rescale'): widget.cb_rescale.setChecked(track_data.get('rescale', False))
            if hasattr(widget, 'size_multiplier'): widget.size_multiplier.setValue(track_data.get('size_multiplier', 1.0))
            if 'S_TEXT/UTF8' in (getattr(widget, 'codec_id', '') or '').upper():
                if hasattr(widget, 'cb_convert'): widget.cb_convert.setChecked(track_data.get('convert_to_ass', False))
            if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
            if hasattr(widget, 'refresh_summary'): widget.refresh_summary()

        # one-default-per-type live
        if hasattr(widget, 'cb_default'):
            widget.cb_default.clicked.connect(lambda checked, w=widget: self._enforce_single_default(checked, w))

        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)
        self.setCurrentItem(item)
        self.scrollToItem(item)

    # -- movement
    def move_selected(self, delta: int):
        item = self.currentItem()
        if not item:
            return
        row = self.row(item)
        new_row = row + delta
        if 0 <= new_row < self.count():
            it = self.takeItem(row)
            self.insertItem(new_row, it)
            self.setCurrentItem(it)

    # -- normalization
    def _enforce_single_default(self, checked: bool, sender_widget: TrackWidget):
        if not checked:
            return
        sender_type = sender_widget.track_type
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if not w or w is sender_widget:
                continue
            if getattr(w, 'track_type', None) == sender_type and hasattr(w, 'cb_default'):
                w.cb_default.setChecked(False)
                if hasattr(w, 'refresh_badges'): w.refresh_badges()
                if hasattr(w, 'refresh_summary'): w.refresh_summary()

    def normalize_single_default_for_type(self, ttype: str, prefer_widget: Optional[TrackWidget] = None):
        first_found = None
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if not w or getattr(w, 'track_type', None) != ttype:
                continue
            if hasattr(w, 'cb_default'):
                if prefer_widget and w is prefer_widget:
                    w.cb_default.setChecked(True); first_found = w
                elif w.cb_default.isChecked():
                    if not first_found: first_found = w
                    else: w.cb_default.setChecked(False)
                if hasattr(w, 'refresh_badges'): w.refresh_badges()
                if hasattr(w, 'refresh_summary'): w.refresh_summary()

        if not first_found:
            for i in range(self.count()):
                it = self.item(i)
                w = self.itemWidget(it)
                if w and getattr(w, 'track_type', None) == ttype and hasattr(w, 'cb_default'):
                    w.cb_default.setChecked(True)
                    if hasattr(w, 'refresh_badges'): w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
                    break

    def normalize_forced_subtitles(self):
        first = None
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if not w or getattr(w, 'track_type', None) != 'subtitles':
                continue
            if hasattr(w, 'cb_forced') and w.cb_forced.isChecked():
                if not first: first = w
                else: w.cb_forced.setChecked(False)
            if hasattr(w, 'refresh_badges'): w.refresh_badges()
            if hasattr(w, 'refresh_summary'): w.refresh_summary()

    # -- build payload
    def build_layout(self) -> List[Dict]:
        out: List[Dict] = []
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if not w:
                continue
            td = w.track_data.copy()
            cfg = {}
            if hasattr(w, 'cb_default'): cfg['is_default'] = w.cb_default.isChecked()
            if hasattr(w, 'cb_forced'): cfg['is_forced_display'] = w.cb_forced.isChecked()
            if hasattr(w, 'cb_name'): cfg['apply_track_name'] = w.cb_name.isChecked()
            if hasattr(w, 'cb_rescale'): cfg['rescale'] = w.cb_rescale.isChecked()
            if hasattr(w, 'cb_convert'): cfg['convert_to_ass'] = w.cb_convert.isChecked()
            if hasattr(w, 'size_multiplier'): cfg['size_multiplier'] = w.size_multiplier.value()
            td.update(cfg)
            out.append(td)
        return out

    # -- context menu
    def _show_context_menu(self, pos: QPoint):
        item = self.itemAt(pos)
        if not item:
            return
        w = self.itemWidget(item)
        m = QMenu(self)

        act_up = m.addAction("Move Up")
        act_down = m.addAction("Move Down")
        m.addSeparator()
        act_default = m.addAction("Make Default")
        act_forced = m.addAction("Toggle Forced") if getattr(w, 'track_type', '') == 'subtitles' else None
        m.addSeparator()
        act_delete = m.addAction("Delete")

        act = m.exec_(self.mapToGlobal(pos))
        if not act: return

        if act == act_up:
            self.move_selected(-1)
        elif act == act_down:
            self.move_selected(+1)
        elif act == act_default and hasattr(w, 'cb_default'):
            w.cb_default.setChecked(True)
            self.normalize_single_default_for_type(w.track_type, prefer_widget=w)
            if hasattr(w, 'refresh_badges'): w.refresh_badges()
            if hasattr(w, 'refresh_summary'): w.refresh_summary()
        elif act_forced and act == act_forced and hasattr(w, 'cb_forced'):
            w.cb_forced.setChecked(not w.cb_forced.isChecked())
            self.normalize_forced_subtitles()
            if hasattr(w, 'refresh_badges'): w.refresh_badges()
            if hasattr(w, 'refresh_summary'): w.refresh_summary()
        elif act == act_delete:
            row = self.row(item); self.takeItem(row)
