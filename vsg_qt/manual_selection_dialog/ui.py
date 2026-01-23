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
    QGroupBox, QScrollArea, QWidget, QMessageBox, QPushButton, QCheckBox, QFileDialog, QMenu
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
                 previous_attachment_sources: Optional[List[str]] = None,
                 previous_source_settings: Optional[Dict[str, Dict[str, Any]]] = None):
        super().__init__(parent)
        self.setWindowTitle("Manual Track Selection")
        self.setMinimumSize(1200, 700)

        self.track_info = track_info
        self.config = config
        self.log_callback = log_callback or (lambda msg: print(f"[Dialog] {msg}"))
        self.manual_layout: Optional[List[dict]] = None
        self.attachment_sources: List[str] = []
        self.source_settings: Dict[str, Dict[str, Any]] = previous_source_settings or {}
        self._style_edit_clipboard: Optional[Dict[str, Any]] = None  # Stores style_patch and font_replacements
        self.edited_widget = None
        self._source_group_boxes: Dict[str, QGroupBox] = {}  # Track group boxes for context menu

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

            # Add context menu for source settings (all sources including Source 1)
            group_box.setContextMenuPolicy(Qt.CustomContextMenu)
            group_box.customContextMenuRequested.connect(
                lambda pos, sk=source_key, gb=group_box: self._show_source_context_menu(pos, sk, gb)
            )
            self._source_group_boxes[source_key] = group_box

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

    def get_manual_layout_and_attachment_sources(self) -> Tuple[List[Dict], List[str], Dict[str, Dict[str, Any]]]:
        """Returns (manual_layout, attachment_sources, source_settings)."""
        return self.manual_layout, self.attachment_sources, self.source_settings

    def accept(self):
        # FIX: Call method on the logic instance
        self.manual_layout, self.attachment_sources = self._logic.get_final_layout_and_attachments()
        super().accept()

    def _show_source_context_menu(self, pos, source_key: str, group_box: QGroupBox):
        """Show context menu for source settings."""
        menu = QMenu(self)

        # Check if this source has non-default settings
        current = self.source_settings.get(source_key, {})
        if source_key == "Source 1":
            has_settings = bool(current.get('correlation_ref_track') is not None)
        else:
            has_settings = bool(
                current.get('correlation_source_track') is not None or
                current.get('use_source_separation')
            )

        # Configure correlation settings action
        config_action = menu.addAction("Configure Correlation Settings...")
        if has_settings:
            config_action.setText("Configure Correlation Settings... (Modified)")

        # Clear settings action (only if there are settings)
        clear_action = None
        if has_settings:
            menu.addSeparator()
            clear_action = menu.addAction("Clear Source Settings")

        action = menu.exec(group_box.mapToGlobal(pos))
        if action == config_action:
            self._open_source_settings_dialog(source_key)
        elif clear_action and action == clear_action:
            self._clear_source_settings(source_key)

    def _open_source_settings_dialog(self, source_key: str):
        """Open the source settings dialog for the specified source."""
        from vsg_qt.source_settings_dialog import SourceSettingsDialog

        # Get this source's audio tracks
        source_tracks = [t for t in self.track_info.get(source_key, []) if t.get('type') == 'audio']

        # Get Source 1's audio tracks
        source1_tracks = [t for t in self.track_info.get('Source 1', []) if t.get('type') == 'audio']

        dialog = SourceSettingsDialog(
            source_key=source_key,
            source_audio_tracks=source_tracks,
            source1_audio_tracks=source1_tracks,
            current_settings=self.source_settings.get(source_key),
            parent=self
        )

        if dialog.exec():
            settings = dialog.get_settings()
            # Store settings if any are non-default
            if dialog.has_non_default_settings():
                self.source_settings[source_key] = settings
                self.info_label.setText(f"Correlation settings configured for {source_key}.")
                self.info_label.setVisible(True)
            else:
                # Remove settings if all are default
                self.source_settings.pop(source_key, None)

            # Refresh badges for all tracks from this source
            self._refresh_badges_for_source(source_key)

    def _clear_source_settings(self, source_key: str):
        """Clear source settings for the specified source."""
        if source_key in self.source_settings:
            del self.source_settings[source_key]
            self.info_label.setText(f"Correlation settings cleared for {source_key}.")
            self.info_label.setVisible(True)

            # Refresh badges for all tracks from this source
            self._refresh_badges_for_source(source_key)

    def _refresh_badges_for_source(self, source_key: str):
        """Refresh badges and summary for all audio tracks from the specified source."""
        if not hasattr(self, 'final_list'):
            return

        for i in range(self.final_list.count()):
            widget = self.final_list.itemWidget(self.final_list.item(i))
            if widget and hasattr(widget, 'track_data') and hasattr(widget, 'logic'):
                track_source = widget.track_data.get('source', '')
                track_type = widget.track_data.get('type', '')
                # Refresh badges and summary for audio tracks from this source
                if track_source == source_key and track_type == 'audio':
                    widget.logic.refresh_badges()
                    widget.logic.refresh_summary()

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
                    '-show_entries', 'stream=codec_name,codec_long_name,codec_type:stream_tags=language',
                    '-of', 'json', file_path
                ], tool_paths)

                if not out:
                    self.log_callback(f"[WARN] ffprobe found no subtitle stream in {Path(file_path).name}")
                    continue

                streams = json.loads(out).get('streams', [])
                if not streams:
                    self.log_callback(f"[WARN] No subtitle streams found in {Path(file_path).name}")
                    continue

                info = streams[0]
                # Explicitly verify this is a subtitle stream
                if info.get('codec_type') != 'subtitle':
                    self.log_callback(f"[WARN] {Path(file_path).name} stream is not a subtitle (got: {info.get('codec_type')})")
                    continue
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

    def _prepare_ocr_preview(self, widget: TrackWidget) -> Optional[Tuple[str, str]]:
        """
        Run preview OCR on image-based subtitle for style editing.

        Uses fast EasyOCR to generate a temporary ASS file that can be edited
        in the style editor. Also generates SubtitleData JSON with full OCR
        metadata for future advanced features.

        Returns:
            Tuple of (json_path, ass_path) on success, or None on failure.
        """
        track_data = widget.track_data

        # Check if we already have a preview
        if track_data.get('ocr_preview_json') and track_data.get('user_modified_path'):
            existing_json = track_data['ocr_preview_json']
            existing_ass = track_data['user_modified_path']
            if Path(existing_json).exists() and Path(existing_ass).exists():
                self.log_callback("[Style Editor] Using existing OCR preview")
                return existing_json, existing_ass

        # Extract the image-based subtitle first
        extracted_path = self._extract_image_subtitle(widget)
        if not extracted_path:
            QMessageBox.warning(
                self, "OCR Preview",
                "Failed to extract image-based subtitle.\n\n"
                "Make sure the source file is accessible."
            )
            return None

        # Get language from track settings or default to English
        lang = track_data.get('custom_lang') or 'eng'

        # Get style_editor_temp directory
        output_dir = self.config.get_style_editor_temp_dir()

        self.log_callback(f"[Style Editor] Running preview OCR ({lang})...")

        # Import and run preview OCR
        from vsg_core.subtitles.ocr import run_preview_ocr

        result = run_preview_ocr(
            subtitle_path=extracted_path,
            lang=lang,
            output_dir=output_dir,
            log_callback=self.log_callback,
        )

        if result is None:
            QMessageBox.warning(
                self, "OCR Preview Failed",
                "Preview OCR failed to process the subtitle.\n\n"
                "Check the log for details. The subtitle may be empty or corrupted."
            )
            return None

        json_path, ass_path = result

        # Store paths in track_data
        widget.track_data['user_modified_path'] = ass_path
        widget.track_data['ocr_preview_json'] = json_path

        self.log_callback(f"[Style Editor] Preview ready: {Path(ass_path).name}")

        return json_path, ass_path

    def _extract_image_subtitle(self, widget: TrackWidget) -> Optional[str]:
        """
        Extract image-based subtitle (VobSub/PGS) from source file.

        Returns:
            Path to extracted .idx (VobSub) or .sup (PGS), or None on failure.
        """
        track_data = widget.track_data
        source_file = track_data.get('original_path')
        track_id = track_data.get('id')

        if not all([source_file, track_id is not None]):
            self.log_callback("[ERROR] Missing source file or track ID for OCR extraction.")
            return None

        runner = CommandRunner(self.config.settings, self.log_callback)
        tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}

        try:
            # Create temp directory for extraction
            temp_dir = Path(tempfile.gettempdir()) / f"vsg_ocr_preview_{Path(source_file).stem}_{track_id}_{int(time.time())}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            if track_data.get('source') == 'External':
                # External file - just copy it
                temp_path = temp_dir / Path(source_file).name
                shutil.copy2(source_file, temp_path)

                # For VobSub, handle .idx/.sub pair
                if temp_path.suffix.lower() == '.idx':
                    # .idx provided - also copy the .sub file
                    sub_file = Path(source_file).with_suffix('.sub')
                    if sub_file.exists():
                        shutil.copy2(sub_file, temp_dir / sub_file.name)
                    return str(temp_path)
                elif temp_path.suffix.lower() == '.sub':
                    # .sub provided - check for .idx and use that instead
                    idx_file = Path(source_file).with_suffix('.idx')
                    if idx_file.exists():
                        idx_temp = temp_dir / idx_file.name
                        shutil.copy2(idx_file, idx_temp)
                        return str(idx_temp)
                    # No .idx found, return .sub (OCR will fail gracefully)
                    return str(temp_path)

                return str(temp_path)
            else:
                # Extract from container
                extracted = extract_tracks(
                    source_file, temp_dir, runner, tool_paths,
                    'ocr_preview', specific_tracks=[track_id]
                )
                if not extracted:
                    self.log_callback(f"[ERROR] Failed to extract track {track_id} for OCR preview")
                    return None

                extracted_path = Path(extracted[0]['path'])

                # For VobSub, mkvextract creates both .idx and .sub files
                # extract_tracks returns .sub path, but OCR needs .idx
                if extracted_path.suffix.lower() == '.sub':
                    idx_path = extracted_path.with_suffix('.idx')
                    if idx_path.exists():
                        self.log_callback(f"[INFO] Using .idx file for VobSub OCR: {idx_path.name}")
                        return str(idx_path)

                return str(extracted_path)

        except Exception as e:
            self.log_callback(f"[ERROR] Exception during image subtitle extraction: {e}")
            return None

    def _copy_style_edits(self, widget: TrackWidget):
        """Copy style_patch and font_replacements from track_data (not raw style block)."""
        style_patch = widget.track_data.get('style_patch')
        font_replacements = widget.track_data.get('font_replacements')

        if not style_patch and not font_replacements:
            QMessageBox.warning(self, "Copy Style Edits", "No style edits found on this track.\n\nUse the Style Editor to make changes first.")
            return

        self._style_edit_clipboard = {
            'style_patch': style_patch.copy() if style_patch else {},
            'font_replacements': font_replacements.copy() if font_replacements else {},
            'source_name': widget.track_data.get('custom_name') or widget.track_data.get('description', 'Unknown')
        }

        # Build description of what was copied
        parts = []
        if style_patch:
            parts.append(f"{len(style_patch)} style patch(es)")
        if font_replacements:
            parts.append(f"{len(font_replacements)} font replacement(s)")

        self.info_label.setText(f"✅ Copied {', '.join(parts)} to clipboard.")
        self.info_label.setVisible(True)

    def _paste_style_edits(self, widget: TrackWidget):
        """Paste style_patch and font_replacements to target track with validation."""
        if not self._style_edit_clipboard:
            QMessageBox.warning(self, "Paste Style Edits", "Clipboard is empty.\n\nCopy style edits from another track first.")
            return

        style_patch = self._style_edit_clipboard.get('style_patch', {})
        font_replacements = self._style_edit_clipboard.get('font_replacements', {})

        if not style_patch and not font_replacements:
            QMessageBox.warning(self, "Paste Style Edits", "Clipboard contains no style edits.")
            return

        # Get target track's editable file path
        temp_path = self._ensure_editable_subtitle_path(widget)
        if not temp_path:
            QMessageBox.warning(self, "Error", "Could not prepare subtitle file for pasting.")
            return

        # Get available styles from target file for validation
        engine = StyleEngine(temp_path)
        available_styles = set(engine.get_style_names())

        # Validate and collect warnings
        warnings = []
        valid_style_patch = {}
        valid_font_replacements = {}

        # Validate style_patch
        for style_name, attrs in style_patch.items():
            if style_name in available_styles:
                valid_style_patch[style_name] = attrs
            else:
                warnings.append(f"Style patch: '{style_name}' not found")

        # Validate font_replacements
        for style_name, repl_data in font_replacements.items():
            if style_name in available_styles:
                valid_font_replacements[style_name] = repl_data
            else:
                warnings.append(f"Font replacement: '{style_name}' not found")

        if not valid_style_patch and not valid_font_replacements:
            QMessageBox.warning(
                self, "Paste Failed",
                "None of the styles in the clipboard exist in the target track.\n\n" +
                "Missing styles:\n" + "\n".join(warnings)
            )
            return

        # Apply valid patches to the file using SubtitleData
        from vsg_core.subtitles.data import SubtitleData
        from vsg_core.subtitles.operations.style_ops import apply_style_patch

        data = SubtitleData.from_file(temp_path)

        # Apply style patch
        if valid_style_patch:
            apply_style_patch(data, valid_style_patch)

        # Apply font replacements (update fontname attribute in styles)
        if valid_font_replacements:
            for style_name, repl_data in valid_font_replacements.items():
                new_font = repl_data.get('new_font_name')
                if new_font and style_name in data.styles:
                    data.styles[style_name].fontname = new_font

        # Save the modified file
        data.save_ass(temp_path)

        # Merge into target track's track_data
        existing_patch = widget.track_data.get('style_patch', {})
        existing_patch.update(valid_style_patch)
        if existing_patch:
            widget.track_data['style_patch'] = existing_patch

        existing_font_repl = widget.track_data.get('font_replacements', {})
        existing_font_repl.update(valid_font_replacements)
        if existing_font_repl:
            widget.track_data['font_replacements'] = existing_font_repl

        # Show result
        applied_parts = []
        if valid_style_patch:
            applied_parts.append(f"{len(valid_style_patch)} style patch(es)")
        if valid_font_replacements:
            applied_parts.append(f"{len(valid_font_replacements)} font replacement(s)")

        result_msg = f"✅ Applied {', '.join(applied_parts)}."
        if warnings:
            result_msg += f" ({len(warnings)} skipped)"
            # Store warnings for badge display
            widget.track_data['pasted_warnings'] = warnings

        self.info_label.setText(result_msg)
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
        # Use global config setting for skip_frame_validation
        generated_track['skip_frame_validation'] = self.config.settings.get('duration_align_skip_validation_generated_tracks', True)

        # Update the track name (keep original description - the 🔗 Generated badge shows it's generated)
        generated_track['name'] = filter_config['name']
        generated_track['custom_name'] = filter_config['name']

        # Add the generated track to the FinalList
        self.final_list.add_track_widget(generated_track)

        # Show confirmation
        name_display = f"'{filter_config['name']}' " if filter_config['name'] else ""
        self.info_label.setText(f"✅ Generated track {name_display}created successfully.")
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
            'name': track_data.get('custom_name', track_data.get('name', ''))
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
        # Use global config setting for skip_frame_validation
        track_data['skip_frame_validation'] = self.config.settings.get('duration_align_skip_validation_generated_tracks', True)
        track_data['name'] = filter_config['name']
        track_data['custom_name'] = filter_config['name']

        # Refresh the widget to show updated configuration
        if hasattr(widget, 'logic'):
            widget.logic.refresh_badges()
            widget.logic.refresh_summary()

        # Show confirmation
        name_display = f"'{filter_config['name']}' " if filter_config['name'] else ""
        self.info_label.setText(f"✅ Generated track {name_display}updated successfully.")
        self.info_label.setVisible(True)

    def _launch_style_editor(self, widget: TrackWidget):
        track_data = widget.track_data
        ref_video_path = self.track_info.get('Source 1', [{}])[0].get('original_path')
        if not ref_video_path:
            QMessageBox.warning(self, "Error", "Reference video path is missing.")
            return

        # Check if this is an OCR track (image-based subtitle with OCR enabled)
        codec_id = track_data.get('codec_id', '').upper()
        # Read perform_ocr from checkbox widget (track_data may not be synced after Track Settings dialog)
        perform_ocr = widget.cb_ocr.isChecked() if hasattr(widget, 'cb_ocr') else track_data.get('perform_ocr', False)
        is_image_based = 'VOBSUB' in codec_id or 'PGS' in codec_id or 'HDMV' in codec_id
        is_ocr_track = perform_ocr and is_image_based

        # Check: Image-based subtitle without OCR enabled
        if is_image_based and not perform_ocr:
            QMessageBox.information(
                self, "OCR Required",
                "This is an image-based subtitle (VobSub/PGS) which cannot be "
                "edited directly.\n\n"
                "To use the Style Editor, enable 'Perform OCR' in Track Settings first. "
                "This will convert the images to editable text."
            )
            return

        if is_ocr_track:
            # OCR path: Run preview OCR with progress dialog
            self.log_callback("[Style Editor] Taking OCR path...")
            result = self._prepare_ocr_preview_with_progress(widget)
            if result is None:
                self.log_callback("[Style Editor] OCR preview returned None")
                return
            json_path, editable_sub_path = result
            self.log_callback(f"[Style Editor] OCR result: json={json_path}, ass={editable_sub_path}")
            widget.track_data['ocr_preview_json'] = json_path
        else:
            self.log_callback("[Style Editor] Taking non-OCR path (extracting subtitle)...")
            editable_sub_path = self._ensure_editable_subtitle_path(widget)
            self.log_callback(f"[Style Editor] Extracted path: {editable_sub_path}")

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
                self.log_callback(f"[INFO] Extracted {len(extracted_fonts)} font(s) for preview.")
            fonts_dir = str(font_temp_dir)
        except Exception as e:
            self.log_callback(f"[WARN] Could not extract fonts: {e}")

        # Pass existing font replacements if any
        existing_font_replacements = track_data.get('font_replacements')
        editor = StyleEditorDialog(
            ref_video_path, editable_sub_path,
            fonts_dir=fonts_dir,
            existing_font_replacements=existing_font_replacements,
            parent=self
        )
        if editor.exec():
            widget.track_data['style_patch'] = editor.get_style_patch()
            # Store font replacements if any were configured
            font_replacements = editor.get_font_replacements()
            if font_replacements:
                widget.track_data['font_replacements'] = font_replacements
            elif 'font_replacements' in widget.track_data:
                # Clear if no replacements (user removed them)
                del widget.track_data['font_replacements']
            self.edited_widget = widget
            widget.logic.refresh_badges()
            widget.logic.refresh_summary()

    def _prepare_ocr_preview_with_progress(self, widget: TrackWidget) -> Optional[Tuple[str, str]]:
        """
        Run preview OCR with a progress dialog.

        Shows a modal progress dialog while OCR runs, blocking the UI
        but showing progress updates.

        Returns:
            Tuple of (json_path, ass_path) on success, or None on failure.
        """
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt

        track_data = widget.track_data

        # Check if we already have a preview
        if track_data.get('ocr_preview_json') and track_data.get('user_modified_path'):
            existing_json = track_data['ocr_preview_json']
            existing_ass = track_data['user_modified_path']
            if Path(existing_json).exists() and Path(existing_ass).exists():
                self.log_callback("[Style Editor] Using existing OCR preview")
                return existing_json, existing_ass

        # Extract the image-based subtitle first
        extracted_path = self._extract_image_subtitle(widget)
        if not extracted_path:
            QMessageBox.warning(
                self, "OCR Preview",
                "Failed to extract image-based subtitle.\n\n"
                "Make sure the source file is accessible."
            )
            return None

        # Get language and output directory
        lang = track_data.get('custom_lang') or 'eng'
        output_dir = self.config.get_style_editor_temp_dir()

        # Create progress dialog
        progress = QProgressDialog("Running OCR preview...", "Cancel", 0, 100, self)
        progress.setWindowTitle("OCR Preview")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        # Track progress via log callback
        result_holder = [None]  # Use list to allow modification in nested function
        canceled = [False]

        def progress_log(msg: str):
            if canceled[0]:
                return
            self.log_callback(msg)
            # Extract progress percentage from OCR messages
            if "%" in msg and "[Preview OCR]" in msg:
                try:
                    pct_str = msg.split("(")[-1].rstrip("%)")
                    pct = int(pct_str)
                    progress.setValue(pct)
                    # Extract message for label
                    msg_part = msg.split("]")[1].split("(")[0].strip()
                    progress.setLabelText(f"OCR Preview: {msg_part}")
                except (ValueError, IndexError):
                    pass
            # Process events to update UI
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            if progress.wasCanceled():
                canceled[0] = True

        # Run preview OCR (blocking but with progress updates)
        from vsg_core.subtitles.ocr import run_preview_ocr

        self.log_callback(f"[Style Editor] Running preview OCR ({lang})...")

        result = run_preview_ocr(
            subtitle_path=extracted_path,
            lang=lang,
            output_dir=output_dir,
            log_callback=progress_log,
        )

        progress.close()
        progress.deleteLater()  # Ensure proper cleanup

        if canceled[0]:
            self.log_callback("[Style Editor] OCR preview canceled")
            return None

        if result is None:
            QMessageBox.warning(
                self, "OCR Preview Failed",
                "Preview OCR failed to process the subtitle.\n\n"
                "Check the log for details."
            )
            return None

        json_path, ass_path = result

        # Store paths in track_data
        widget.track_data['user_modified_path'] = ass_path
        widget.track_data['ocr_preview_json'] = json_path

        self.log_callback(f"[Style Editor] Preview ready: {Path(ass_path).name}")

        return json_path, ass_path
