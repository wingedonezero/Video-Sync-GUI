# vsg_qt/main_window/controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import tempfile
import zipfile
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QTimer

from vsg_core.config import AppConfig
from vsg_core.job_discovery import discover_jobs
from vsg_core.io.runner import CommandRunner
from vsg_core.extraction.tracks import get_track_info_for_dialog
from vsg_core.subtitles.style_engine import StyleEngine
from vsg_qt.worker import JobWorker
from vsg_qt.manual_selection_dialog import ManualSelectionDialog
from vsg_qt.options_dialog import OptionsDialog

from .helpers import (
    generate_track_signature,
    materialize_layout,
    layout_to_template,
    get_style_signature, # NEW: Import new signature logic
)

class MainController:
    def __init__(self, view: "MainWindow"):
        self.v = view
        self.config: AppConfig = view.config
        self.worker: Optional[JobWorker] = None
        # The cache will now store signature -> patch dictionary
        self.style_patch_cache: Dict[str, Dict] = {}

    def open_options_dialog(self):
        dialog = OptionsDialog(self.config, self.v)
        if dialog.exec():
            self.config.save()
            self.append_log('Settings saved.')

    def apply_config_to_ui(self):
        v = self.v
        v.ref_input.setText(self.config.get('last_ref_path', ''))
        v.sec_input.setText(self.config.get('last_sec_path', ''))
        v.ter_input.setText(self.config.get('last_ter_path', ''))
        v.archive_logs_check.setChecked(self.config.get('archive_logs', True))
        v.auto_apply_strict_check.setChecked(self.config.get('auto_apply_strict', False))

    def save_ui_to_config(self):
        v = self.v
        self.config.set('last_ref_path', v.ref_input.text())
        self.config.set('last_sec_path', v.sec_input.text())
        self.config.set('last_ter_path', v.ter_input.text())
        self.config.set('archive_logs', v.archive_logs_check.isChecked())
        self.config.set('auto_apply_strict', v.auto_apply_strict_check.isChecked())
        self.config.save()

    def append_log(self, message: str):
        v = self.v
        v.log_output.append(message)
        if self.config.get('log_autoscroll', True):
            v.log_output.verticalScrollBar().setValue(v.log_output.verticalScrollBar().maximum())

    def update_progress(self, value: float):
        self.v.progress_bar.setValue(int(value * 100))

    def update_status(self, message: str):
        self.v.status_label.setText(message)

    def browse_for_path(self, line_edit, caption: str):
        from PySide6.QtWidgets import QFileDialog
        dialog = QFileDialog(self.v, caption)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if self.config.get('last_ref_path'):
            start_dir = str(Path(self.config.get('last_ref_path')).parent)
            dialog.setDirectory(start_dir)
        if dialog.exec():
            line_edit.setText(dialog.selectedFiles()[0])

    def start_batch(self, and_merge: bool):
        self.save_ui_to_config()
        ref_path_str = self.v.ref_input.text().strip()
        try:
            initial_jobs = discover_jobs(
                ref_path_str, self.v.sec_input.text().strip() or None, self.v.ter_input.text().strip() or None
            )
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self.v, "Job Discovery Error", str(e)); return
        if not initial_jobs:
            QMessageBox.information(self.v, "No Jobs Found", "No valid jobs could be found."); return

        final_jobs = initial_jobs
        if and_merge:
            self.style_patch_cache.clear() # Clear cache for new batch
            processed_jobs = []
            last_manual_layout = None
            last_track_signature = None
            auto_apply_enabled = self.v.auto_apply_check.isChecked()
            strict_match = self.v.auto_apply_strict_check.isChecked()

            tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}
            if not all(tool_paths.values()):
                QMessageBox.critical(self.v, "Tool Not Found", "A required tool (mkvmerge, mkvextract, ffmpeg) was not found in your PATH."); return

            runner = CommandRunner(self.config.settings, self.append_log)

            for i, job_data in enumerate(initial_jobs):
                self.v.status_label.setText(f"Scanning {Path(job_data['ref']).name}...")
                try:
                    track_info = get_track_info_for_dialog(job_data['ref'], job_data.get('sec'), job_data.get('ter'), runner, tool_paths)
                except Exception as e:
                    QMessageBox.warning(self.v, "Scan Failed", f"Could not analyze tracks for {Path(job_data['ref']).name}:\n{e}"); return

                # NEW: Centralized styling step. This runs for EVERY job.
                self._apply_patches_for_job(track_info)

                current_signature = generate_track_signature(track_info, strict=strict_match)
                current_layout = None

                if (auto_apply_enabled and last_manual_layout is not None and
                    last_track_signature is not None and current_signature == last_track_signature):
                    # Auto-apply will now correctly carry over the 'style_patch'
                    current_layout = materialize_layout(last_manual_layout, track_info)
                    self.append_log(f"Auto-applied previous layout to {Path(job_data['ref']).name}...")
                else:
                    layout_to_carry_over = last_manual_layout if last_track_signature and current_signature == last_track_signature else None

                    dialog = ManualSelectionDialog(track_info, parent=self.v,
                                                   previous_layout=layout_to_carry_over,
                                                   log_callback=self.append_log)

                    if dialog.exec():
                        current_layout = dialog.get_manual_layout()
                        # After user interaction, check if the editor was used and update the cache
                        self._update_style_cache(current_layout, track_info)
                    else:
                        self.append_log("Batch run cancelled by user."); self.v.status_label.setText("Ready"); return

                if current_layout:
                    job_data['manual_layout'] = current_layout
                    processed_jobs.append(job_data)
                    last_manual_layout = layout_to_template(current_layout)
                    last_track_signature = current_signature
                else:
                    self.append_log(f"Job '{Path(job_data['ref']).name}' was skipped.")
                    last_manual_layout = None; last_track_signature = None

            final_jobs = processed_jobs

        if not final_jobs:
            self.v.status_label.setText("Ready"); self.append_log("No jobs to run after user selection."); return

        output_dir = self.config.get('output_folder')
        is_batch = Path(ref_path_str).is_dir() and len(final_jobs) > 1
        if is_batch:
            output_dir = str(Path(output_dir) / Path(ref_path_str).name)

        self.v.log_output.clear(); self.v.status_label.setText(f'Starting batch of {len(final_jobs)} jobs…')
        self.v.progress_bar.setValue(0); self.v.sec_delay_label.setText('—'); self.v.ter_delay_label.setText('—')

        self.worker = JobWorker(self.config.settings, final_jobs, and_merge, output_dir)
        self.worker.signals.log.connect(self.append_log)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.status.connect(self.update_status)
        self.worker.signals.finished_job.connect(self.job_finished)
        self.worker.signals.finished_all.connect(self.batch_finished)

        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(self.worker)

    def _apply_patches_for_job(self, track_info: Dict[str, List[Dict]]):
        """Finds matching patches in the cache and injects them into the track_info."""
        if not self.style_patch_cache:
            return

        for source in ('REF', 'SEC', 'TER'):
            subs_in_source = [t for t in track_info.get(source, []) if t.get('type') == 'subtitles']
            for i, track in enumerate(subs_in_source):
                signature = get_style_signature(track, i)
                if signature in self.style_patch_cache:
                    track['style_patch'] = self.style_patch_cache[signature]
                    self.append_log(f"[Style] Found and queued patch for track '{signature}'.")

    def _update_style_cache(self, layout: List[dict], track_info: Dict[str, List[Dict]]):
        """
        After the dialog closes, find which track was edited (if any), get its
        patch and signature, and store it in the cache.
        """
        edited_track = None
        style_patch = None
        for track in layout:
            if track.get('style_patch'):
                edited_track = track
                style_patch = track['style_patch']
                break

        if not edited_track or not style_patch:
            return

        # We need to find the track's index for the signature fallback
        source_list = [t for t in track_info.get(edited_track['source'], []) if t.get('type') == 'subtitles']
        idx = -1
        for i, t in enumerate(source_list):
            if t['id'] == edited_track['id']:
                idx = i
                break

        signature = get_style_signature(edited_track, idx)
        if signature:
            self.style_patch_cache[signature] = style_patch
            self.append_log(f"[Style] Saved patch for '{signature}' for batch use.")

    def job_finished(self, result: dict):
        if 'delay_sec' in result: self.v.sec_delay_label.setText(f"{result['delay_sec']} ms" if result['delay_sec'] is not None else "—")
        if 'delay_ter' in result: self.v.ter_delay_label.setText(f"{result['delay_ter']} ms" if result['delay_ter'] is not None else "—")
        name = result.get('name', ''); status = result.get('status', 'Unknown')
        if status == 'Failed': self.append_log(f"--- Job Summary for {name}: FAILED ---")
        else: self.append_log(f"--- Job Summary for {name}: {status} ---")

    def batch_finished(self, all_results: list):
        self.update_status(f'All {len(all_results)} jobs finished.'); self.v.progress_bar.setValue(100)
        output_dir = None
        if all_results:
            for result in all_results:
                if result.get('status') in ['Merged', 'Analyzed'] and 'output' in result and result['output']:
                    output_dir = Path(result['output']).parent; break
        ref_path_str = self.v.ref_input.text().strip()
        is_batch = Path(ref_path_str).is_dir() and len(all_results) > 1
        if is_batch and self.v.archive_logs_check.isChecked() and output_dir:
            QTimer.singleShot(0, lambda: self._archive_logs_for_batch(output_dir))

        QMessageBox.information(self.v, "Batch Complete", f"Finished processing {len(all_results)} jobs.")

    def _archive_logs_for_batch(self, output_dir: Path):
        self.append_log(f"--- Archiving logs in {output_dir} ---")
        try:
            log_files = list(output_dir.glob('*.log'))
            if not log_files: self.append_log("No log files found to archive."); return
            zip_path = output_dir / f"{output_dir.name}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for log_file in log_files: zipf.write(log_file, arcname=log_file.name); self.append_log(f"  + Added {log_file.name}")
            for log_file in log_files: log_file.unlink()
            self.append_log(f"Successfully created log archive: {zip_path}")
        except Exception as e:
            self.append_log(f"[ERROR] Failed to archive logs: {e}")

    def on_close(self):
        self.save_ui_to_config()
