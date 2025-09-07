# vsg_qt/manual_selection_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QGroupBox, QScrollArea, QWidget, QMessageBox
)

from .logic import ManualLogic
from .widgets import SourceList, FinalList
from vsg_qt.track_widget import TrackWidget
from vsg_qt.style_editor_dialog import StyleEditorDialog
from vsg_core.extraction.tracks import extract_tracks
from vsg_core.extraction.attachments import extract_attachments
from vsg_core.subtitles.convert import convert_srt_to_ass
from vsg_core.io.runner import CommandRunner
from vsg_core.subtitles.style_engine import StyleEngine

class ManualSelectionDialog(QDialog):
    def __init__(self, track_info: Dict[str, List[dict]], parent=None,
                 previous_layout: Optional[List[dict]] = None,
                 log_callback: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)

        self.track_info = track_info
        self.manual_layout: Optional[List[dict]] = None
        self.parent_config = parent.config if parent and hasattr(parent, 'config') else None
        self._style_clipboard: Optional[List[str]] = None
        self.log_callback = log_callback or (lambda msg: print(f"[Dialog] {msg}"))

        root = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)
        row = QHBoxLayout()
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_wrap = QWidget(); left_v = QVBoxLayout(left_wrap); left_v.setContentsMargins(0,0,0,0)
        self.ref_list = SourceList(); self.sec_list = SourceList(); self.ter_list = SourceList()
        for title, lw in [("Reference Tracks", self.ref_list), ("Secondary Tracks", self.sec_list), ("Tertiary Tracks", self.ter_list)]:
            g = QGroupBox(title); gl = QVBoxLayout(g); gl.addWidget(lw); left_v.addWidget(g)
        left_v.addStretch(1)
        left_scroll.setWidget(left_wrap)
        row.addWidget(left_scroll, 1)
        self.final_list = FinalList(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        gl = QVBoxLayout(final_group); gl.addWidget(self.final_list)
        row.addWidget(final_group, 2)
        root.addLayout(row)
        self._populate_sources()
        self._wire_double_clicks()
        if previous_layout:
            realized = ManualLogic.prepopulate(previous_layout, self.track_info)
            if realized:
                self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
                self.info_label.setVisible(True)
                for t in realized:
                    if not ManualLogic.is_blocked_video(t):
                        self.final_list.add_track_widget(t, preset=True)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _get_temp_subtitle_path(self, widget: TrackWidget, for_read_only=False) -> Optional[str]:
        track_data = widget.track_data
        if track_data.get('user_modified_path'):
            return track_data['user_modified_path']
        if for_read_only:
            return None
        source_file = track_data.get('original_path')
        track_id = track_data.get('id')
        if not all([source_file, track_id is not None, self.parent_config]):
            return None

        runner = CommandRunner(self.parent_config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        try:
            temp_dir = Path(tempfile.gettempdir()) / f"vsg_style_edit_{Path(source_file).stem}_{track_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            extracted = extract_tracks(source_file, temp_dir, runner, tool_paths, 'temp', specific_tracks=[track_id])
            if not extracted: return None
            temp_path = extracted[0]['path']
            if Path(temp_path).suffix.lower() == '.srt':
                temp_path = convert_srt_to_ass(temp_path, runner, tool_paths)
            widget.track_data['user_modified_path'] = temp_path
            return temp_path
        except Exception:
            return None

    def _copy_styles(self, widget: TrackWidget):
        temp_path = self._get_temp_subtitle_path(widget)
        if not temp_path:
            QMessageBox.information(self, "Copy Styles", "Could not prepare subtitle file for copying.")
            return
        engine = StyleEngine(temp_path)
        self._style_clipboard = engine.get_raw_style_block()
        if self._style_clipboard:
            self.info_label.setText("✅ Styles copied to clipboard.")
            self.info_label.setVisible(True)
        else:
            QMessageBox.warning(self, "Copy Styles", "No styles found in the selected track.")

    def _paste_styles(self, widget: TrackWidget):
        if not self._style_clipboard: return
        temp_path = self._get_temp_subtitle_path(widget)
        if not temp_path:
            QMessageBox.information(self, "Paste Styles", "Could not prepare subtitle file for pasting.")
            return
        engine = StyleEngine(temp_path)
        engine.set_raw_style_block(self._style_clipboard)
        self.info_label.setText("✅ Styles pasted.")
        self.info_label.setVisible(True)
        widget.refresh_badges()
        widget.refresh_summary()

    def _launch_style_editor(self, widget: TrackWidget):
        track_data = widget.track_data
        source_file = track_data.get('original_path')
        track_id = track_data.get('id')
        ref_video_path = self.track_info.get('REF', [{}])[0].get('original_path')

        if not all([source_file, track_id is not None, ref_video_path, self.parent_config]):
            QMessageBox.warning(self, "Error", "Could not launch editor: Missing necessary file information.")
            return

        runner = CommandRunner(self.parent_config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        fonts_dir = None
        try:
            font_temp_dir = Path(tempfile.gettempdir()) / f"vsg_fonts_{Path(source_file).stem}"
            font_temp_dir.mkdir(parents=True, exist_ok=True)
            extracted_fonts = extract_attachments(source_file, font_temp_dir, runner, tool_paths, 'font')
            if extracted_fonts:
                fonts_dir = str(font_temp_dir)
                self.log_callback(f"[INFO] Extracted {len(extracted_fonts)} font(s) for preview.")
        except Exception as e:
            self.log_callback(f"[WARN] Could not extract fonts: {e}")

        temp_subtitle_path_str = self._get_temp_subtitle_path(widget)
        if not temp_subtitle_path_str:
            QMessageBox.critical(self, "Error Preparing Editor", "Failed to extract or prepare the subtitle file.")
            return

        editor = StyleEditorDialog(ref_video_path, temp_subtitle_path_str, fonts_dir=fonts_dir, parent=self)
        if editor.exec():
            widget.track_data['user_modified_path'] = temp_subtitle_path_str
            widget.refresh_badges()
            widget.refresh_summary()

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

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up: self.final_list._move_by(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down: self.final_list._move_by(+1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:
            item = self.final_list.currentItem()
            if item:
                w = self.final_list.itemWidget(item)
                if hasattr(w, 'cb_default'):
                    w.cb_default.setChecked(True)
                    ManualLogic.normalize_single_default_for_type(self.final_list._widgets_of_type(w.track_type), w.track_type, prefer_widget=w)
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
            if item: self.final_list.takeItem(self.final_list.row(item)); event.accept(); return
        super().keyPressEvent(event)

    def accept(self):
        ManualLogic.normalize_single_default_for_type(self.final_list._widgets_of_type('audio'), 'audio')
        ManualLogic.normalize_single_default_for_type(self.final_list._widgets_of_type('subtitles'), 'subtitles')
        ManualLogic.normalize_forced_subtitles(self.final_list._widgets_of_type('subtitles'))
        widgets = []
        for i in range(self.final_list.count()):
            it = self.final_list.item(i)
            w = self.final_list.itemWidget(it)
            if w: widgets.append(w)
        self.manual_layout = ManualLogic.build_layout_from_widgets(widgets)
        super().accept()

    def get_manual_layout(self): return self.manual_layout
