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

        # FIX: Instantiate the logic controller
        self._logic = ManualLogic(self)

        self.source_lists: Dict[str, SourceList] = {}
        self.attachment_checkboxes: Dict[str, QCheckBox] = {}
        self.available_sources = sorted(track_info.keys(), key=lambda k: int(re.search(r'\d+', k).group()))

        self._build_ui(previous_attachment_sources)
        self._wire_signals()
        self._populate_sources()

        if previous_layout:
            self.info_label.setText("✅ Pre-populated with the layout from the previous file.")
            self.info_label.setVisible(True)
            # FIX: Call the prepopulate method on the logic instance
            self._logic.prepopulate_from_layout(previous_layout)

    def _build_ui(self, previous_attachment_sources: Optional[List[str]] = None):
        root = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setVisible(False)
        self.info_label.setStyleSheet("color: green; font-weight: bold;")
        root.addWidget(self.info_label, 0, Qt.AlignCenter)

        main_hbox = QHBoxLayout()
        left_pane_widget = QWidget()
        left_pane_layout = QVBoxLayout(left_pane_widget); left_pane_layout.setContentsMargins(0,0,0,0)
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_widget = QWidget()
        self.left_vbox = QVBoxLayout(left_widget); self.left_vbox.setContentsMargins(0,0,0,0)

        for source_key in self.available_sources:
            path_name = Path(self.track_info[source_key][0]['original_path']).name if self.track_info[source_key] else "N/A"
            title = f"{source_key} Tracks ('{path_name}')"
            if source_key == "Source 1": title = f"{source_key} (Reference) Tracks ('{path_name}')"

            source_list_widget = SourceList(dialog=self)
            self.source_lists[source_key] = source_list_widget
            group_box = QGroupBox(title)
            group_layout = QVBoxLayout(group_box); group_layout.addWidget(source_list_widget)
            self.left_vbox.addWidget(group_box)

        self.external_list = SourceList(dialog=self)
        self.ext_group = QGroupBox("External Subtitles"); ext_layout = QVBoxLayout(self.ext_group)
        ext_layout.addWidget(self.external_list); self.ext_group.setVisible(False)
        self.left_vbox.addWidget(self.ext_group)
        self.left_vbox.addStretch(1)
        left_scroll.setWidget(left_widget)

        self.add_external_btn = QPushButton("Add External Subtitle(s)...")
        left_pane_layout.addWidget(left_scroll)
        left_pane_layout.addWidget(self.add_external_btn)
        main_hbox.addWidget(left_pane_widget, 1)

        right_pane_widget = QWidget()
        right_pane_layout = QVBoxLayout(right_pane_widget); right_pane_layout.setContentsMargins(0,0,0,0)
        self.final_list = FinalList(self)
        final_group = QGroupBox("Final Output (Drag to reorder)")
        final_layout = QVBoxLayout(final_group); final_layout.addWidget(self.final_list)

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

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _wire_signals(self):
        for lw in self.source_lists.values():
            lw.itemDoubleClicked.connect(self._on_double_clicked_source)
        self.external_list.itemDoubleClicked.connect(self._on_double_clicked_source)
        self.add_external_btn.clicked.connect(self._add_external_subtitles)

    def _populate_sources(self):
        for src_key, widget in self.source_lists.items():
            for t in self.track_info.get(src_key, []):
                # FIX: Call method on the logic instance
                widget.add_track_item(t, guard_block=self._logic.is_blocked_video(t))

    def _on_double_clicked_source(self, item):
        if not item: return
        td = item.data(Qt.UserRole)
        # FIX: Call method on the logic instance
        if td and not self._logic.is_blocked_video(td):
            self.final_list.add_track_widget(td, preset=('style_patch' in td))

    def get_manual_layout_and_attachment_sources(self) -> Tuple[List[Dict], List[str]]:
        return self.manual_layout, self.attachment_sources

    def accept(self):
        # FIX: Call method on the logic instance
        self.manual_layout, self.attachment_sources = self._logic.get_final_layout_and_attachments()
        super().accept()

    # ... other methods like _add_external_subtitles, keyPressEvent, etc remain the same ...
    # They are omitted here for brevity but should be kept in your file.
    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up: self.final_list._move_by(-1); event.accept(); return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down: self.final_list._move_by(+1); event.accept(); return
        if event.key() == Qt.Key_Delete:
            item = self.final_list.currentItem()
            if item: self.final_list.takeItem(self.final_list.row(item)); event.accept(); return
        super().keyPressEvent(event)

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
                    'source': 'External', 'original_path': file_path, 'id': 0,
                    'type': 'subtitles', 'codec_id': codec_id,
                    'lang': info.get('tags', {}).get('language', 'und'),
                    'name': Path(file_path).stem
                }
                self.external_list.add_track_item(track_data, guard_block=False)
            except Exception as e:
                self.log_callback(f"[ERROR] Failed to process external file {file_path}: {e}")

        if self.external_list.count() > 0:
            self.ext_group.setVisible(True)

    def _ensure_editable_subtitle_path(self, widget: TrackWidget) -> Optional[str]:
        track_data = widget.track_data
        if track_data.get('user_modified_path'):
            return track_data['user_modified_path']

        source_file = track_data.get('original_path')
        track_id = track_data.get('id')
        if not all([source_file, track_id is not None, self.config]):
            self.log_callback("[ERROR] Missing info for subtitle extraction.")
            return None

        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        try:
            temp_dir = Path(tempfile.gettempdir()) / f"vsg_style_edit_{Path(source_file).stem}_{track_id}_{int(time.time())}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            if track_data.get('source') == 'External':
                temp_path = temp_dir / Path(source_file).name
                shutil.copy2(source_file, temp_path)
                temp_path_str = str(temp_path)
            else:
                extracted = extract_tracks(source_file, temp_dir, runner, tool_paths, 'edit', specific_tracks=[track_id])
                if not extracted:
                    self.log_callback(f"[ERROR] mkvextract failed for track ID {track_id}")
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

    def _create_generated_track(self, source_track: dict):
        """
        Create a generated track by filtering styles from a source subtitle track.

        Args:
            source_track: The source track dictionary to filter from
        """
        from vsg_qt.generated_track_dialog import GeneratedTrackDialog

        # Extract the subtitle track first so we can read its styles
        source_file = source_track.get('original_path')
        track_id = source_track.get('id')
        is_external = source_track.get('source') == 'External'

        if not source_file or (track_id is None and not is_external):
            QMessageBox.warning(self, "Error", "Missing track information.")
            return

        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        try:
            # Extract subtitle to temp location
            temp_dir = Path(tempfile.gettempdir()) / f"vsg_gen_track_{Path(source_file).stem}_{track_id}_{int(time.time())}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            if is_external:
                temp_sub_path = temp_dir / Path(source_file).name
                shutil.copy2(source_file, temp_sub_path)
            else:
                extracted = extract_tracks(source_file, temp_dir, runner, tool_paths, 'temp', specific_tracks=[track_id])
                if not extracted:
                    QMessageBox.warning(self, "Error", f"Failed to extract subtitle track {track_id}")
                    return
                temp_sub_path = Path(extracted[0]['path'])

            # Convert SRT to ASS if needed
            if temp_sub_path.suffix.lower() == '.srt':
                temp_sub_path = Path(convert_srt_to_ass(str(temp_sub_path), runner, tool_paths))

            # Create a modified source_track with the extracted path for the dialog
            source_track_for_dialog = dict(source_track)
            source_track_for_dialog['original_path'] = str(temp_sub_path)

            # Open the style selection dialog with the extracted subtitle
            dialog = GeneratedTrackDialog(source_track_for_dialog, parent=self)
            if not dialog.exec():
                # Clean up temp file
                shutil.rmtree(temp_dir, ignore_errors=True)
                return  # User cancelled

            filter_config = dialog.get_filter_config()
            if not filter_config:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to extract subtitle for style analysis:\n{str(e)}")
            self.log_callback(f"[ERROR] Exception extracting subtitle: {e}")
            import traceback
            self.log_callback(traceback.format_exc())
            return
        finally:
            # Clean up temp extraction
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)

        # Create a new track dictionary based on the source track
        generated_track = dict(source_track)

        # Mark it as generated and store filter configuration
        generated_track['is_generated'] = True
        generated_track['generated_source_track_id'] = source_track.get('id')
        generated_track['generated_source_path'] = source_track.get('original_path')
        generated_track['generated_filter_mode'] = filter_config['mode']
        generated_track['generated_filter_styles'] = filter_config['styles']
        generated_track['generated_original_style_list'] = filter_config.get('original_style_list', [])  # Complete style list for validation
        generated_track['generated_verify_only_lines_removed'] = True

        # Update the track name (keep original description - the 🔗 Generated badge shows it's generated)
        generated_track['name'] = filter_config['name']
        generated_track['custom_name'] = filter_config['name']

        # Add the generated track to the FinalList
        self.final_list.add_track_widget(generated_track)

        # Show confirmation
        self.info_label.setText(f"✅ Generated track '{filter_config['name']}' created successfully.")
        self.info_label.setVisible(True)

    def _edit_generated_track(self, widget: TrackWidget, item):
        """
        Edit an existing generated track's filter configuration.

        Args:
            widget: The track widget to edit
            item: The list item containing the widget
        """
        from vsg_qt.generated_track_dialog import GeneratedTrackDialog

        track_data = widget.track_data
        if not track_data.get('is_generated'):
            QMessageBox.warning(self, "Error", "This is not a generated track.")
            return

        # Get current configuration from track_data
        existing_config = {
            'mode': track_data.get('generated_filter_mode', 'exclude'),
            'styles': track_data.get('generated_filter_styles', []),
            'name': track_data.get('custom_name', track_data.get('name', 'Generated Track'))
        }

        # Get the source track information
        source_track_id = track_data.get('generated_source_track_id')
        source_path = track_data.get('generated_source_path')
        source_key = track_data.get('source')

        if not source_path or source_track_id is None:
            QMessageBox.warning(self, "Error", "Missing source track information.")
            return

        # Extract the source subtitle so we can read its current styles
        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        try:
            # Extract subtitle to temp location
            temp_dir = Path(tempfile.gettempdir()) / f"vsg_gen_edit_{Path(source_path).stem}_{source_track_id}_{int(time.time())}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            extracted = extract_tracks(source_path, temp_dir, runner, tool_paths, 'temp', specific_tracks=[source_track_id])
            if not extracted:
                QMessageBox.warning(self, "Error", f"Failed to extract source subtitle track {source_track_id}")
                return
            temp_sub_path = Path(extracted[0]['path'])

            # Convert SRT to ASS if needed
            if temp_sub_path.suffix.lower() == '.srt':
                temp_sub_path = Path(convert_srt_to_ass(str(temp_sub_path), runner, tool_paths))

            # Create a source_track dict for the dialog
            source_track_for_dialog = {
                'source': source_key,
                'id': source_track_id,
                'description': f"Source Track {source_track_id}",
                'original_path': str(temp_sub_path)
            }

            # Open the dialog with existing configuration
            dialog = GeneratedTrackDialog(source_track_for_dialog, existing_config=existing_config, parent=self)
            if not dialog.exec():
                # Clean up temp file
                shutil.rmtree(temp_dir, ignore_errors=True)
                return  # User cancelled

            filter_config = dialog.get_filter_config()
            if not filter_config:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to extract subtitle for editing:\n{str(e)}")
            self.log_callback(f"[ERROR] Exception extracting subtitle: {e}")
            import traceback
            self.log_callback(traceback.format_exc())
            return
        finally:
            # Clean up temp extraction
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)

        # Update the track_data with new configuration
        track_data['generated_filter_mode'] = filter_config['mode']
        track_data['generated_filter_styles'] = filter_config['styles']
        track_data['generated_original_style_list'] = filter_config.get('original_style_list', [])
        track_data['name'] = filter_config['name']
        track_data['custom_name'] = filter_config['name']

        # Refresh the widget to show updated configuration
        if hasattr(widget, 'logic'):
            widget.logic.refresh_badges()
            widget.logic.refresh_summary()

        # Show confirmation
        self.info_label.setText(f"✅ Generated track '{filter_config['name']}' updated successfully.")
        self.info_label.setVisible(True)

    def _launch_style_editor(self, widget: TrackWidget):
        track_data = widget.track_data
        ref_video_path = self.track_info.get('Source 1', [{}])[0].get('original_path')
        if not ref_video_path:
            QMessageBox.warning(self, "Error", "Reference video path is missing.")
            return

        editable_sub_path = self._ensure_editable_subtitle_path(widget)
        if not editable_sub_path:
            QMessageBox.critical(self, "Error", "Failed to prepare the subtitle file.")
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
            widget.logic.refresh_badges()
            widget.logic.refresh_summary()
