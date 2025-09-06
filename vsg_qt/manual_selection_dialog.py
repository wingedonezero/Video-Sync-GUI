# vsg_qt/manual_selection_dialog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Dict, List, Tuple
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QGroupBox, QScrollArea, QWidget
)

from vsg_qt.manual import SourceTrackList, FinalPlanList

class ManualSelectionDialog(QDialog):
    """
    Manual track selection dialog (modular):
      LEFT: SourceTrackList per REF/SEC/TER in a single scroll column
      RIGHT: FinalPlanList that holds TrackWidgets
    """
    def __init__(self, track_info: Dict[str, List[dict]], parent=None, previous_layout: List[dict] | None = None):
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

        row = QHBoxLayout()

        # left scroll column
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_wrap = QWidget(); left_v = QVBoxLayout(left_wrap); left_v.setContentsMargins(0,0,0,0)

        self.ref_list = SourceTrackList(is_blocked=self.is_blocked_video, on_add=self._add_to_final)
        self.sec_list = SourceTrackList(is_blocked=self.is_blocked_video, on_add=self._add_to_final)
        self.ter_list = SourceTrackList(is_blocked=self.is_blocked_video, on_add=self._add_to_final)

        for title, lw in [("Reference Tracks", self.ref_list),
                          ("Secondary Tracks", self.sec_list),
                          ("Tertiary Tracks", self.ter_list)]:
            grp = QGroupBox(title); gl = QVBoxLayout(grp); gl.addWidget(lw); left_v.addWidget(grp)

        left_v.addStretch(1)
        left_scroll.setWidget(left_wrap)
        row.addWidget(left_scroll, 1)

        # right: final list
        self.final_list = FinalPlanList(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        vg = QVBoxLayout(final_group); vg.addWidget(self.final_list)
        row.addWidget(final_group, 2)

        root.addLayout(row)

        # populate sources
        self._populate_sources()

        # pre-populate from previous abstract layout (optional)
        if previous_layout:
            self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
            self.info_label.setVisible(True)
            for td in self._materialize_from_previous(previous_layout):
                if not self.is_blocked_video(td):
                    self.final_list.add_track(td, from_prepopulation=True)

        # ok/cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ---------- policies ----------
    def is_blocked_video(self, track_data: dict) -> bool:
        """SEC/TER video may not be added to final plan."""
        try:
            return (track_data.get('type','').lower() == 'video' and
                    track_data.get('source','').upper() in ('SEC','TER'))
        except Exception:
            return False

    # ---------- population ----------
    def _populate_sources(self):
        self.ref_list.populate(self.track_info.get('REF', []))
        self.sec_list.populate(self.track_info.get('SEC', []))
        self.ter_list.populate(self.track_info.get('TER', []))

    # ---------- bridge: source -> final ----------
    def _add_to_final(self, track_data: dict):
        if not self.is_blocked_video(track_data):
            self.final_list.add_track(track_data)

    # ---------- previous layout materialization (by order within (source,type)) ----------
    def _materialize_from_previous(self, layout: List[dict]) -> List[dict]:
        pools = {}
        counters: Dict[Tuple[str,str], int] = {}
        for src in ('REF','SEC','TER'):
            for t in self.track_info.get(src, []):
                key = (src, t['type'], counters.get((src,t['type']), 0))
                pools[key] = t
                counters[(src,t['type'])] = counters.get((src,t['type']), 0) + 1

        counters.clear()
        realized = []
        for prev in layout:
            src, ttype = prev['source'], prev['type']
            idx = counters.get((src, ttype), 0)
            key = (src, ttype, idx)
            match = pools.get(key)
            if match:
                td = match.copy()
                td.update({
                    'is_default': prev.get('is_default', False),
                    'is_forced_display': prev.get('is_forced_display', False),
                    'apply_track_name': prev.get('apply_track_name', False),
                    'convert_to_ass': prev.get('convert_to_ass', False),
                    'rescale': prev.get('rescale', False),
                    'size_multiplier': prev.get('size_multiplier', 1.0),
                })
                realized.append(td)
            counters[(src, ttype)] = idx + 1
        return realized

    # ---------- keyboard helpers ----------
    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up:
            self.final_list.move_selected(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down:
            self.final_list.move_selected(+1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:
            it = self.final_list.currentItem()
            if it:
                w = self.final_list.itemWidget(it)
                if hasattr(w, 'cb_default'):
                    w.cb_default.setChecked(True)
                    self.final_list.normalize_single_default_for_type(w.track_type, prefer_widget=w)
                    if hasattr(w, 'refresh_badges'): w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
            event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            it = self.final_list.currentItem()
            if it:
                w = self.final_list.itemWidget(it)
                if getattr(w, 'track_type', '') == 'subtitles' and hasattr(w, 'cb_forced'):
                    w.cb_forced.setChecked(not w.cb_forced.isChecked())
                    self.final_list.normalize_forced_subtitles()
                    if hasattr(w, 'refresh_badges'): w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
            event.accept(); return
        if event.key() == Qt.Key_Delete:
            it = self.final_list.currentItem()
            if it:
                row = self.final_list.row(it)
                self.final_list.takeItem(row)
            event.accept(); return
        super().keyPressEvent(event)

    # ---------- accept ----------
    def accept(self):
        # normalize before building
        self.final_list.normalize_single_default_for_type('audio')
        self.final_list.normalize_single_default_for_type('subtitles')
        self.final_list.normalize_forced_subtitles()
        self.manual_layout = self.final_list.build_layout()
        super().accept()

    def get_manual_layout(self):
        return self.manual_layout
