# vsg_qt/manual_selection_dialog.py

# -*- coding: utf-8 -*-
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QListWidget, QAbstractItemView, QListWidgetItem, QGroupBox
)
from .track_widget import TrackWidget

class FinalListWidget(QListWidget):
    # ... (unchanged)
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
    def __init__(self, track_info, parent=None, previous_layout=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)
        self.track_info = track_info
        self.manual_layout = None
        self.layout = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        self.layout.addWidget(self.info_label, 0, Qt.AlignCenter)
        main_columns_layout = QHBoxLayout()
        self.ref_list = self._create_source_list("Reference Tracks", main_columns_layout)
        self.sec_list = self._create_source_list("Secondary Tracks", main_columns_layout)
        self.ter_list = self._create_source_list("Tertiary Tracks", main_columns_layout)
        self.final_list = FinalListWidget(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        final_layout = QVBoxLayout(final_group)
        final_layout.addWidget(self.final_list)
        main_columns_layout.addWidget(final_group, 2)
        self.layout.addLayout(main_columns_layout)
        self._configure_source_lists()
        self._populate_source_lists()
        if previous_layout:
            self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
            self.info_label.setVisible(True)
            self._prepopulate_from_layout(previous_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def _prepopulate_from_layout(self, layout):
        """
        Populates the final list by matching tracks from the previous layout
        to the available tracks in the current file based on their order.
        """
        available_tracks_pool = {}
        type_counters = {}
        for source in ['REF', 'SEC', 'TER']:
            for track in self.track_info.get(source, []):
                track_type = track['type']
                current_index = type_counters.get((source, track_type), 0)
                key = (source, track_type, current_index)
                available_tracks_pool[key] = track
                type_counters[(source, track_type)] = current_index + 1

        type_counters.clear()
        for prev_track in layout:
            source, track_type = prev_track['source'], prev_track['type']
            current_index = type_counters.get((source, track_type), 0)
            lookup_key = (source, track_type, current_index)
            matched_track = available_tracks_pool.get(lookup_key)
            if matched_track:
                track_to_add = matched_track.copy()
                track_to_add.update({
                    'is_default': prev_track.get('is_default', False),
                    'is_forced_display': prev_track.get('is_forced_display', False),
                    'apply_track_name': prev_track.get('apply_track_name', False),
                    'convert_to_ass': prev_track.get('convert_to_ass', False),
                    'rescale': prev_track.get('rescale', False),
                    'size_multiplier': prev_track.get('size_multiplier', 1.0)
                })
                self.add_track_to_final_list(track_to_add, from_prepopulation=True)
            type_counters[(source, track_type)] = current_index + 1

    def add_track_to_final_list(self, track_data, from_prepopulation=False):
        item = QListWidgetItem()
        self.final_list.addItem(item)
        widget = TrackWidget(track_data)
        if from_prepopulation:
            widget.cb_default.setChecked(track_data.get('is_default', False))
            widget.cb_forced.setChecked(track_data.get('is_forced_display', False))
            widget.cb_name.setChecked(track_data.get('apply_track_name', False))
            widget.cb_rescale.setChecked(track_data.get('rescale', False))
            widget.size_multiplier.setValue(track_data.get('size_multiplier', 1.0))
            if 'S_TEXT/UTF8' in widget.codec_id.upper():
                widget.cb_convert.setChecked(track_data.get('convert_to_ass', False))
        widget.cb_default.clicked.connect(lambda checked, w=widget: self._enforce_single_default(checked, w))
        item.setSizeHint(widget.sizeHint())
        self.final_list.setItemWidget(item, widget)

    # ... (the rest of the file is unchanged)
    def _create_source_list(self, title, parent_layout):
        list_widget = QListWidget()
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(list_widget)
        parent_layout.addWidget(group)
        return list_widget
    def _configure_source_lists(self):
        for source_list in [self.ref_list, self.sec_list, self.ter_list]:
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
    def _enforce_single_default(self, checked, sender_widget):
        if not checked: return
        sender_type = sender_widget.track_type
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if widget and widget is not sender_widget and widget.track_type == sender_type:
                widget.cb_default.setChecked(False)
    def accept(self):
        self.manual_layout = []
        for i in range(self.final_list.count()):
            item = self.final_list.item(i)
            widget = self.final_list.itemWidget(item)
            if widget:
                track_data = widget.track_data.copy()
                track_data.update(widget.get_config())
                self.manual_layout.append(track_data)
        super().accept()
    def get_manual_layout(self):
        return self.manual_layout
