# vsg_qt/main_window/controller.py
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QMessageBox

from vsg_core.job_discovery import discover_jobs
from vsg_core.job_layouts import JobLayoutManager
from vsg_core.reporting import ReportWriter
from vsg_qt.job_queue_dialog import JobQueueDialog
from vsg_qt.options_dialog import OptionsDialog
from vsg_qt.report_dialogs import BatchCompletionDialog
from vsg_qt.worker import JobWorker

if TYPE_CHECKING:
    from vsg_core.config import AppConfig

    from .window import MainWindow


class MainController:
    def __init__(self, view: MainWindow):
        self.v = view
        self.config: AppConfig = view.config
        self.worker: JobWorker | None = None
        self.layout_manager = JobLayoutManager(
            temp_root=self.config.get("temp_root"), log_callback=self.append_log
        )
        # Report tracking
        self.report_writer: ReportWriter | None = None
        self._job_counter: int = 0

    def open_options_dialog(self) -> None:
        dialog = OptionsDialog(self.config, self.v)
        if dialog.exec():
            self.config.save()
            self.append_log("Settings saved.")

    def apply_config_to_ui(self) -> None:
        v = self.v
        v.ref_input.setText(self.config.get("last_ref_path", ""))
        v.sec_input.setText(self.config.get("last_sec_path", ""))
        v.ter_input.setText(self.config.get("last_ter_path", ""))
        v.archive_logs_check.setChecked(self.config.get("archive_logs", True))

    def save_ui_to_config(self) -> None:
        v = self.v
        self.config.set("last_ref_path", v.ref_input.text())
        self.config.set("last_sec_path", v.sec_input.text())
        self.config.set("last_ter_path", v.ter_input.text())
        self.config.set("archive_logs", v.archive_logs_check.isChecked())
        self.config.save()

    def append_log(self, message: str) -> None:
        v = self.v
        v.log_output.append(message)
        if self.config.get("log_autoscroll", True):
            v.log_output.verticalScrollBar().setValue(
                v.log_output.verticalScrollBar().maximum()
            )

    def update_progress(self, value: float) -> None:
        self.v.progress_bar.setValue(int(value * 100))

    def update_status(self, message: str) -> None:
        self.v.status_label.setText(message)

    def browse_for_path(self, line_edit, caption: str) -> None:
        from PySide6.QtWidgets import QFileDialog

        dialog = QFileDialog(self.v, caption)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        start_dir = self.config.get("last_ref_path") or self.config.get("last_sec_path")
        if start_dir:
            dialog.setDirectory(str(Path(start_dir).parent))
        if dialog.exec():
            line_edit.setText(dialog.selectedFiles()[0])

    def open_job_queue(self) -> None:
        self.save_ui_to_config()
        queue_dialog = JobQueueDialog(
            config=self.config,
            log_callback=self.append_log,
            layout_manager=self.layout_manager,
            parent=self.v,
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

    def _run_configured_jobs(self, final_jobs: list[dict]) -> None:
        source1_path_str = final_jobs[0]["sources"]["Source 1"]
        output_dir = self.config.get("output_folder")
        is_batch = len(final_jobs) > 1
        if is_batch:
            source1_path = Path(source1_path_str)
            output_dir = str(Path(output_dir) / source1_path.parent.name)

        self._start_worker(final_jobs, and_merge=True, output_dir=output_dir)

    def start_batch_analyze_only(self) -> None:
        self.save_ui_to_config()
        sources = {
            k: v
            for k, v in {
                "Source 1": self.v.ref_input.text().strip(),
                "Source 2": self.v.sec_input.text().strip(),
                "Source 3": self.v.ter_input.text().strip(),
            }.items()
            if v
        }

        try:
            initial_jobs = discover_jobs(sources)
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self.v, "Job Discovery Error", str(e))
            return
        if not initial_jobs:
            QMessageBox.information(self.v, "No Jobs Found", "No valid jobs found.")
            return

        output_dir = self.config.get("output_folder")
        source1_path_str = sources.get("Source 1", "")
        if len(initial_jobs) > 1:
            output_dir = str(Path(output_dir) / Path(source1_path_str).name)

        self._start_worker(initial_jobs, and_merge=False, output_dir=output_dir)

    def _start_worker(self, jobs: list[dict], and_merge: bool, output_dir: str) -> None:
        self.v.log_output.clear()
        self.v.status_label.setText(f"Starting batch of {len(jobs)} jobs…")
        self.v.progress_bar.setValue(0)
        for label in self.v.delay_labels:
            label.setText("—")

        # Initialize report writer
        self._job_counter = 0
        is_batch = len(jobs) > 1
        logs_folder = Path(self.config.get("logs_folder"))

        # Determine batch name from first job's Source 1
        source1_path = Path(jobs[0]["sources"]["Source 1"])
        if is_batch:
            batch_name = source1_path.parent.name
        else:
            batch_name = source1_path.stem

        self.report_writer = ReportWriter(logs_folder)
        report_path = self.report_writer.create_report(
            batch_name=batch_name,
            is_batch=is_batch,
            output_dir=output_dir,
            total_jobs=len(jobs),
        )
        self.append_log(f"[Report] Created: {report_path}")

        # Create a snapshot copy of settings for the worker thread to avoid
        # sharing the same AppSettings instance between the main thread and worker.
        # Concurrent access to the shared object (even read-only) can cause segfaults
        # in PySide6/shiboken6 when the GIL is released during C++ calls.
        worker_settings = self.config.settings.model_copy(deep=True)
        self.worker = JobWorker(worker_settings, jobs, and_merge, output_dir)
        self.worker.signals.log.connect(self.append_log)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.status.connect(self.update_status)
        self.worker.signals.finished_job.connect(self.job_finished)
        self.worker.signals.finished_all.connect(self.batch_finished)
        QThreadPool.globalInstance().start(self.worker)

    def job_finished(self, result: dict) -> None:
        delays = result.get("delays", {})
        for i, label in enumerate(self.v.delay_labels):
            source_key = f"Source {i + 2}"
            delay_val = delays.get(source_key)
            label.setText(f"{delay_val} ms" if delay_val is not None else "—")

        name = result.get("name", "")
        status = result.get("status", "Unknown")
        self.append_log(f"--- Job Summary for {name}: {status.upper()} ---")

        # Add job to report
        self._job_counter += 1
        if self.report_writer:
            self.report_writer.add_job(result, self._job_counter)

    def batch_finished(self, all_results: list) -> None:
        self.update_status(f"All {len(all_results)} jobs finished.")
        self.v.progress_bar.setValue(100)

        is_batch = len(all_results) > 1
        output_dir = None
        if all_results and "output" in all_results[0] and all_results[0]["output"]:
            output_dir = Path(all_results[0]["output"]).parent

        if is_batch and self.v.archive_logs_check.isChecked() and output_dir:
            QTimer.singleShot(0, lambda: self._archive_logs_for_batch(output_dir))

        # Finalize the report - this is the single source of truth for all stats
        report_path = None
        summary = {}
        if self.report_writer:
            summary = self.report_writer.finalize()
            report_path = self.report_writer.get_report_path()

        # Get stats from report (single source of truth)
        successful_jobs = summary.get("successful", 0)
        jobs_with_warnings = summary.get("warnings", 0)
        failed_jobs = summary.get("failed", 0)
        stepping_jobs = summary.get("stepping_jobs", [])
        stepping_disabled_jobs = summary.get("stepping_disabled_jobs", [])

        # Simple log summary - detailed info is in the report
        summary_message = "\n--- Batch Summary ---\n"
        summary_message += f"  - Successful jobs: {successful_jobs}\n"
        summary_message += f"  - Jobs with warnings: {jobs_with_warnings}\n"
        summary_message += f"  - Failed jobs: {failed_jobs}\n"
        if report_path:
            summary_message += f"\n  Report: {report_path}\n"

        self.append_log(summary_message)

        # Show completion dialog with Show Report button
        dialog = BatchCompletionDialog(
            parent=self.v,
            total_jobs=len(all_results),
            successful=successful_jobs,
            warnings=jobs_with_warnings,
            failed=failed_jobs,
            stepping_jobs=stepping_jobs,
            stepping_disabled_jobs=stepping_disabled_jobs,
            report_path=report_path,
        )
        dialog.exec()

        # FIX: Cleanup is now called here, after all jobs are finished.
        self.layout_manager.cleanup_all()

    def _archive_logs_for_batch(self, output_dir: Path) -> None:
        self.append_log(f"--- Archiving logs in {output_dir} ---")
        try:
            log_files = list(output_dir.glob("*.log"))
            if not log_files:
                self.append_log("No log files found to archive.")
                return
            zip_path = output_dir / f"{output_dir.name}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for log_file in log_files:
                    zipf.write(log_file, arcname=log_file.name)
            for log_file in log_files:
                log_file.unlink()
            self.append_log(f"Successfully created log archive: {zip_path}")
        except Exception as e:
            self.append_log(f"[ERROR] Failed to archive logs: {e}")

    def on_close(self) -> None:
        # Cancel any running worker to prevent signal crashes
        if self.worker is not None:
            self.worker.cancel()
            self.append_log("[SHUTDOWN] Cancelling background tasks...")

        self.save_ui_to_config()
        self.layout_manager.cleanup_all()
