# vsg_qt/manual_selection_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil
import tempfile
import time
import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QGroupBox, QScrollArea, QWidget, QMessageBox, QPushButton, QCheckBox, QFileDialog
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
                 previous_layout: Optional[List[dict]] = None,
                 previous_attachment_sources: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)

        self.track_info = track_info
        self.config = config
        self.log_callback = log_callback or (lambda msg: print(f"[Dialog] {msg}"))
        self.manual_layout: Optional[List[dict]] = None
        self.attachment_sources: List[str] = []
        self._style_clipboard: Optional[List[str]] = None
        self.edited_widget = None

        self.source_lists: Dict[str, SourceList] = {}
        self.attachment_checkboxes: Dict[str, QCheckBox] = {}
        self.available_sources = sorted(track_info.keys(), key=lambda k: int(re.search(r'\d+', k).group()))

        # --- Main Layout ---
        root = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)

        main_hbox = QHBoxLayout()

        # --- Left Pane (Source Lists) ---
        left_pane_widget = QWidget()
        left_pane_layout = QVBoxLayout(left_pane_widget)
        left_pane_layout.setContentsMargins(0,0,0,0)

        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_widget = QWidget()
        self.left_vbox = QVBoxLayout(left_widget)
        self.left_vbox.setContentsMargins(0,0,0,0)

        for source_key in self.available_sources:
            path_name = Path(track_info[source_key][0]['original_path']).name if track_info[source_key] else "N/A"
            title = f"{source_key} Tracks ('{path_name}')"
            if source_key == "Source 1":
                title = f"{source_key} (Reference) Tracks ('{path_name}')"

            source_list_widget = SourceList()
            self.source_lists[source_key] = source_list_widget

            group_box = QGroupBox(title)
            group_layout = QVBoxLayout(group_box); group_layout.addWidget(source_list_widget)
            self.left_vbox.addWidget(group_box)

        # External Subtitles List
        self.external_list = SourceList()
        self.ext_group = QGroupBox("External Subtitles")
        ext_layout = QVBoxLayout(self.ext_group); ext_layout.addWidget(self.external_list)
        self.ext_group.setVisible(False) # Hide until files are added
        self.left_vbox.addWidget(self.ext_group)

        self.left_vbox.addStretch(1)
        left_scroll.setWidget(left_widget)

        self.add_external_btn = QPushButton("Add External Subtitle(s)...")
        left_pane_layout.addWidget(left_scroll)
        left_pane_layout.addWidget(self.add_external_btn)
        main_hbox.addWidget(left_pane_widget, 1)

        # --- Right Pane (Final Layout) ---
        right_pane_widget = QWidget()
        right_pane_layout = QVBoxLayout(right_pane_widget)
        right_pane_layout.setContentsMargins(0,0,0,0)

        self.final_list = FinalList(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        final_layout = QVBoxLayout(final_group); final_layout.addWidget(self.final_list)

        # Attachments Group Box
        self.attachment_group = QGroupBox("Attachments")
        attachment_layout = QHBoxLayout(self.attachment_group)
        attachment_layout.addWidget(QLabel("Include attachments from:"))
        for source_key in self.available_sources:
            cb = QCheckBox(source_key)
            if previous_attachment_sources and source_key in previous_attachment_sources:
                cb.setChecked(True)
            self.attachment_checkboxes[source_key] = cb
            attachment_layout.addWidget(cb)
        attachment_layout.addStretch()

        right_pane_layout.addWidget(final_group)
        right_pane_layout.addWidget(self.attachment_group)
        main_hbox.addWidget(right_pane_widget, 2)

        root.addLayout(main_hbox)

        # --- Dialog Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # --- Initial Population & Wiring ---
        self._populate_sources()
        self._wire_signals()

        if previous_layout:
            realized = ManualLogic.prepopulate(previous_layout, self.track_info)
            if realized:
                self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
                self.info_label.setVisible(True)
                for t in realized:
                    if not ManualLogic.is_blocked_video(t):
                        self.final_list.add_track_widget(t, preset=True)

    def _wire_signals(self):
        for lw in self.source_lists.values():
            lw.itemDoubleClicked.connect(self._on_double_clicked_source)
        self.external_list.itemDoubleClicked.connect(self._on_double_clicked_source)
        self.add_external_btn.clicked.connect(self._add_external_subtitles)

    def _populate_sources(self):
        for src_key, widget in self.source_lists.items():
            for t in self.track_info.get(src_key, []):
                widget.add_track_item(t, guard_block=ManualLogic.is_blocked_video(t))

    def _on_double_clicked_source(self, item):
        if not item: return
        td = item.data(Qt.UserRole)
        if td and not ManualLogic.is_blocked_video(td):
            self.final_list.add_track_widget(td, preset=('style_patch' in td))

    def _add_external_subtitles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select External Subtitle Files", "",
            "Subtitle Files (*.srt *.ass *.ssa *.sup);;All Files (*)"
        )
        if not files:
            return

        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {'ffprobe': shutil.which('ffprobe')}
        if not tool_paths['ffprobe']:
            QMessageBox.critical(self, "Error", "ffprobe tool not found in PATH.")
            return

        for file_path in files:
            try:
                out = runner.run([
                    'ffprobe', '-v', 'error', '-select_streams', 's:0',
                    '-show_entries', 'stream=codec_name,codec_long_name:stream_tags=language',
                    '-of', 'json', file_path
                ], tool_paths)

                if not out:
                    self.log_callback(f"[WARN] ffprobe found no subtitle stream in {Path(file_path).name}")
                    continue

                info = json.loads(out)['streams'][0]
                codec_id_map = {'subrip': 'S_TEXT/UTF8', 'ssa': 'S_TEXT/SSA', 'ass': 'S_TEXT/ASS', 'hdmv_pgs_subtitle': 'S_HDMV/PGS'}
                codec_id = codec_id_map.get(info.get('codec_name'), f"S_{info.get('codec_name', 'UNKNOWN').upper()}")

                track_data = {
                    'source': 'External', 'original_path': file_path, 'id': 0, # External tracks get a dummy ID
                    'type': 'subtitles', 'codec_id': codec_id,
                    'lang': info.get('tags', {}).get('language', 'und'),
                    'name': Path(file_path).stem
                }
                self.external_list.add_track_item(track_data, guard_block=False)
            except Exception as e:
                self.log_callback(f"[ERROR] Failed to process external file {file_path}: {e}")

        if self.external_list.count() > 0:
            self.ext_group.setVisible(True)

    def get_manual_layout_and_attachment_sources(self) -> Tuple[List[Dict], List[str]]:
        return self.manual_layout, self.attachment_sources

    def accept(self):
        widgets = []
        for i in range(self.final_list.count()):
            widgets.append(self.final_list.itemWidget(self.final_list.item(i)))

        ManualLogic.normalize_single_default_for_type(widgets, 'audio')
        ManualLogic.normalize_single_default_for_type(widgets, 'subtitles')
        ManualLogic.normalize_forced_subtitles(widgets)

        self.manual_layout = ManualLogic.build_layout_from_widgets(widgets)
        self.attachment_sources = [key for key, cb in self.attachment_checkboxes.items() if cb.isChecked()]

        super().accept()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up: self.final_list._move_by(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down: self.final_list._move_by(+1); event.accept(); return
        if event.key() == Qt.Key_Delete:
            item = self.final_list.currentItem()
            if item: self.final_list.takeItem(self.final_list.row(item)); event.accept(); return
        super().keyPressEvent(event)

    # The following methods are unchanged but included for completeness
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

            # For external files, the "source" is the file itself
            file_to_extract_from = source_file
            if track_data.get('source') == 'External':
                 # It doesn't need extraction, just a copy
                temp_path = temp_dir / Path(source_file).name
                shutil.copy2(source_file, temp_path)
                temp_path_str = str(temp_path)
            else:
                extracted = extract_tracks(file_to_extract_from, temp_dir, runner, tool_paths, 'edit', specific_tracks=[track_id])
                if not extracted:
                    self.log_callback(f"[ERROR] mkvextract failed for track ID {track_id} from {file_to_extract_from}")
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
