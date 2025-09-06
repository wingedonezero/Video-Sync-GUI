# -*- coding: utf-8 -*-
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox, QMenu, QGroupBox
)
from .final_list import FinalListWidget
from .source_panel import SourcePanel
from vsg_qt.track_widget import TrackWidget

class ManualSelectionDialog(QDialog):
    """
    Split version:
      - SourcePanel (left) with three lists
      - FinalListWidget (right)
      - The dialog manages context menu, keyboard helpers, normalization, and compose layout.
    """
    def __init__(self, track_info: dict, parent=None, previous_layout=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)
        self.track_info = track_info
        self.manual_layout = None

        root = QVBoxLayout(self)

        # banner
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)

        # main row
        row = QHBoxLayout()

        # LEFT
        self.sources = SourcePanel()
        self.sources.set_block_rule(self.is_blocked_video)
        self.sources.populate(self.track_info)
        self.sources.trackActivated.connect(self._on_source_activated)
        left_group = QGroupBox("")  # purely visual spacing with group frame
        lg = QVBoxLayout(left_group); lg.setContentsMargins(0,0,0,0); lg.addWidget(self.sources)
        row.addWidget(left_group, 1)

        # RIGHT
        self.final_list = FinalListWidget()
        self.final_list.set_drop_validator(self.is_blocked_video)
        self.final_list.set_on_drop(self.add_track_to_final_list)

        right_group = QGroupBox("Final Output (Drag to reorder)")
        from PySide6.QtWidgets import QVBoxLayout as VB
        rg = VB(right_group); rg.addWidget(self.final_list)
        row.addWidget(right_group, 2)

        root.addLayout(row)

        # Pre-populate with previous layout if provided
        if previous_layout:
            self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
            self.info_label.setVisible(True)
            self._prepopulate_from_layout(previous_layout)

        # Context menu on final list
        self.final_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.final_list.customContextMenuRequested.connect(self._show_context_menu)

        # OK / Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ---------- rules ----------
    def is_blocked_video(self, track_data: dict) -> bool:
        """SEC/TER video is not allowed to enter the final plan."""
        try:
            return (track_data.get('type','').lower() == 'video' and
                    track_data.get('source','').upper() in ('SEC','TER'))
        except Exception:
            return False

    # ---------- source actions ----------
    def _on_source_activated(self, track_data: dict):
        if not self.is_blocked_video(track_data):
            self.add_track_to_final_list(track_data)

    # ---------- pre-populate ----------
    def _prepopulate_from_layout(self, layout):
        pools = {}
        counters = {}
        for src in ('REF','SEC','TER'):
            for t in self.track_info.get(src, []):
                key = (src, t['type'], counters.get((src, t['type']), 0))
                pools[key] = t
                counters[(src, t['type'])] = counters.get((src, t['type']), 0) + 1
        counters.clear()

        for prev in layout:
            src, ttype = prev['source'], prev['type']
            idx = counters.get((src, ttype), 0)
            key = (src, ttype, idx)
            match = pools.get(key)
            if match:
                data = match.copy()
                data.update({
                    'is_default': prev.get('is_default', False),
                    'is_forced_display': prev.get('is_forced_display', False),
                    'apply_track_name': prev.get('apply_track_name', False),
                    'convert_to_ass': prev.get('convert_to_ass', False),
                    'rescale': prev.get('rescale', False),
                    'size_multiplier': prev.get('size_multiplier', 1.0),
                })
                if not self.is_blocked_video(data):
                    self.add_track_to_final_list(data, from_prepopulation=True)
            counters[(src, ttype)] = idx + 1

    # ---------- add to final ----------
    def add_track_to_final_list(self, track_data, from_prepopulation=False):
        from PySide6.QtWidgets import QListWidgetItem
        it = QListWidgetItem()
        self.final_list.addItem(it)
        widget = TrackWidget(track_data)

        if from_prepopulation:
            if hasattr(widget, 'cb_default'): widget.cb_default.setChecked(track_data.get('is_default', False))
            if hasattr(widget, 'cb_forced'): widget.cb_forced.setChecked(track_data.get('is_forced_display', False))
            if hasattr(widget, 'cb_name'): widget.cb_name.setChecked(track_data.get('apply_track_name', False))
            if hasattr(widget, 'cb_rescale'): widget.cb_rescale.setChecked(track_data.get('rescale', False))
            if hasattr(widget, 'size_multiplier'): widget.size_multiplier.setValue(track_data.get('size_multiplier', 1.0))
            if 'S_TEXT/UTF8' in (getattr(widget, 'codec_id', '') or '').upper():
                if hasattr(widget, 'cb_convert'): widget.cb_convert.setChecked(track_data.get('convert_to_ass', False))
            if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
            if hasattr(widget, 'refresh_summary'): widget.refresh_summary()

        # realtime single-default enforcement per type
        if hasattr(widget, 'cb_default'):
            widget.cb_default.clicked.connect(lambda checked, w=widget: self._enforce_single_default(checked, w))

        it.setSizeHint(widget.sizeHint())
        self.final_list.setItemWidget(it, widget)
        self.final_list.setCurrentItem(it)
        self.final_list.scrollToItem(it)

    # ---------- context menu ----------
    def _show_context_menu(self, pos: QPoint):
        item = self.final_list.itemAt(pos)
        if not item:
            return
        widget = self.final_list.itemWidget(item)
        menu = QMenu(self)

        act_up   = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()
        act_def  = menu.addAction("Make Default")
        if getattr(widget, 'track_type', '') == 'subtitles':
            act_forced = menu.addAction("Toggle Forced")
        else:
            act_forced = None
        menu.addSeparator()
        act_del  = menu.addAction("Delete")

        action = menu.exec_(self.final_list.mapToGlobal(pos))
        if not action:
            return

        if action == act_up:
            self._move_item(-1)
        elif action == act_down:
            self._move_item(+1)
        elif action == act_def:
            if hasattr(widget, 'cb_default'):
                widget.cb_default.setChecked(True)
                self._normalize_single_default_for_type(widget.track_type, prefer_widget=widget)
                if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
                if hasattr(widget, 'refresh_summary'): widget.refresh_summary()
        elif act_forced and action == act_forced:
            if hasattr(widget, 'cb_forced'):
                widget.cb_forced.setChecked(not widget.cb_forced.isChecked())
                self._normalize_forced_subtitles()
                if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
                if hasattr(widget, 'refresh_summary'): widget.refresh_summary()
        elif action == act_del:
            row = self.final_list.row(item)
            self.final_list.takeItem(row)

    # ---------- movement ----------
    def _move_item(self, delta: int):
        item = self.final_list.currentItem()
        if not item:
            return
        row = self.final_list.row(item)
        new_row = row + delta
        if 0 <= new_row < self.final_list.count():
            it = self.final_list.takeItem(row)
            self.final_list.insertItem(new_row, it)
            self.final_list.setCurrentItem(it)

    # ---------- keyboard helpers ----------
    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up:
            self._move_item(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down:
            self._move_item(+1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:
            item = self.final_list.currentItem()
            if item:
                w = self.final_list.itemWidget(item)
                if hasattr(w, 'cb_default'):
                    w.cb_default.setChecked(True)
                    self._normalize_single_default_for_type(w.track_type, prefer_widget=w)
                    if hasattr(w, 'refresh_badges'): w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
            event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            item = self.final_list.currentItem()
            if item:
                w = self.final_list.itemWidget(item)
                if getattr(w, 'track_type', '') == 'subtitles' and hasattr(w, 'cb_forced'):
                    w.cb_forced.setChecked(not w.cb_forced.isChecked())
                    self._normalize_forced_subtitles()
                    if hasattr(w, 'refresh_badges'): w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
            event.accept(); return
        if event.key() == Qt.Key_Delete:
            item = self.final_list.currentItem()
            if item:
                row = self.final_list.row(item)
                self.final_list.takeItem(row)
            event.accept(); return
        super().keyPressEvent(event)

    # ---------- normalization helpers ----------
    def _enforce_single_default(self, checked, sender_widget):
        if not checked:
            return
        sender_type = sender_widget.track_type
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if widget and widget is not sender_widget and widget.track_type == sender_type:
                if hasattr(widget, 'cb_default'):
                    widget.cb_default.setChecked(False)
                    if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
                    if hasattr(widget, 'refresh_summary'): widget.refresh_summary()

    def _normalize_single_default_for_type(self, ttype, prefer_widget=None):
        first_found = None
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if not widget or getattr(widget, 'track_type', None) != ttype:
                continue
            if hasattr(widget, 'cb_default'):
                if prefer_widget and widget is prefer_widget:
                    widget.cb_default.setChecked(True)
                    first_found = widget
                elif widget.cb_default.isChecked():
                    if not first_found:
                        first_found = widget
                    else:
                        widget.cb_default.setChecked(False)
                if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
                if hasattr(widget, 'refresh_summary'): widget.refresh_summary()

        if not first_found:
            for i in range(self.final_list.count()):
                item = self.final_list.item(i)
                widget = self.final_list.itemWidget(item)
                if widget and getattr(widget, 'track_type', None) == ttype and hasattr(widget, 'cb_default'):
                    widget.cb_default.setChecked(True)
                    if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
                    if hasattr(widget, 'refresh_summary'): widget.refresh_summary()
                    break

    def _normalize_forced_subtitles(self):
        first = None
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if not widget or getattr(widget, 'track_type', None) != 'subtitles':
                continue
            if hasattr(widget, 'cb_forced') and widget.cb_forced.isChecked():
                if not first:
                    first = widget
                else:
                    widget.cb_forced.setChecked(False)
            if hasattr(widget, 'refresh_badges'): widget.refresh_badges()
            if hasattr(widget, 'refresh_summary'): widget.refresh_summary()

    # ---------- accept ----------
    def accept(self):
        # normalize first
        self._normalize_single_default_for_type('audio')
        self._normalize_single_default_for_type('subtitles')
        self._normalize_forced_subtitles()

        # build layout payload
        self.manual_layout = []
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if widget:
                track_data = widget.track_data.copy()
                cfg = {}
                if hasattr(widget, 'cb_default'): cfg['is_default'] = widget.cb_default.isChecked()
                if hasattr(widget, 'cb_forced'): cfg['is_forced_display'] = widget.cb_forced.isChecked()
                if hasattr(widget, 'cb_name'):   cfg['apply_track_name'] = widget.cb_name.isChecked()
                if hasattr(widget, 'cb_rescale'): cfg['rescale'] = widget.cb_rescale.isChecked()
                if hasattr(widget, 'cb_convert'): cfg['convert_to_ass'] = widget.cb_convert.isChecked()
                if hasattr(widget, 'size_multiplier'): cfg['size_multiplier'] = widget.size_multiplier.value()
                track_data.update(cfg)
                self.manual_layout.append(track_data)
        super().accept()

    def get_manual_layout(self):
        return self.manual_layout
