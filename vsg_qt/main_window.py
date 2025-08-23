# -*- coding: utf-8 -*-

"""
The main window of the PyQt application.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFileDialog, QGroupBox, QTextEdit, QProgressBar,
    QMessageBox
)
from PySide6.QtCore import Qt, QThreadPool

from .options_dialog import OptionsDialog
from .worker import JobWorker
from vsg_core.config import AppConfig
from vsg_core.job_discovery import discover_jobs

class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video/Audio Sync & Merge - PySide6 Edition')
        self.setGeometry(100, 100, 1000, 600)

        self.config = AppConfig()
        self.thread_pool = QThreadPool()

        self.ref_input = QLineEdit()
        self.sec_input = QLineEdit()
        self.ter_input = QLineEdit()
        self.log_output = QTextEdit()
        self.progress_bar = QProgressBar()
        self.status_label = QLabel('Ready')
        self.sec_delay_label = QLabel('—')
        self.ter_delay_label = QLabel('—')

        self.setup_ui()
        self.apply_config_to_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        top_button_layout = QHBoxLayout()
        options_btn = QPushButton('Settings…')
        options_btn.clicked.connect(self.open_options_dialog)
        top_button_layout.addWidget(options_btn)
        top_button_layout.addStretch()
        main_layout.addLayout(top_button_layout)

        inputs_group = QGroupBox('Input Files (File or Directory)')
        inputs_layout = QVBoxLayout(inputs_group)
        inputs_layout.addLayout(self._create_file_input('Reference:', self.ref_input, self._browse_ref))
        inputs_layout.addLayout(self._create_file_input('Secondary:', self.sec_input, self._browse_sec))
        inputs_layout.addLayout(self._create_file_input('Tertiary:', self.ter_input, self._browse_ter))
        main_layout.addWidget(inputs_group)

        actions_group = QGroupBox('Actions')
        actions_layout = QHBoxLayout(actions_group)
        analyze_btn = QPushButton('Analyze Only')
        analyze_merge_btn = QPushButton('Analyze & Merge')
        analyze_btn.clicked.connect(lambda: self.start_batch(and_merge=False))
        analyze_merge_btn.clicked.connect(lambda: self.start_batch(and_merge=True))
        actions_layout.addWidget(analyze_btn)
        actions_layout.addWidget(analyze_merge_btn)
        actions_layout.addStretch()
        main_layout.addWidget(actions_group)

        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel('Status:'))
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        main_layout.addLayout(status_layout)

        results_group = QGroupBox('Latest Job Results')
        results_layout = QHBoxLayout(results_group)
        results_layout.addWidget(QLabel('Secondary Delay:'))
        results_layout.addWidget(self.sec_delay_label)
        results_layout.addSpacing(20)
        results_layout.addWidget(QLabel('Tertiary Delay:'))
        results_layout.addWidget(self.ter_delay_label)
        results_layout.addStretch()
        main_layout.addWidget(results_group)

        log_group = QGroupBox('Log')
        log_layout = QVBoxLayout(log_group)
        self.log_output.setReadOnly(True)
        self.log_output.setFontFamily('monospace')
        log_layout.addWidget(self.log_output)
        main_layout.addWidget(log_group)

    def _create_file_input(self, label_text: str, line_edit: QLineEdit, browse_slot):
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text), 1)
        layout.addWidget(line_edit, 8)
        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(browse_slot)
        layout.addWidget(browse_btn, 1)
        return layout

    def _browse_ref(self): self._browse_for_path(self.ref_input, "Select Reference File or Directory")
    def _browse_sec(self): self._browse_for_path(self.sec_input, "Select Secondary File or Directory")
    def _browse_ter(self): self._browse_for_path(self.ter_input, "Select Tertiary File or Directory")

    def _browse_for_path(self, line_edit: QLineEdit, caption: str):
        dialog = QFileDialog(self, caption)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if dialog.exec():
            line_edit.setText(dialog.selectedFiles()[0])

    def open_options_dialog(self):
        dialog = OptionsDialog(self.config, self)
        if dialog.exec():
            self.config.save()
            self.append_log('Settings saved.')

    def apply_config_to_ui(self):
        self.ref_input.setText(self.config.get('last_ref_path', ''))
        self.sec_input.setText(self.config.get('last_sec_path', ''))
        self.ter_input.setText(self.config.get('last_ter_path', ''))

    def save_ui_to_config(self):
        self.config.set('last_ref_path', self.ref_input.text())
        self.config.set('last_sec_path', self.sec_input.text())
        self.config.set('last_ter_path', self.ter_input.text())
        self.config.save()

    def start_batch(self, and_merge: bool):
        """Discovers jobs and starts the background worker for the batch."""
        self.save_ui_to_config()

        ref_path_str = self.ref_input.text().strip()

        try:
            jobs = discover_jobs(
                ref_path_str,
                self.sec_input.text().strip() or None,
                self.ter_input.text().strip() or None
            )
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Job Discovery Error", str(e))
            return

        # --- New Logic: Determine output directory ---
        output_dir = self.config.get('output_folder')
        is_batch = Path(ref_path_str).is_dir()
        if is_batch:
            output_dir = str(Path(output_dir) / Path(ref_path_str).name)

        self.log_output.clear()
        self.status_label.setText(f'Starting batch of {len(jobs)} jobs…')
        self.progress_bar.setValue(0)
        self.sec_delay_label.setText('—')
        self.ter_delay_label.setText('—')

        worker = JobWorker(self.config.settings, jobs, and_merge, output_dir)

        worker.signals.log.connect(self.append_log)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.status.connect(self.update_status)
        worker.signals.finished_job.connect(self.job_finished)
        worker.signals.finished_all.connect(self.batch_finished)

        self.thread_pool.start(worker)

    def append_log(self, message: str):
        self.log_output.append(message)
        if self.config.get('log_autoscroll', True):
            self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def update_progress(self, value: float):
        self.progress_bar.setValue(int(value * 100))

    def update_status(self, message: str):
        self.status_label.setText(message)

    def job_finished(self, result: dict):
        if 'delay_sec' in result:
            self.sec_delay_label.setText(f"{result['delay_sec']} ms" if result['delay_sec'] is not None else "—")
        if 'delay_ter' in result:
            self.ter_delay_label.setText(f"{result['delay_ter']} ms" if result['delay_ter'] is not None else "—")

        name = result.get('name', '')
        status = result.get('status', 'Unknown')
        if status == 'Failed':
            self.append_log(f"--- Job Summary for {name}: FAILED ---")
        else:
            self.append_log(f"--- Job Summary for {name}: {status} ---")

    def batch_finished(self, all_results: list):
        self.update_status(f'All {len(all_results)} jobs finished.')
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "Batch Complete", f"Finished processing {len(all_results)} jobs.")
