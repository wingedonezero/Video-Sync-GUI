# vsg_qt/worker/runner.py
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Dict, Any, List

from PySide6.QtCore import QRunnable, Slot, QPointer

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
        self._signals_ptr = QPointer(self.signals)

    @Slot()
    def run(self):
        pipeline = JobPipeline(
            config=self.config,
            log_callback=lambda msg: self._emit_safe("log", msg),
            progress_callback=lambda val: self._emit_safe("progress", val),
        )

        all_results: List[Dict[str, Any]] = []
        total_jobs = len(self.jobs)

        for i, job_data in enumerate(self.jobs, 1):
            sources = job_data.get('sources', {})
            source1_file = sources.get("Source 1")
            if not source1_file:
                self._emit_safe("log", f"[FATAL WORKER ERROR] Job {i} is missing 'Source 1'. Skipping.")
                continue

            # Store original Source 1 path for batch output folder logic in controller
            job_data['ref_path_for_batch_check'] = source1_file

            try:
                self._emit_safe("status", f'Processing {i}/{total_jobs}: {Path(source1_file).name}')

                result = pipeline.run_job(
                    sources=sources,
                    and_merge=self.and_merge,
                    output_dir_str=self.output_dir,
                    manual_layout=job_data.get('manual_layout'),
                    attachment_sources=job_data.get('attachment_sources')
                )

                result['job_data_for_batch_check'] = job_data

                self._emit_safe("finished_job", result)
                all_results.append(result)

            except Exception as e:
                error_result = {
                    'status': 'Failed', 'error': str(e),
                    'name': Path(source1_file).name,
                    'job_data_for_batch_check': job_data
                }
                self._emit_safe("log", f'[FATAL WORKER ERROR] Job {i} failed: {e}')
                self._emit_safe("finished_job", error_result)
                all_results.append(error_result)

        self._emit_safe("finished_all", all_results)

    def disable_gui_signals(self):
        self._signals_ptr = None

    def _emit_safe(self, signal_name: str, payload):
        signals = self._signals_ptr
        if not signals:
            return
        try:
            getattr(signals, signal_name).emit(payload)
        except RuntimeError:
            self._signals_ptr = None
