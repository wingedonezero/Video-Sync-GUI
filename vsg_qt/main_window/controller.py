# vsg_qt/main_window/controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QTimer, QThreadPool

from vsg_core.config import AppConfig
from vsg_core.job_discovery import discover_jobs
from vsg_qt.worker import JobWorker
from vsg_qt.options_dialog import OptionsDialog
from vsg_qt.job_queue_dialog import JobQueueDialog

class MainController:
    def __init__(self, view: "MainWindow"):
        self.v = view
        self.config: AppConfig = view.config
        self.worker: Optional[JobWorker] = None

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

    def save_ui_to_config(self):
        v = self.v
        self.config.set('last_ref_path', v.ref_input.text())
        self.config.set('last_sec_path', v.sec_input.text())
        self.config.set('last_ter_path', v.ter_input.text())
        self.config.set('archive_logs', v.archive_logs_check.isChecked())
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

    def open_job_queue(self):
        self.save_ui_to_config()
        queue_dialog = JobQueueDialog(config=self.config, log_callback=self.append_log, parent=self.v)
        if queue_dialog.exec():
            final_jobs = queue_dialog.get_configured_jobs()
            if final_jobs:
                self._run_configured_jobs(final_jobs)
            else:
                self.append_log("Queue closed with no jobs to run.")
                self.v.status_label.setText("Ready")

    def _run_configured_jobs(self, final_jobs: List[Dict]):
        source1_path_str = final_jobs[0]['sources']['Source 1']
        output_dir = self.config.get('output_folder')

        source1_path = Path(source1_path_str)
        is_batch = source1_path.is_dir()
        if not is_batch and len(final_jobs) > 1:
            is_batch = True

        if is_batch and source1_path.is_file():
             output_dir = str(Path(output_dir) / source1_path.parent.name)
        elif is_batch and source1_path.is_dir():
             output_dir = str(Path(output_dir) / source1_path.name)

        self._start_worker(final_jobs, and_merge=True, output_dir=output_dir)

    def start_batch_analyze_only(self):
        self.save_ui_to_config()
        sources = {
            "Source 1": self.v.ref_input.text().strip(),
            "Source 2": self.v.sec_input.text().strip(),
            "Source 3": self.v.ter_input.text().strip(),
        }
        sources = {k: v for k, v in sources.items() if v}

        try:
            initial_jobs = discover_jobs(sources)
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self.v, "Job Discovery Error", str(e)); return
        if not initial_jobs:
            QMessageBox.information(self.v, "No Jobs Found", "No valid jobs could be found for the selected inputs."); return

        output_dir = self.config.get('output_folder')
        source1_path_str = sources.get("Source 1", "")
        is_batch = Path(source1_path_str).is_dir() and len(initial_jobs) > 1
        if is_batch:
            output_dir = str(Path(output_dir) / Path(source1_path_str).name)

        self._start_worker(initial_jobs, and_merge=False, output_dir=output_dir)

    def _start_worker(self, jobs: List[Dict], and_merge: bool, output_dir: str):
        self.v.log_output.clear(); self.v.status_label.setText(f'Starting batch of {len(jobs)} jobs…')
        self.v.progress_bar.setValue(0); self.v.sec_delay_label.setText('—'); self.v.ter_delay_label.setText('—')

        self.worker = JobWorker(self.config.settings, jobs, and_merge, output_dir)
        self.worker.signals.log.connect(self.append_log)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.status.connect(self.update_status)
        self.worker.signals.finished_job.connect(self.job_finished)
        self.worker.signals.finished_all.connect(self.batch_finished)
        QThreadPool.globalInstance().start(self.worker)

    def job_finished(self, result: dict):
        delays = result.get('delays', {})
        delay2 = delays.get('Source 2')
        delay3 = delays.get('Source 3')
        self.v.sec_delay_label.setText(f"{delay2} ms" if delay2 is not None else "—")
        self.v.ter_delay_label.setText(f"{delay3} ms" if delay3 is not None else "—")

        name = result.get('name', ''); status = result.get('status', 'Unknown')
        if status == 'Failed': self.append_log(f"--- Job Summary for {name}: FAILED ---")
        else: self.append_log(f"--- Job Summary for {name}: {status} ---")

    def batch_finished(self, all_results: list):
        self.update_status(f'All {len(all_results)} jobs finished.'); self.v.progress_bar.setValue(100)
        output_dir = None
        if all_results:
            for res in all_results:
                if res.get('status') in ['Merged', 'Analyzed'] and 'output' in res and res['output']:
                    output_dir = Path(res['output']).parent; break

        ref_path_str = ""
        if all_results and 'job_data_for_batch_check' in all_results[0]:
             job_data = all_results[0]['job_data_for_batch_check']
             ref_path_str = job_data.get('ref_path_for_batch_check', '')

        is_batch = Path(ref_path_str).is_dir() if ref_path_str else len(all_results) > 1

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
