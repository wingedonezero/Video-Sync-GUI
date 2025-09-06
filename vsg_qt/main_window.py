# vsg_qt/main_window.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from collections import Counter

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QMessageBox
)
from PySide6.QtCore import QThreadPool, QTimer

from vsg_qt.options_dialog import OptionsDialog
from vsg_qt.worker import JobWorker
from vsg_core.config import AppConfig
from vsg_core.job_discovery import discover_jobs
from vsg_core.io.runner import CommandRunner
from vsg_core.extraction.tracks import get_track_info_for_dialog
from vsg_qt.manual_selection_dialog import ManualSelectionDialog

# new modular panels
from vsg_qt.mainloop import *  # nope — keep things simple!
# Real imports:
from vsg_qt.mainwindow import (
    InputsPanel, ManualBehaviorPanel, ActionsPanel, StatusPanel, ResultsPanel, LogPanel
)

class MainWindow(QMainWindow):
    """Main application window (modular controller)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video/Audio Sync & Merge - PySide6 Edition')
        self.setGeometry(100, 100, 1000, 600)

        self.config = AppConfig()
        self.thread_pool = QThreadPool()
        self.worker = None

        # --- compose UI ---
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # header row: Settings…
        header = QHBoxLayout()
        self.btn_settings = QPushButton("Settings…")
        self.btn_settings.clicked.connect(self.open_options_dialog)
        header.addWidget(self.btn_settings)
        header.addStretch(1)
        root.addLayout(header)

        # panels
        self.inputs = InputsPanel()
        self.manual = ManualBehaviorPanel()
        self.actions = ActionsPanel()
        self.status = StatusPanel()
        self.results = ResultsPanel()
        self.log = LogPanel()

        root.addWidget(self.inputs)
        root.addWidget(self.manual)
        root.addWidget(self.actions)
        root.addLayout(self._status_row())  # status inline row
        root.addWidget(self.results)
        root.addWidget(self.log)

        # wiring
        self.actions.analyze_only.connect(lambda: self.start_batch(and_merge=False))
        self.actions.analyze_merge.connect(lambda: self.start_batch(and_merge=True))

        self.apply_config_to_ui()

    # status row embeds StatusPanel (to match old layout)
    def _status_row(self):
        # StatusPanel is already a row-like widget; wrap in HBox for spacing consistency
        hb = QHBoxLayout()
        hb.addWidget(self.status)
        return hb

    # ---------- options ----------
    def open_options_dialog(self):
        dialog = OptionsDialog(self.config, self)
        if dialog.exec():
            self.config.save()
            self.append_log('Settings saved.')

    # ---------- config sync ----------
    def apply_config_to_ui(self):
        self.inputs.set_values(
            self.config.get('last_ref_path', ''),
            self.config.get('last_sec_path', ''),
            self.config.get('last_ter_path', ''),
        )
        self.actions.set_archive(self.config.get('archive_logs', True))
        self.manual.set_strict(self.config.get('auto_apply_strict', False))
        # note: manual auto-apply is *not* persisted previously; keep default unchecked
        # (If you decide to persist later, wire here)
        # self.manual.set_auto_apply(self.config.get('auto_apply_enabled', False))

    def save_ui_to_config(self):
        ref, sec, ter = self.inputs.get_values()
        self.config.set('last_ref_path', ref or '')
        self.config.set('last_sec_path', sec or '')
        self.config.set('last_ter_path', ter or '')
        self.config.set('archive_logs', self.actions.get_archive())
        self.config.set('auto_apply_strict', self.manual.get_strict())
        self.config.save()

    # ---------- signature helpers (unchanged semantics) ----------
    def _generate_track_signature(self, track_info, strict=False):
        if not strict:
            return Counter(
                f"{t['source']}_{t['type']}"
                for source_list in track_info.values() for t in source_list
            )
        return Counter(
            f"{t['source']}_{t['type']}_{(t.get('lang') or 'und').lower()}_{(t.get('codec_id') or '').lower()}"
            for source_list in track_info.values() for t in source_list
        )

    def _materialize_layout(self, abstract_layout, track_info):
        pools = {'REF': [], 'SEC': [], 'TER': []}
        for src in pools.keys():
            pools[src] = [t for t in track_info.get(src, [])]
        counters = {}
        realized = []
        for item in abstract_layout or []:
            src = item.get('source'); ttype = item.get('type')
            idx = counters.get((src, ttype), 0)
            matching = [t for t in pools.get(src, []) if t.get('type') == ttype]
            if idx < len(matching):
                base = matching[idx].copy()
                base.update({
                    'is_default': item.get('is_default', False),
                    'is_forced_display': item.get('is_forced_display', False),
                    'apply_track_name': item.get('apply_track_name', False),
                    'convert_to_ass': item.get('convert_to_ass', False),
                    'rescale': item.get('rescale', False),
                    'size_multiplier': item.get('size_multiplier', 1.0),
                })
                realized.append(base)
            counters[(src, ttype)] = idx + 1
        return realized

    def _layout_to_template(self, layout):
        kept = {'source', 'type', 'is_default', 'is_forced_display', 'apply_track_name', 'convert_to_ass', 'rescale', 'size_multiplier'}
        return [{k: v for k, v in t.items() if k in kept} for t in (layout or [])]

    # ---------- run batch ----------
    def start_batch(self, and_merge: bool):
        self.save_ui_to_config()
        ref_path_str, sec_path_str, ter_path_str = self.inputs.get_values()
        try:
            initial_jobs = discover_jobs(ref_path_str, sec_path_str, ter_path_str)
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Job Discovery Error", str(e)); return
        if not initial_jobs:
            QMessageBox.information(self, "No Jobs Found", "No valid jobs could be found."); return

        final_jobs = initial_jobs

        # manual-only path for merges
        if and_merge:
            processed_jobs = []; last_manual_layout = None; last_track_signature = None
            auto_apply_enabled = self.manual.get_auto_apply()
            strict_match = self.manual.get_strict()
            tool_paths = {t: shutil.which(t) for t in ['mkvmerge']}
            if not tool_paths['mkvmerge']:
                QMessageBox.critical(self, "Tool Not Found", "mkvmerge not found."); return
            runner = CommandRunner(self.config.settings, lambda msg: self.append_log(f'[Pre-Scan] {msg}'))
            for i, job_data in enumerate(initial_jobs):
                self.status.set_status(f"Pre-scanning {Path(job_data['ref']).name}...")
                try:
                    track_info = get_track_info_for_dialog(job_data['ref'], job_data.get('sec'), job_data.get('ter'), runner, tool_paths)
                except Exception as e:
                    QMessageBox.warning(self, "Pre-scan Failed",
                                        f"Could not analyze tracks for {Path(job_data['ref']).name}:\n{e}")
                    return
                current_signature = self._generate_track_signature(track_info, strict=strict_match); current_layout = None
                should_auto_apply = (auto_apply_enabled and last_manual_layout is not None and last_track_signature is not None and current_signature == last_track_signature)
                if should_auto_apply:
                    current_layout = self._materialize_layout(last_manual_layout, track_info)
                    self.append_log(f"Auto-applied previous layout to {Path(job_data['ref']).name}... (strict={'on' if strict_match else 'off'})")
                else:
                    layout_to_carry = last_manual_layout if (last_track_signature and current_signature == last_track_signature) else None
                    dialog = ManualSelectionDialog(track_info, self, previous_layout=layout_to_carry)
                    if dialog.exec():
                        current_layout = dialog.get_manual_layout()
                    else:
                        self.append_log("Batch run cancelled by user."); self.status.set_status("Ready"); return
                if current_layout:
                    job_data['manual_layout'] = current_layout; processed_jobs.append(job_data)
                    last_manual_layout = self._layout_to_template(current_layout)
                    last_track_signature = current_signature
                else:
                    self.append_log(f"Job '{Path(job_data['ref']).name}' was skipped.")
                    last_manual_layout = None; last_track_signature = None
            final_jobs = processed_jobs

        if not final_jobs:
            self.status.set_status("Ready"); self.append_log("No jobs to run after user selection."); return

        output_dir = self.config.get('output_folder')
        is_batch = Path(ref_path_str).is_dir() and len(final_jobs) > 1
        if is_batch:
            output_dir = str(Path(output_dir) / Path(ref_path_str).name)

        # reset UI sections
        self.log.clear()
        self.status.set_status(f'Starting batch of {len(final_jobs)} jobs…')
        self.status.set_progress(0.0)
        self.results.reset()

        # worker
        self.worker = JobWorker(self.config.settings, final_jobs, and_merge, output_dir)
        self.worker.signals.log.connect(self.append_log)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.status.connect(self.update_status)
        self.worker.signals.finished_job.connect(self.job_finished)
        self.worker.signals.finished_all.connect(self.batch_finished)
        self.thread_pool.start(self.worker)

    # ---------- UI signal sinks ----------
    def append_log(self, message: str):
        self.log.append(message, autoscroll=self.config.get('log_autoscroll', True))

    def update_progress(self, value: float):
        self.status.set_progress(value)

    def update_status(self, message: str):
        self.status.set_status(message)

    def job_finished(self, result: dict):
        # update delays panel
        if 'delay_sec' in result or 'delay_ter' in result:
            self.results.set_delays(result.get('delay_sec'), result.get('delay_ter'))

        name = result.get('name', '')
        status = result.get('status', 'Unknown')
        if status == 'Failed':
            self.append_log(f"--- Job Summary for {name}: FAILED ---")
        else:
            self.append_log(f"--- Job Summary for {name}: {status} ---")

    def batch_finished(self, all_results: list):
        self.update_status(f'All {len(all_results)} jobs finished.')
        self.status.set_progress(1.0)

        output_dir = None
        if all_results:
            for result in all_results:
                if result.get('status') in ['Merged', 'Analyzed'] and 'output' in result and result['output']:
                    output_dir = Path(result['output']).parent
                    break

        ref_path_str, *_ = self.inputs.get_values()
        is_batch = Path(ref_path_str).is_dir() and len(all_results) > 1

        if is_batch and self.actions.get_archive() and output_dir:
            QTimer.singleShot(0, lambda: self._archive_logs_for_batch(output_dir))

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Batch Complete", f"Finished processing {len(all_results)} jobs.")

    def _archive_logs_for_batch(self, output_dir: Path):
        self.append_log(f"--- Archiving logs in {output_dir} ---")
        try:
            log_files = list(output_dir.glob('*.log'))
            if not log_files:
                self.append_log("No log files found to archive.")
                return

            zip_name = f"{output_dir.name}.zip"
            zip_path = output_dir / zip_name

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for log_file in log_files:
                    zipf.write(log_file, arcname=log_file.name)
                    self.append_log(f"  + Added {log_file.name}")

            for log_file in log_files:
                log_file.unlink()

            self.append_log(f"Successfully created log archive: {zip_path}")

        except Exception as e:
            self.append_log(f"[ERROR] Failed to archive logs: {e}")

    def closeEvent(self, event):
        self.save_ui_to_config()
        super().closeEvent(event)
