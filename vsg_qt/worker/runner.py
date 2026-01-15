# vsg_qt/worker/runner.py
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Dict, Any, List

from PySide6.QtCore import QRunnable, Slot

from vsg_core.pipeline import JobPipeline
from .signals import WorkerSignals

class JobWorker(QRunnable):
    def __init__(self, config: Dict[str, Any], jobs: List[Dict], and_merge: bool, output_dir: str):
        super().__init__()
        self.config = config
        self.jobs = jobs
        self.and_merge = and_merge
        self.output_dir = output_dir
        self.signals = WorkerSignals()
        self.cancelled = False

    def _safe_log(self, msg: str):
        """Safely emit log message, handling case where signals are deleted during GUI shutdown."""
        try:
            if hasattr(self, 'signals') and self.signals is not None:
                self.signals.log.emit(msg)
        except (RuntimeError, AttributeError):
            # Signals deleted during GUI cleanup - silently ignore
            pass

    def _safe_progress(self, val: float):
        """Safely emit progress update, handling case where signals are deleted during GUI shutdown."""
        try:
            if hasattr(self, 'signals') and self.signals is not None:
                self.signals.progress.emit(val)
        except (RuntimeError, AttributeError):
            # Signals deleted during GUI cleanup - silently ignore
            pass

    def _safe_status(self, msg: str):
        """Safely emit status update, handling case where signals are deleted during GUI shutdown."""
        try:
            if hasattr(self, 'signals') and self.signals is not None:
                self.signals.status.emit(msg)
        except (RuntimeError, AttributeError):
            # Signals deleted during GUI cleanup - silently ignore
            pass

    def _safe_finished_job(self, result: Dict[str, Any]):
        """Safely emit job finished signal, handling case where signals are deleted during GUI shutdown."""
        try:
            if hasattr(self, 'signals') and self.signals is not None:
                self.signals.finished_job.emit(result)
        except (RuntimeError, AttributeError):
            # Signals deleted during GUI cleanup - silently ignore
            pass

    def _safe_finished_all(self, results: List[Dict[str, Any]]):
        """Safely emit all jobs finished signal, handling case where signals are deleted during GUI shutdown."""
        try:
            if hasattr(self, 'signals') and self.signals is not None:
                self.signals.finished_all.emit(results)
        except (RuntimeError, AttributeError):
            # Signals deleted during GUI cleanup - silently ignore
            pass

    def cancel(self):
        """Request cancellation of this worker."""
        self.cancelled = True

    @Slot()
    def run(self):
        pipeline = JobPipeline(
            config=self.config,
            log_callback=self._safe_log,
            progress_callback=self._safe_progress,
        )

        all_results: List[Dict[str, Any]] = []
        total_jobs = len(self.jobs)

        for i, job_data in enumerate(self.jobs, 1):
            # Check for cancellation
            if self.cancelled:
                self._safe_log(f"[WORKER] Cancelled by user, stopping at job {i}/{total_jobs}")
                break

            sources = job_data.get('sources', {})
            source1_file = sources.get("Source 1")
            if not source1_file:
                self._safe_log(f"[FATAL WORKER ERROR] Job {i} is missing 'Source 1'. Skipping.")
                continue

            # Store original Source 1 path for batch output folder logic in controller
            job_data['ref_path_for_batch_check'] = source1_file

            try:
                self._safe_status(f'Processing {i}/{total_jobs}: {Path(source1_file).name}')

                result = pipeline.run_job(
                    sources=sources,
                    and_merge=self.and_merge,
                    output_dir_str=self.output_dir,
                    manual_layout=job_data.get('manual_layout'),
                    attachment_sources=job_data.get('attachment_sources')
                )

                result['job_data_for_batch_check'] = job_data

                self._safe_finished_job(result)
                all_results.append(result)

            except Exception as e:
                error_result = {
                    'status': 'Failed', 'error': str(e),
                    'name': Path(source1_file).name,
                    'job_data_for_batch_check': job_data
                }
                self._safe_log(f'[FATAL WORKER ERROR] Job {i} failed: {e}')
                self._safe_finished_job(error_result)
                all_results.append(error_result)

        self._safe_finished_all(all_results)
