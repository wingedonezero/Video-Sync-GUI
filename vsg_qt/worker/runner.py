# -*- coding: utf-8 -*-
"""
QRunnable worker that executes analysis/merge jobs via vsg_core.pipeline.JobPipeline
without freezing the GUI.
"""
from pathlib import Path
from typing import Dict, Any, List

from PySide6.QtCore import QRunnable, Slot

from vsg_core.pipeline import JobPipeline
from .signals import WorkerSignals


class JobWorker(QRunnable):
    """
    A QRunnable worker that executes a list of jobs in a separate thread.
    - Emits granular signals for UI updates.
    - Behavior is identical to the previous monolithic worker.py.
    """
    def __init__(self, config: Dict[str, Any], jobs: List[Dict], and_merge: bool, output_dir: str):
        super().__init__()
        self.config = config
        self.jobs = jobs                  # Each job is a dict: {'ref', 'sec'?, 'ter'?, 'manual_layout'?}
        self.and_merge = and_merge
        self.output_dir = output_dir
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        """Main entry executed in the worker thread."""
        pipeline = JobPipeline(
            config=self.config,
            log_callback=lambda msg: self.signals.log.emit(msg),
            progress_callback=lambda val: self.signals.progress.emit(val),
        )

        all_results: List[Dict[str, Any]] = []
        total_jobs = len(self.jobs)

        for i, job_data in enumerate(self.jobs, 1):
            ref_file = job_data['ref']
            try:
                self.signals.status.emit(f'Processing {i}/{total_jobs}: {Path(ref_file).name}')

                result = pipeline.run_job(
                    ref_file=ref_file,
                    sec_file=job_data.get('sec'),
                    ter_file=job_data.get('ter'),
                    and_merge=self.and_merge,
                    output_dir_str=self.output_dir,
                    manual_layout=job_data.get('manual_layout'),  # Manual selection payload (if any)
                )

                self.signals.finished_job.emit(result)
                all_results.append(result)

            except Exception as e:
                error_result = {
                    'status': 'Failed',
                    'error': str(e),
                    'name': Path(ref_file).name,
                }
                self.signals.log.emit(f'[FATAL WORKER ERROR] Job {i} failed: {e}')
                self.signals.finished_job.emit(error_result)
                all_results.append(error_result)

        self.signals.finished_all.emit(all_results)
