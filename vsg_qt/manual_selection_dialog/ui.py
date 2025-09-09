# vsg_qt/manual_selection_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil
import tempfile
import time
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
    def __init__(self, track_info: Dict[str, List[dict]], *, config: "AppConfig",
                 log_callback: Optional[Callable[[str], None]] = None, parent=None,
                 previous_layout: Optional[List[dict]] = None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)

        self.track_info = track_info
        self.config = config
        self.log_callback = log_callback or (lambda msg: print(f"[Dialog] {msg}"))
        self.manual_layout: Optional[List[dict]] = None
        self._style_clipboard: Optional[List[str]] = None
        self.edited_widget = None

        self.source_lists: Dict[str, SourceList] = {}

        root = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)
        row = QHBoxLayout()
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_wrap = QWidget()
        self.left_vbox = QVBoxLayout(left_wrap); self.left_vbox.setContentsMargins(0,0,0,0)

        # --- Dynamic source list creation ---
        sorted_sources = sorted(track_info.keys(), key=lambda k: int(k.split(" ")[1]))
        for source_key in sorted_sources:
            title = f"{source_key} Tracks"
            if source_key == "Source 1":
                title = f"{source_key} (Reference) Tracks"

            source_list_widget = SourceList()
            self.source_lists[source_key] = source_list_widget

            group_box = QGroupBox(title)
            group_layout = QVBoxLayout(group_box)
            group_layout.addWidget(source_list_widget)
            self.left_vbox.addWidget(group_box)
        # ------------------------------------

        self.left_vbox.addStretch(1)
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

    def _ensure_editable_subtitle_path(self, widget: TrackWidget) -> Optional[str]:
        track_data = widget.track_data
        if track_data.get('user_modified_path'):
            return track_data['user_modified_path']

        source_file = track_data.get('original_path')
        track_id = track_data.get('id')
        if not all([source_file, track_id is not None, self.config]):
            self.log_callback("[ERROR] Missing info required for subtitle extraction (config or track data).")
            return None

        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        try:
            temp_dir = Path(tempfile.gettempdir()) / f"vsg_style_edit_{Path(source_file).stem}_{track_id}_{int(time.time())}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            extracted = extract_tracks(source_file, temp_dir, runner, tool_paths, 'edit', specific_tracks=[track_id])
            if not extracted:
                self.log_callback(f"[ERROR] mkvextract failed for track ID {track_id} from {source_file}")
                return None

            temp_path_str = extracted[0]['path']
            if Path(temp_path_str).suffix.lower() == '.srt':
                temp_path_str = convert_srt_to_ass(temp_path_str, runner, tool_paths)

            widget.track_data['user_modified_path'] = temp_path_str
            return temp_path_str
        except Exception as e:
            self.log_callback(f"[ERROR] Exception during subtitle preparation: {e}")
            return None

    def _copy_styles(self, widget: TrackWidget):
        temp_path = self._ensure_editable_subtitle_path(widget)
        if not temp_path:
            QMessageBox.warning(self, "Error", "Could not prepare subtitle file for copying.")
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
        temp_path = self._ensure_editable_subtitle_path(widget)
        if not temp_path:
            QMessageBox.warning(self, "Error", "Could not prepare subtitle file for pasting.")
            return
        engine = StyleEngine(temp_path)
        engine.set_raw_style_block(self._style_clipboard)
        self.info_label.setText("✅ Styles pasted.")
        self.info_label.setVisible(True)
        widget.refresh_badges()
        widget.refresh_summary()
        self.edited_widget = widget

    def _launch_style_editor(self, widget: TrackWidget):
        track_data = widget.track_data
        ref_video_path = self.track_info.get('Source 1', [{}])[0].get('original_path')
        if not ref_video_path:
            QMessageBox.warning(self, "Error", "Could not launch editor: Reference video path is missing.")
            return

        editable_sub_path = self._ensure_editable_subtitle_path(widget)
        if not editable_sub_path:
            QMessageBox.critical(self, "Error Preparing Editor", "Failed to extract or prepare the subtitle file.")
            return

        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract']}

        fonts_dir = None
        try:
            source_file = track_data.get('original_path')
            font_temp_dir = Path(tempfile.gettempdir()) / f"vsg_fonts_{Path(source_file).stem}"
            font_temp_dir.mkdir(parents=True, exist_ok=True)
            extracted_fonts = extract_attachments(source_file, font_temp_dir, runner, tool_paths, 'font')
            if extracted_fonts:
                fonts_dir = str(font_temp_dir)
                self.log_callback(f"[INFO] Extracted {len(extracted_fonts)} font(s) for preview.")
        except Exception as e:
            self.log_callback(f"[WARN] Could not extract fonts: {e}")

        editor = StyleEditorDialog(ref_video_path, editable_sub_path, fonts_dir=fonts_dir, parent=self)
        if editor.exec():
            widget.track_data['style_patch'] = editor.get_style_patch()
            self.edited_widget = widget
            widget.refresh_badges()
            widget.refresh_summary()

    def _populate_sources(self):
        for source_key, widget in self.source_lists.items():
            for t in self.track_info.get(source_key, []):
                widget.add_track_item(t, guard_block=ManualLogic.is_blocked_video(t))

    def _wire_double_clicks(self):
        for lw in self.source_lists.values():
            lw.itemDoubleClicked.connect(self._on_double_clicked_source)

    def _on_double_clicked_source(self, item):
        if not item: return
        td = item.data(Qt.UserRole)
        if td and not ManualLogic.is_blocked_video(td):
            self.final_list.add_track_widget(td, preset=('style_patch' in td))

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up: self.final_list._move_by(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down: self.final_list._move_by(+1); event.accept(); return
        # ... (key press handlers for default/forced/delete are unchanged) ...
        super().keyPressEvent(event)

    def accept(self):
        # ... (normalization logic is unchanged) ...
        widgets = []
        for i in range(self.final_list.count()):
            it = self.final_list.item(i)
            w = self.final_list.itemWidget(it)
            if w: widgets.append(w)
        self.manual_layout = ManualLogic.build_layout_from_widgets(widgets)
        super().accept()

    def get_manual_layout(self): return self.manual_layout
