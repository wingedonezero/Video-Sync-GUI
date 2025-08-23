# -*- coding: utf-8 -*-

"""
The background worker for running analysis/merge jobs without freezing the GUI.
"""

from pathlib import Path
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from typing import Dict, Any, List, Tuple, Optional

from vsg_core.pipeline import JobPipeline

class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    log = Signal(str)
    progress = Signal(float) # 0.0 to 1.0
    status = Signal(str)
    finished_job = Signal(dict) # Emits result for a single job
    finished_all = Signal(list) # Emits all results when batch is done

class JobWorker(QRunnable):
    """
    A QRunnable worker that executes a list of jobs in a separate thread.
    """
    def __init__(self, config: Dict[str, Any], jobs: List[Tuple[str, Optional[str], Optional[str]]], and_merge: bool, output_dir: str):
        super().__init__()
        self.config = config
        self.jobs = jobs
        self.and_merge = and_merge
        self.output_dir = output_dir
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        """The main entry point for the worker thread."""
        pipeline = JobPipeline(
            config=self.config,
            log_callback=lambda msg: self.signals.log.emit(msg),
            progress_callback=lambda val: self.signals.progress.emit(val)
        )

        all_results = []
        total_jobs = len(self.jobs)

        for i, (ref_file, sec_file, ter_file) in enumerate(self.jobs, 1):
            try:
                self.signals.status.emit(f'Processing {i}/{total_jobs}: {Path(ref_file).name}')
                result = pipeline.run_job(ref_file, sec_file, ter_file, self.and_merge, self.output_dir)
                self.signals.finished_job.emit(result)
                all_results.append(result)
            except Exception as e:
                error_result = {'status': 'Failed', 'error': str(e), 'name': Path(ref_file).name}
                self.signals.log.emit(f'[FATAL WORKER ERROR] Job {i} failed: {e}')
                self.signals.finished_job.emit(error_result)
                all_results.append(error_result)

        self.signals.finished_all.emit(all_results)
