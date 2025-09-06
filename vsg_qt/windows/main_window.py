# -*- coding: utf-8 -*-
from pathlib import Path
import shutil, zipfile
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QMessageBox
from PySide6.QtCore import QThreadPool, QTimer
from collections import Counter

from vsg_qt.panels.input_panel import InputPanel
from vsg_qt.panels.manual_behavior_panel import ManualBehaviorPanel
from vsg_qt.panels.actions_panel import ActionsPanel
from vsg_qt.panels.status_panel import StatusPanel
from vsg_qt.panels.results_panel import ResultsPanel
from vsg_qt.panels.log_panel import LogPanel

from vsg_qt.options_dialog import OptionsDialog
from vsg_qt.worker import JobWorker

from vsg_core.config import AppConfig
from vsg_core.job_discovery import discover_jobs
from vsg_core.io.runner import CommandRunner
from vsg_core.extraction.tracks import get_track_info_for_dialog
from vsg_qt.manual_selection_dialog import ManualSelectionDialog


class MainWindow(QMainWindow):
    """Thin orchestrator over modular UI panels."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video/Audio Sync & Merge - PySide6 Edition')
        self.setGeometry(100, 100, 1000, 600)

        self.config = AppConfig()
        self.thread_pool = QThreadPool()
        self.worker = None

        # panels
        self.inputs = InputPanel()
        self.manual = ManualBehaviorPanel()
        self.actions = ActionsPanel()
        self.status = StatusPanel()
        self.results = ResultsPanel()
        self.log = LogPanel()

        # root layout
        central = QWidget()
        root = QVBoxLayout(central)
        root.addWidget(self.inputs)
        root.addWidget(self.manual)
        root.addWidget(self.actions)
        root.addWidget(self.status)
        root.addWidget(self.results)
        root.addWidget(self.log)
        self.setCentralWidget(central)

        # wire events
        self.inputs.settingsRequested.connect(self.open_options_dialog)
        self.actions.analyzeRequested.connect(self._on_analyze_clicked)

        # load settings → UI
        self._apply_config_to_ui()

    # ---------------- settings ----------------
    def open_options_dialog(self):
        dialog = OptionsDialog(self.config, self)
        if dialog.exec():
            self.config.save()
            self._append_log('Settings saved.')

    def _apply_config_to_ui(self):
        self.inputs.set_paths(
            self.config.get('last_ref_path', ''),
            self.config.get('last_sec_path', ''),
            self.config.get('last_ter_path', ''),
        )
        self.actions.set_archive_enabled(self.config.get('archive_logs', True))
        self.manual.set_values(
            auto_apply=False,  # runtime only (not persisted)
            strict=self.config.get('auto_apply_strict', False),
        )

    def _save_ui_to_config(self):
        ref, sec, ter = self.inputs.get_paths()
        self.config.set('last_ref_path', ref or '')
        self.config.set('last_sec_path', sec or '')
        self.config.set('last_ter_path', ter or '')
        self.config.set('archive_logs', self.actions.archive_enabled())
        self.config.set('auto_apply_strict', self.manual.is_strict())
        self.config.save()

    # ---------------- actions ----------------
    def _on_analyze_clicked(self, and_merge: bool):
        self._save_ui_to_config()

        ref_path, sec_path, ter_path = self.inputs.get_paths()
        try:
            initial_jobs = discover_jobs(ref_path, sec_path, ter_path)
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Job Discovery Error", str(e))
            return
        if not initial_jobs:
            QMessageBox.information(self, "No Jobs Found", "No valid jobs could be found.")
            return

        final_jobs = initial_jobs
        # manual-only for merges
        if and_merge:
            processed_jobs = []
            last_manual_layout = None
            last_track_signature = None
            auto_apply_enabled = self.manual.is_auto_apply()
            strict_match = self.manual.is_strict()

            tool_paths = {t: shutil.which(t) for t in ['mkvmerge']}
            if not tool_paths['mkvmerge']:
                QMessageBox.critical(self, "Tool Not Found", "mkvmerge not found.")
                return

            runner = CommandRunner(self.config.settings, lambda msg: self._append_log(f'[Pre-Scan] {msg}'))
            for i, job_data in enumerate(initial_jobs):
                self.status.set_status(f"Pre-scanning {Path(job_data['ref']).name}...")
                try:
                    track_info = get_track_info_for_dialog(job_data['ref'], job_data.get('sec'), job_data.get('ter'), runner, tool_paths)
                except Exception as e:
                    msg = f"Could not analyze tracks for {Path(job_data['ref']).name}:\n{e}"
                    QMessageBox.warning(self, "Pre-scan Failed", msg)
                    return

                current_signature = self._generate_track_signature(track_info, strict=strict_match)
                current_layout = None

                should_auto_apply = (
                    auto_apply_enabled and last_manual_layout is not None and
                    last_track_signature is not None and current_signature == last_track_signature
                )

                if should_auto_apply:
                    current_layout = self._materialize_layout(last_manual_layout, track_info)
                    self._append_log(f"Auto-applied previous layout to {Path(job_data['ref']).name}... (strict={'on' if strict_match else 'off'})")
                else:
                    carry = None
                    if last_track_signature and current_signature == last_track_signature:
                        carry = last_manual_layout
                    dialog = ManualSelectionDialog(track_info, self, previous_layout=carry)
                    if dialog.exec():
                        current_layout = dialog.get_manual_layout()
                    else:
                        self._append_log("Batch run cancelled by user.")
                        self.status.set_status("Ready")
                        return

                if current_layout:
                    job_data['manual_layout'] = current_layout
                    processed_jobs.append(job_data)
                    last_manual_layout = self._layout_to_template(current_layout)
                    last_track_signature = current_signature
                else:
                    self._append_log(f"Job '{Path(job_data['ref']).name}' was skipped.")
                    last_manual_layout = None
                    last_track_signature = None

            final_jobs = processed_jobs

        if not final_jobs:
            self.status.set_status("Ready")
            self._append_log("No jobs to run after user selection.")
            return

        # prepare batch
        output_dir = self.config.get('output_folder')
        is_batch = Path(ref_path).is_dir() and len(final_jobs) > 1
        if is_batch:
            output_dir = str(Path(output_dir) / Path(ref_path).name)

        # reset UI
        self.log.clear()
        self.status.set_status(f'Starting batch of {len(final_jobs)} jobs…')
        self.status.set_progress(0.0)
        self.results.reset()

        # launch worker
        self.worker = JobWorker(self.config.settings, final_jobs, and_merge, output_dir)
        self.worker.signals.log.connect(self._append_log)
        self.worker.signals.progress.connect(self.status.set_progress)
        self.worker.signals.status.connect(self.status.set_status)
        self.worker.signals.finished_job.connect(self._job_finished)
        self.worker.signals.finished_all.connect(self._batch_finished)
        self.thread_pool.start(self.worker)

    # ---------------- helpers (moved from old MainWindow) ----------------
    def _append_log(self, message: str):
        self.log.append(message, autoscroll=self.config.get('log_autoscroll', True))

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
        kept = {'source','type','is_default','is_forced_display','apply_track_name','convert_to_ass','rescale','size_multiplier'}
        return [{k: v for k, v in t.items() if k in kept} for t in (layout or [])]

    # ---------------- results & finish ----------------
    def _job_finished(self, result: dict):
        if 'delay_sec' in result:
            self.results.set_sec_delay(result['delay_sec'] if result['delay_sec'] is not None else None)
        if 'delay_ter' in result:
            self.results.set_ter_delay(result['delay_ter'] if result['delay_ter'] is not None else None)

        name = result.get('name', '')
        status = result.get('status', 'Unknown')
        if status == 'Failed':
            self._append_log(f"--- Job Summary for {name}: FAILED ---")
        else:
            self._append_log(f"--- Job Summary for {name}: {status} ---")

    def _batch_finished(self, all_results: list):
        self.status.set_status(f'All {len(all_results)} jobs finished.')
        self.status.set_progress(1.0)

        output_dir = None
        for result in all_results:
            if result.get('status') in ['Merged', 'Analyzed'] and 'output' in result and result['output']:
                output_dir = Path(result['output']).parent
                break

        # archive logs if batch and enabled
        ref_path, _, _ = self.inputs.get_paths()
        is_batch = Path(ref_path).is_dir() and len(all_results) > 1
        if is_batch and self.actions.archive_enabled() and output_dir:
            QTimer.singleShot(0, lambda: self._archive_logs_for_batch(output_dir))

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Batch Complete", f"Finished processing {len(all_results)} jobs.")

    def _archive_logs_for_batch(self, output_dir: Path):
        self._append_log(f"--- Archiving logs in {output_dir} ---")
        try:
            log_files = list(output_dir.glob('*.log'))
            if not log_files:
                self._append_log("No log files found to archive.")
                return
            zip_name = f"{output_dir.name}.zip"
            zip_path = output_dir / zip_name
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for lf in log_files:
                    zipf.write(lf, arcname=lf.name)
                    self._append_log(f"  + Added {lf.name}")
            for lf in log_files:
                lf.unlink()
            self._append_log(f"Successfully created log archive: {zip_path}")
        except Exception as e:
            self._append_log(f"[ERROR] Failed to archive logs: {e}")

    # ---------------- lifecycle ----------------
    def closeEvent(self, event):
        self._save_ui_to_config()
        super().closeEvent(event)
