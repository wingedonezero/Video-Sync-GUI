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

    @Slot()
    def run(self):
        pipeline = JobPipeline(
            config=self.config,
            log_callback=lambda msg: self.signals.log.emit(msg),
            progress_callback=lambda val: self.signals.progress.emit(val),
        )

        all_results: List[Dict[str, Any]] = []
        total_jobs = len(self.jobs)

        for i, job_data in enumerate(self.jobs, 1):
            sources = job_data.get('sources', {})
            source1_file = sources.get("Source 1")
            if not source1_file:
                self.signals.log.emit(f"[FATAL WORKER ERROR] Job {i} is missing 'Source 1'. Skipping.")
                continue

            try:
                self.signals.status.emit(f'Processing {i}/{total_jobs}: {Path(source1_file).name}')

                result = pipeline.run_job(
                    sources=sources,
                    and_merge=self.and_merge,
                    output_dir_str=self.output_dir,
                    manual_layout=job_data.get('manual_layout'),
                )

                # Pass original job data through for the batch check in the controller
                result['job_data_for_batch_check'] = job_data

                self.signals.finished_job.emit(result)
                all_results.append(result)

            except Exception as e:
                error_result = {
                    'status': 'Failed', 'error': str(e),
                    'name': Path(source1_file).name,
                    'job_data_for_batch_check': job_data
                }
                self.signals.log.emit(f'[FATAL WORKER ERROR] Job {i} failed: {e}')
                self.signals.finished_job.emit(error_result)
                all_results.append(error_result)

        self.signals.finished_all.emit(all_results)
