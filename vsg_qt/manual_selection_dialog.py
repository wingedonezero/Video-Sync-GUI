# vsg_qt/manual_selection_dialog.py
# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QListWidget, QAbstractItemView, QListWidgetItem, QGroupBox, QMenu,
    QScrollArea, QWidget
)
from .track_widget import TrackWidget

class FinalListWidget(QListWidget):
    """Final output list with drag-drop from source lists and light helpers."""
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def dropEvent(self, event):
        source = event.source()
        if source and source != self:
            source_item = source.currentItem()
            if source_item:
                track_data = source_item.data(Qt.UserRole)
                if track_data:
                    self.dialog.add_track_to_final_list(track_data)
            event.accept()
        else:
            super().dropEvent(event)

class ManualSelectionDialog(QDialog):
    """Manual track selection dialog — left column scroll w/ REF, SEC, TER stacked; right is Final Output."""
    def __init__(self, track_info, parent=None, previous_layout=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)
        self.track_info = track_info
        self.manual_layout = None

        root = QVBoxLayout(self)

        # Optional banner
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)

        main_row = QHBoxLayout()

        # ---- LEFT: single scroll column with three sections ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_wrap = QWidget()
        left_v = QVBoxLayout(left_wrap)
        left_v.setContentsMargins(0, 0, 0, 0)

        self.ref_list = self._create_source_list("Reference Tracks")
        self.sec_list = self._create_source_list("Secondary Tracks")
        self.ter_list = self._create_source_list("Tertiary Tracks")

        for title, lw in [
            ("Reference Tracks", self.ref_list),
            ("Secondary Tracks", self.sec_list),
            ("Tertiary Tracks", self.ter_list),
        ]:
            group = QGroupBox(title)
            gl = QVBoxLayout(group)
            gl.addWidget(lw)
            left_v.addWidget(group)

        left_v.addStretch(1)
        left_scroll.setWidget(left_wrap)
        main_row.addWidget(left_scroll, 1)

        # ---- RIGHT: Final Output ----
        self.final_list = FinalListWidget(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        final_layout = QVBoxLayout(final_group)
        final_layout.addWidget(self.final_list)
        main_row.addWidget(final_group, 2)

        root.addLayout(main_row)

        # Configure + populate
        self._configure_source_lists()
        self._populate_source_lists()

        if previous_layout:
            self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
            self.info_label.setVisible(True)
            self._prepopulate_from_layout(previous_layout)

        # Context menu on Final list for quick actions (no extra UI chrome)
        self.final_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.final_list.customContextMenuRequested.connect(self._show_context_menu)

        # Ok/Cancel — unchanged
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

    # ---------- Source Lists ----------
    def _create_source_list(self, _title):
        lw = QListWidget()
        return lw

    def _configure_source_lists(self):
        for source_list in (self.ref_list, self.sec_list, self.ter_list):
            source_list.setDragEnabled(True)
            source_list.setSelectionMode(QAbstractItemView.SingleSelection)
            source_list.setDefaultDropAction(Qt.CopyAction)

    def _populate_source_lists(self):
        source_map = {'REF': self.ref_list, 'SEC': self.sec_list, 'TER': self.ter_list}
        for source_key, list_widget in source_map.items():
            for track in self.track_info.get(source_key, []):
                name_part = f" '{track['name']}'" if track['name'] else ""
                item_text = (f"[{track['type'][0].upper()}-{track['id']}] "
                             f"{track['codec_id']} ({track['lang']}){name_part}")
                item = QListWidgetItem(item_text, list_widget)
                item.setData(Qt.UserRole, track)

    # ---------- Populate Final list ----------
    def _prepopulate_from_layout(self, layout):
        """Map previous layout by (source,type) order to current file tracks."""
        pools = {}
        counters = {}
        for src in ('REF', 'SEC', 'TER'):
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
                self.add_track_to_final_list(data, from_prepopulation=True)
            counters[(src, ttype)] = idx + 1

    def add_track_to_final_list(self, track_data, from_prepopulation=False):
        item = QListWidgetItem()
        self.final_list.addItem(item)
        widget = TrackWidget(track_data)
        if from_prepopulation:
            # carry over flags to widget
            if hasattr(widget, 'cb_default'): widget.cb_default.setChecked(track_data.get('is_default', False))
            if hasattr(widget, 'cb_forced'): widget.cb_forced.setChecked(track_data.get('is_forced_display', False))
            if hasattr(widget, 'cb_name'): widget.cb_name.setChecked(track_data.get('apply_track_name', False))
            if hasattr(widget, 'cb_rescale'): widget.cb_rescale.setChecked(track_data.get('rescale', False))
            if hasattr(widget, 'size_multiplier'): widget.size_multiplier.setValue(track_data.get('size_multiplier', 1.0))
            if 'S_TEXT/UTF8' in (getattr(widget, 'codec_id', '') or '').upper():
                if hasattr(widget, 'cb_convert'): widget.cb_convert.setChecked(track_data.get('convert_to_ass', False))

        # keep one default per type in realtime
        if hasattr(widget, 'cb_default'):
            widget.cb_default.clicked.connect(lambda checked, w=widget: self._enforce_single_default(checked, w))

        item.setSizeHint(widget.sizeHint())
        self.final_list.setItemWidget(item, widget)

    # ---------- Context menu (no visual layout changes) ----------
    def _show_context_menu(self, pos: QPoint):
        item = self.final_list.itemAt(pos)
        if not item:
            return
        widget = self.final_list.itemWidget(item)
        menu = QMenu(self)

        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()
        act_default = menu.addAction("Make Default")
        if getattr(widget, 'track_type', '') == 'subtitles':
            act_forced = menu.addAction("Toggle Forced")
        else:
            act_forced = None
        menu.addSeparator()
        act_delete = menu.addAction("Delete")

        action = menu.exec_(self.final_list.mapToGlobal(pos))
        if not action:
            return
        if action == act_up:
            self._move_item(-1)
        elif action == act_down:
            self._move_item(+1)
        elif action == act_default:
            if hasattr(widget, 'cb_default'):
                widget.cb_default.setChecked(True)
                self._normalize_single_default_for_type(widget.track_type, prefer_widget=widget)
                if hasattr(widget, 'refresh_label'): widget.refresh_label()
        elif act_forced and action == act_forced:
            if hasattr(widget, 'cb_forced'):
                widget.cb_forced.setChecked(not widget.cb_forced.isChecked())
                self._normalize_forced_subtitles()
                if hasattr(widget, 'refresh_label'): widget.refresh_label()
        elif action == act_delete:
            row = self.final_list.row(item)
            self.final_list.takeItem(row)

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

    # ---------- Keyboard helpers ----------
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
                    if hasattr(w, 'refresh_label'): w.refresh_label()
            event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            item = self.final_list.currentItem()
            if item:
                w = self.final_list.itemWidget(item)
                if getattr(w, 'track_type', '') == 'subtitles' and hasattr(w, 'cb_forced'):
                    w.cb_forced.setChecked(not w.cb_forced.isChecked())
                    self._normalize_forced_subtitles()
                    if hasattr(w, 'refresh_label'): w.refresh_label()
            event.accept(); return
        if event.key() == Qt.Key_Delete:
            item = self.final_list.currentItem()
            if item:
                row = self.final_list.row(item)
                self.final_list.takeItem(row)
            event.accept(); return
        super().keyPressEvent(event)

    # ---------- Normalization helpers ----------
    def _enforce_single_default(self, checked, sender_widget):
        if not checked: return
        sender_type = sender_widget.track_type
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if widget and widget is not sender_widget and widget.track_type == sender_type:
                if hasattr(widget, 'cb_default'):
                    widget.cb_default.setChecked(False)
                    if hasattr(widget, 'refresh_label'): widget.refresh_label()

    def _normalize_single_default_for_type(self, ttype, prefer_widget=None):
        first_found = None
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if not widget or getattr(widget, 'track_type', None) != ttype:
                continue
            if hasattr(widget, 'cb_default'):
                if prefer_widget and widget is prefer_widget:
                    widget.cb_default.setChecked(True); first_found = widget
                elif widget.cb_default.isChecked():
                    if not first_found: first_found = widget
                    else: widget.cb_default.setChecked(False)
                if hasattr(widget, 'refresh_label'): widget.refresh_label()
        if not first_found:
            for i in range(self.final_list.count()):
                item = self.final_list.item(i)
                widget = self.final_list.itemWidget(item)
                if widget and getattr(widget, 'track_type', None) == ttype and hasattr(widget, 'cb_default'):
                    widget.cb_default.setChecked(True)
                    if hasattr(widget, 'refresh_label'): widget.refresh_label()
                    break

    def _normalize_forced_subtitles(self):
        first = None
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if not widget or getattr(widget, 'track_type', None) != 'subtitles':
                continue
            if hasattr(widget, 'cb_forced') and widget.cb_forced.isChecked():
                if not first: first = widget
                else: widget.cb_forced.setChecked(False)
            if hasattr(widget, 'refresh_label'): widget.refresh_label()

    # ---------- Accept ----------
    def accept(self):
        # normalize before building
        self._normalize_single_default_for_type('audio')
        self._normalize_single_default_for_type('subtitles')
        self._normalize_forced_subtitles()

        self.manual_layout = []
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if widget:
                track_data = widget.track_data.copy()
                cfg = {}
                if hasattr(widget, 'cb_default'): cfg['is_default'] = widget.cb_default.isChecked()
                if hasattr(widget, 'cb_forced'): cfg['is_forced_display'] = widget.cb_forced.isChecked()
                if hasattr(widget, 'cb_name'): cfg['apply_track_name'] = widget.cb_name.isChecked()
                if hasattr(widget, 'cb_rescale'): cfg['rescale'] = widget.cb_rescale.isChecked()
                if hasattr(widget, 'cb_convert'): cfg['convert_to_ass'] = widget.cb_convert.isChecked()
                if hasattr(widget, 'size_multiplier'): cfg['size_multiplier'] = widget.size_multiplier.value()
                track_data.update(cfg)
                self.manual_layout.append(track_data)
        super().accept()

    def get_manual_layout(self):
        return self.manual_layout
