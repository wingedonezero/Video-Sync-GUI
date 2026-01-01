# vsg_qt/manual_selection_dialog/widgets.py
# -*- coding: utf-8 -*-
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
    def __init__(self, dialog: "ManualSelectionDialog" = None, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def add_track_item(self, track: dict, guard_block: bool):
        item_text = f"[{track['type'][0].upper()}-{track['id']}] {track.get('description', '')}"

        it = QListWidgetItem(item_text, self)
        it.setData(Qt.UserRole, track)

        if guard_block:
            flags = it.flags()
            flags &= ~Qt.ItemIsDragEnabled
            flags &= ~Qt.ItemIsEnabled
            it.setFlags(flags)
            it.setForeground(QColor('#888'))
            it.setToolTip("Video from other sources is disabled.\nOnly Source 1 video is allowed.")
        return it

    def _show_context_menu(self, pos: QPoint):
        """Show context menu for source tracks."""
        if not self.dialog:
            return

        item = self.itemAt(pos)
        if not item:
            return

        track = item.data(Qt.UserRole)
        if not track:
            return

        # Only show context menu for text-based subtitle tracks
        is_text_subtitle = (
            track.get('type') == 'subtitles' and
            track.get('codec_id', '').upper() in ['S_TEXT/UTF8', 'S_TEXT/ASS', 'S_TEXT/SSA']
        )

        if not is_text_subtitle:
            return

        menu = QMenu(self)
        act_create_signs = menu.addAction("Create Signs Track...")

        act = menu.exec_(self.mapToGlobal(pos))
        if act == act_create_signs:
            self.dialog._create_generated_track(track)


class FinalList(QListWidget):
    """Final output list that accepts drops and renders TrackWidget rows."""
    def __init__(self, dialog: "ManualSelectionDialog", parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def dropEvent(self, event):
        source = event.source()
        if source and source is not self:
            it = source.currentItem()
            if it:
                track = it.data(Qt.UserRole)
                if track and not self.dialog._logic.is_blocked_video(track):
                    self.add_track_widget(track)
                    event.accept()
            return
        super().dropEvent(event)

    def add_track_widget(self, track_data: dict, preset=False):
        item = QListWidgetItem()
        self.addItem(item)

        widget = TrackWidget(track_data, available_sources=self.dialog.available_sources)

        if hasattr(widget, 'style_editor_btn'):
            widget.style_editor_btn.clicked.connect(lambda checked, w=widget: self.dialog._launch_style_editor(w))

        if preset:
            if hasattr(widget, 'cb_default'):      widget.cb_default.setChecked(track_data.get('is_default', False))
            if hasattr(widget, 'cb_forced'):       widget.cb_forced.setChecked(track_data.get('is_forced_display', False))
            if hasattr(widget, 'cb_name'):         widget.cb_name.setChecked(track_data.get('apply_track_name', False))
            if hasattr(widget, 'cb_rescale'):      widget.cb_rescale.setChecked(track_data.get('rescale', False))

            # THE FIX: The redundant line that set the size_multiplier has been removed from here.
            # The TrackWidget's own constructor now handles this correctly and safely.

            if 'S_TEXT/UTF8' in (getattr(widget, 'codec_id', '') or '').upper():
                if hasattr(widget, 'cb_convert'): widget.cb_convert.setChecked(track_data.get('convert_to_ass', False))
            if hasattr(widget, 'logic'):
                widget.logic.refresh_badges()
                widget.logic.refresh_summary()

        if hasattr(widget, 'cb_default'):
            widget.cb_default.clicked.connect(lambda checked, w=widget: self._enforce_single_default(w))

        # --- MODIFICATION: Connect the 'Forced' checkbox to its enforcement logic ---
        if hasattr(widget, 'cb_forced'):
            widget.cb_forced.clicked.connect(self._enforce_single_forced)

        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)
        self.setCurrentItem(item)
        self.scrollToItem(item)

    def _show_context_menu(self, pos: QPoint):
        item = self.itemAt(pos)
        if not item: return
        widget = self.itemWidget(item)
        menu = QMenu(self)

        is_subs = getattr(widget, 'track_type', '') == 'subtitles'

        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()

        act_copy = menu.addAction("✂️ Copy Styles")
        act_paste = menu.addAction("📋 Paste Styles")
        act_copy.setEnabled(is_subs)
        act_paste.setEnabled(is_subs and self.dialog._style_clipboard is not None)
        menu.addSeparator()

        act_default = menu.addAction("Make Default")
        act_forced = menu.addAction("Toggle Forced") if is_subs else None
        menu.addSeparator()
        act_del = menu.addAction("Delete")

        act = menu.exec_(self.mapToGlobal(pos))
        if not act: return

        if act == act_up: self._move_by(-1)
        elif act == act_down: self._move_by(+1)
        elif act == act_copy: self.dialog._copy_styles(widget)
        elif act == act_paste: self.dialog._paste_styles(widget)
        elif act == act_default and hasattr(widget, 'cb_default'):
            self._enforce_single_default(widget, prefer=True)
        elif act_forced and act == act_forced and hasattr(widget, 'cb_forced'):
            widget.cb_forced.setChecked(not widget.cb_forced.isChecked())
            self._enforce_single_forced()
        elif act == act_del:
            self.takeItem(self.row(item))

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
        return [self.itemWidget(self.item(i)) for i in range(self.count()) if getattr(self.itemWidget(self.item(i)), 'track_type', None) == ttype]

    def _enforce_single_default(self, sender_widget, prefer=False):
        if prefer:
            sender_widget.cb_default.setChecked(True)
        self.dialog._logic.normalize_single_default_for_type(
            self._widgets_of_type(sender_widget.track_type),
            sender_widget.track_type,
            force_default_if_none=False,
            prefer_widget=sender_widget
        )

    def _enforce_single_forced(self):
        """Helper method to call the normalization logic for forced subtitles."""
        self.dialog._logic.normalize_forced_subtitles(self._widgets_of_type('subtitles'))
