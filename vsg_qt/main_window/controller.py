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
from vsg_core.job_layouts import JobLayoutManager
from vsg_qt.worker import JobWorker
from vsg_qt.options_dialog import OptionsDialog
from vsg_qt.job_queue_dialog import JobQueueDialog

class MainController:
    def __init__(self, view: "MainWindow"):
        self.v = view
        self.config: AppConfig = view.config
        self.worker: Optional[JobWorker] = None
        self.layout_manager = JobLayoutManager(
            temp_root=self.config.get('temp_root'),
            log_callback=self.append_log
        )

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
        start_dir = self.config.get('last_ref_path') or self.config.get('last_sec_path')
        if start_dir:
            dialog.setDirectory(str(Path(start_dir).parent))
        if dialog.exec():
            line_edit.setText(dialog.selectedFiles()[0])

    def open_job_queue(self):
        self.save_ui_to_config()
        queue_dialog = JobQueueDialog(
            config=self.config,
            log_callback=self.append_log,
            layout_manager=self.layout_manager,
            parent=self.v
        )
        # FIX: Check the dialog result. Only clean up if the user cancels.
        if queue_dialog.exec():
            final_jobs = queue_dialog.get_final_jobs()
            if final_jobs:
                self._run_configured_jobs(final_jobs)
            else:
                self.append_log("Queue closed with no jobs to run.")
                self.v.status_label.setText("Ready")
                # No jobs were run, so we can clean up now.
                self.layout_manager.cleanup_all()
        else:
            # User cancelled or closed the dialog, so clean up.
            self.layout_manager.cleanup_all()

    def _run_configured_jobs(self, final_jobs: List[Dict]):
        source1_path_str = final_jobs[0]['sources']['Source 1']
        output_dir = self.config.get('output_folder')
        is_batch = len(final_jobs) > 1
        if is_batch:
            source1_path = Path(source1_path_str)
            output_dir = str(Path(output_dir) / source1_path.parent.name)

        self._start_worker(final_jobs, and_merge=True, output_dir=output_dir)

    def start_batch_analyze_only(self):
        self.save_ui_to_config()
        sources = {k: v for k, v in {
            "Source 1": self.v.ref_input.text().strip(),
            "Source 2": self.v.sec_input.text().strip(),
            "Source 3": self.v.ter_input.text().strip(),
        }.items() if v}

        try:
            initial_jobs = discover_jobs(sources)
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self.v, "Job Discovery Error", str(e)); return
        if not initial_jobs:
            QMessageBox.information(self.v, "No Jobs Found", "No valid jobs found."); return

        output_dir = self.config.get('output_folder')
        source1_path_str = sources.get("Source 1", "")
        if len(initial_jobs) > 1:
             output_dir = str(Path(output_dir) / Path(source1_path_str).name)

        self._start_worker(initial_jobs, and_merge=False, output_dir=output_dir)

    def _start_worker(self, jobs: List[Dict], and_merge: bool, output_dir: str):
        self.v.log_output.clear()
        self.v.status_label.setText(f'Starting batch of {len(jobs)} jobs…')
        self.v.progress_bar.setValue(0)
        for label in self.v.delay_labels:
            label.setText("—")

        self.worker = JobWorker(self.config.settings, jobs, and_merge, output_dir)
        self.worker.signals.log.connect(self.append_log)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.status.connect(self.update_status)
        self.worker.signals.finished_job.connect(self.job_finished)
        self.worker.signals.finished_all.connect(self.batch_finished)
        QThreadPool.globalInstance().start(self.worker)

    def job_finished(self, result: dict):
        delays = result.get('delays', {})
        for i, label in enumerate(self.v.delay_labels):
            source_key = f"Source {i + 2}"
            delay_val = delays.get(source_key)
            label.setText(f"{delay_val} ms" if delay_val is not None else "—")

        name = result.get('name', '')
        status = result.get('status', 'Unknown')
        self.append_log(f"--- Job Summary for {name}: {status.upper()} ---")

    def batch_finished(self, all_results: list):
        self.update_status(f'All {len(all_results)} jobs finished.')
        self.v.progress_bar.setValue(100)

        is_batch = len(all_results) > 1
        output_dir = None
        if all_results and 'output' in all_results[0] and all_results[0]['output']:
            output_dir = Path(all_results[0]['output']).parent

        if is_batch and self.v.archive_logs_check.isChecked() and output_dir:
            QTimer.singleShot(0, lambda: self._archive_logs_for_batch(output_dir))

        successful_jobs = 0
        jobs_with_warnings = 0
        failed_jobs = 0
        stepping_jobs = []  # NEW: Track jobs with stepping
        stepping_detected_disabled_jobs = []  # NEW: Track jobs with stepping detected but disabled

        for result in all_results:
            if result.get('status') == 'Failed':
                failed_jobs += 1
            elif result.get('issues', 0) > 0:
                jobs_with_warnings += 1
            else:
                successful_jobs += 1

            # NEW: Track jobs that used stepping correction
            if result.get('stepping_sources'):
                job_name = result.get('name', 'Unknown')
                stepping_sources = result.get('stepping_sources', [])
                stepping_jobs.append({
                    'name': job_name,
                    'sources': stepping_sources
                })

            # NEW: Track jobs with stepping detected but correction disabled
            if result.get('stepping_detected_disabled'):
                job_name = result.get('name', 'Unknown')
                detected_sources = result.get('stepping_detected_disabled', [])
                stepping_detected_disabled_jobs.append({
                    'name': job_name,
                    'sources': detected_sources
                })

        summary_message = "\n--- Batch Summary ---\n"
        summary_message += f"  - Successful jobs: {successful_jobs}\n"
        summary_message += f"  - Jobs with warnings: {jobs_with_warnings}\n"
        summary_message += f"  - Failed jobs: {failed_jobs}\n"

        # Add stepping detection summary
        if stepping_jobs:
            summary_message += f"\nℹ️  Jobs with Stepping Correction ({len(stepping_jobs)}):\n"
            summary_message += "  (Quality checks performed - warnings above indicate issues)\n"
            for job_info in stepping_jobs:
                sources_str = ', '.join(job_info['sources'])
                summary_message += f"  • {job_info['name']} - Sources: {sources_str}\n"

        # NEW: Add stepping detected but disabled warning
        if stepping_detected_disabled_jobs:
            summary_message += f"\n⚠️  Jobs with Stepping Detected (Correction Disabled) ({len(stepping_detected_disabled_jobs)}):\n"
            summary_message += "  ⚠️  These files have timing inconsistencies but stepping correction is disabled.\n"
            summary_message += "  ⚠️  MANUAL REVIEW REQUIRED - Check sync quality carefully!\n"
            summary_message += "  💡 Tip: Enable 'Stepping Correction' in settings for automatic correction.\n"
            for job_info in stepping_detected_disabled_jobs:
                sources_str = ', '.join(job_info['sources'])
                summary_message += f"  • {job_info['name']} - Sources: {sources_str}\n"

        self.append_log(summary_message)

        if failed_jobs > 0:
            QMessageBox.critical(self.v, "Batch Complete", f"Finished processing {len(all_results)} jobs with {failed_jobs} failure(s).")
        elif stepping_jobs or stepping_detected_disabled_jobs:
            # Show info if any jobs used stepping or detected stepping without correction
            msg_parts = [f"Finished processing {len(all_results)} jobs successfully.\n"]

            if stepping_jobs:
                stepping_count = len(stepping_jobs)
                msg_parts.append(f"\nℹ️  Note: {stepping_count} job(s) used stepping correction.")
                msg_parts.append("Check warnings above for any quality issues requiring review.")

            if stepping_detected_disabled_jobs:
                detected_count = len(stepping_detected_disabled_jobs)
                msg_parts.append(f"\n⚠️  WARNING: {detected_count} job(s) have stepping detected but correction is DISABLED!")
                msg_parts.append("These files may have inconsistent timing throughout.")
                msg_parts.append("MANUAL REVIEW REQUIRED!")

            msg_parts.append("\nSee log for details.")
            msg = '\n'.join(msg_parts)
            QMessageBox.warning(self.v, "Batch Complete - Review Required", msg)
        elif jobs_with_warnings > 0:
            QMessageBox.warning(self.v, "Batch Complete", f"Finished processing {len(all_results)} jobs with {jobs_with_warnings} job(s) having warnings.")
        else:
            QMessageBox.information(self.v, "Batch Complete", f"Finished processing {len(all_results)} jobs successfully.")

        # FIX: Cleanup is now called here, after all jobs are finished.
        self.layout_manager.cleanup_all()

    def _archive_logs_for_batch(self, output_dir: Path):
        self.append_log(f"--- Archiving logs in {output_dir} ---")
        try:
            log_files = list(output_dir.glob('*.log'))
            if not log_files:
                self.append_log("No log files found to archive."); return
            zip_path = output_dir / f"{output_dir.name}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for log_file in log_files:
                    zipf.write(log_file, arcname=log_file.name)
            for log_file in log_files:
                log_file.unlink()
            self.append_log(f"Successfully created log archive: {zip_path}")
        except Exception as e:
            self.append_log(f"[ERROR] Failed to archive logs: {e}")

    def on_close(self):
        self.save_ui_to_config()
        if self.worker:
            self.worker.disable_gui_signals()
            QThreadPool.globalInstance().waitForDone()
        self.layout_manager.cleanup_all()
