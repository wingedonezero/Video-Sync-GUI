from __future__ import annotations
from typing import Dict, List, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QGroupBox, QScrollArea, QWidget
)

from .logic import ManualLogic
from .widgets import SourceList, FinalList

class ManualSelectionDialog(QDialog):
    """
    Drop-in replacement keeping the public API:
      - __init__(track_info, parent=None, previous_layout=None)
      - get_manual_layout() -> list[dict]

    Behavior parity with original:
      - Three source lists (REF/SEC/TER)
      - Final list with drag-drop & context menu
      - Guardrail: SEC/TER video blocked
      - Pre-population by abstract layout (order matching)
      - Keyboard helpers preserved (via FinalList)
      - Accept() returns manual layout payload identical to before
    """

    def __init__(self, track_info: Dict[str, List[dict]], parent=None, previous_layout: Optional[List[dict]] = None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)

        self.track_info = track_info
        self.manual_layout: Optional[List[dict]] = None

        root = QVBoxLayout(self)

        # Banner for pre-populate notice
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)

        # Main row
        row = QHBoxLayout()

        # ---- LEFT: single scroll column with three sections ----
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_wrap = QWidget(); left_v = QVBoxLayout(left_wrap); left_v.setContentsMargins(0,0,0,0)

        self.ref_list = SourceList()
        self.sec_list = SourceList()
        self.ter_list = SourceList()

        for title, lw in [
            ("Reference Tracks", self.ref_list),
            ("Secondary Tracks", self.sec_list),
            ("Tertiary Tracks", self.ter_list),
        ]:
            g = QGroupBox(title); gl = QVBoxLayout(g); gl.addWidget(lw); left_v.addWidget(g)

        left_v.addStretch(1)
        left_scroll.setWidget(left_wrap)
        row.addWidget(left_scroll, 1)

        # ---- RIGHT: Final Output ----
        self.final_list = FinalList(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        gl = QVBoxLayout(final_group); gl.addWidget(self.final_list)
        row.addWidget(final_group, 2)

        root.addLayout(row)

        # Populate source lists
        self._populate_sources()

        # Double-click adds to final (respect guardrail)
        self._wire_double_clicks()

        # Pre-populate if previous_layout is provided
        if previous_layout:
            realized = ManualLogic.prepopulate(previous_layout, self.track_info)
            if realized:
                self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
                self.info_label.setVisible(True)
                for t in realized:
                    if not ManualLogic.is_blocked_video(t):
                        self.final_list.add_track_widget(t, preset=True)

        # OK/Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ---- population ----
    def _populate_sources(self):
        for src_key, widget in (('REF', self.ref_list), ('SEC', self.sec_list), ('TER', self.ter_list)):
            for t in self.track_info.get(src_key, []):
                widget.add_track_item(t, guard_block=ManualLogic.is_blocked_video(t))

    def _wire_double_clicks(self):
        for lw in (self.ref_list, self.sec_list, self.ter_list):
            lw.itemDoubleClicked.connect(self._on_double_clicked_source)

    def _on_double_clicked_source(self, item):
        if not item: return
        td = item.data(Qt.UserRole)
        if td and not ManualLogic.is_blocked_video(td):
            self.final_list.add_track_widget(td)

    # ---- keyboard helpers ----
    def keyPressEvent(self, event):
        from PySide6.QtCore import Qt
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up:
            self.final_list._move_by(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down:
            self.final_list._move_by(+1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:
            item = self.final_list.currentItem()
            if item:
                w = self.final_list.itemWidget(item)
                if hasattr(w, 'cb_default'):
                    w.cb_default.setChecked(True)
                    # enforce single default for this type
                    ManualLogic.normalize_single_default_for_type(
                        self.final_list._widgets_of_type(w.track_type), w.track_type, prefer_widget=w
                    )
                    if hasattr(w, 'refresh_badges'):  w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
            event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            item = self.final_list.currentItem()
            if item:
                w = self.final_list.itemWidget(item)
                if getattr(w, 'track_type', '') == 'subtitles' and hasattr(w, 'cb_forced'):
                    w.cb_forced.setChecked(not w.cb_forced.isChecked())
                    ManualLogic.normalize_forced_subtitles(self.final_list._widgets_of_type('subtitles'))
                    if hasattr(w, 'refresh_badges'):  w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
            event.accept(); return
        if event.key() == Qt.Key_Delete:
            item = self.final_list.currentItem()
            if item:
                row = self.final_list.row(item)
                self.final_list.takeItem(row)
            event.accept(); return
        super().keyPressEvent(event)

    # ---- accept / output ----
    def accept(self):
        # normalize before building
        ManualLogic.normalize_single_default_for_type(
            self.final_list._widgets_of_type('audio'), 'audio'
        )
        ManualLogic.normalize_single_default_for_type(
            self.final_list._widgets_of_type('subtitles'), 'subtitles'
        )
        ManualLogic.normalize_forced_subtitles(self.final_list._widgets_of_type('subtitles'))

        # collect widgets in order
        widgets = []
        for i in range(self.final_list.count()):
            it = self.final_list.item(i)
            w = self.final_list.itemWidget(it)
            if w: widgets.append(w)

        self.manual_layout = ManualLogic.build_layout_from_widgets(widgets)
        super().accept()

    def get_manual_layout(self):
        return self.manual_layout
