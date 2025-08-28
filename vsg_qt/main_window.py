# vsg_qt/main_window.py

# -*- coding: utf-8 -*-
import sys
import shutil
from pathlib import Path
from collections import Counter

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFileDialog, QGroupBox, QTextEdit, QProgressBar,
    QMessageBox, QRadioButton, QCheckBox
)
from PySide6.QtCore import Qt, QThreadPool

from .options_dialog import OptionsDialog
from .worker import JobWorker
from vsg_core.config import AppConfig
from vsg_core.job_discovery import discover_jobs
from vsg_core.process import CommandRunner
from vsg_core import mkv_utils
from .manual_selection_dialog import ManualSelectionDialog


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
        self.plan_mode_radio = QRadioButton("Merge Plan")
        self.manual_mode_radio = QRadioButton("Manual Selection")
        self.auto_apply_check = QCheckBox("Auto-apply this layout to all matching files in batch")
        self.options_btn = QPushButton('Settings…')
        self.setup_ui()
        self.apply_config_to_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        top_button_layout = QHBoxLayout()
        self.options_btn.clicked.connect(self.open_options_dialog)
        top_button_layout.addWidget(self.options_btn)
        top_button_layout.addStretch()
        main_layout.addLayout(top_button_layout)

        inputs_group = QGroupBox('Input Files (File or Directory)')
        inputs_layout = QVBoxLayout(inputs_group)
        inputs_layout.addLayout(self._create_file_input('Reference:', self.ref_input, self._browse_ref))
        inputs_layout.addLayout(self._create_file_input('Secondary:', self.sec_input, self._browse_sec))
        inputs_layout.addLayout(self._create_file_input('Tertiary:', self.ter_input, self._browse_ter))
        main_layout.addWidget(inputs_group)

        merge_mode_group = QGroupBox("Merge Mode")
        merge_mode_layout = QVBoxLayout(merge_mode_group)
        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.plan_mode_radio)
        radio_layout.addWidget(self.manual_mode_radio)
        radio_layout.addStretch()
        merge_mode_layout.addLayout(radio_layout)
        merge_mode_layout.addWidget(self.auto_apply_check)
        self.plan_mode_radio.toggled.connect(self._on_merge_mode_changed)
        main_layout.addWidget(merge_mode_group)

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

        # ... (rest of setup_ui is unchanged)
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


    def _on_merge_mode_changed(self, checked):
        # The new auto-apply checkbox is only visible and relevant for manual mode
        is_plan_mode = self.plan_mode_radio.isChecked()
        self.auto_apply_check.setVisible(not is_plan_mode)

        if is_plan_mode:
            self.config.set('merge_mode', 'plan')
            self.options_btn.setEnabled(True)
        else:
            self.config.set('merge_mode', 'manual')
            self.options_btn.setEnabled(False)
        self.config.save()

    def _generate_track_signature(self, track_info):
        """Creates a stable signature of a file's track layout based on counts."""
        return Counter(
            f"{t['source']}_{t['type']}"
            for source_list in track_info.values() for t in source_list
        )

    def start_batch(self, and_merge: bool):
        """Discovers jobs and starts the background worker for the batch."""
        self.save_ui_to_config()
        ref_path_str = self.ref_input.text().strip()
        try:
            initial_jobs = discover_jobs(
                ref_path_str,
                self.sec_input.text().strip() or None,
                self.ter_input.text().strip() or None
            )
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Job Discovery Error", str(e))
            return
        if not initial_jobs:
            QMessageBox.information(self, "No Jobs Found", "No valid jobs could be found.")
            return

        final_jobs = initial_jobs
        if self.config.get('merge_mode') == 'manual' and and_merge:
            processed_jobs = []
            last_manual_layout = None
            last_track_signature = None
            auto_apply_enabled = self.auto_apply_check.isChecked()

            tool_paths = {t: shutil.which(t) for t in ['mkvmerge']}
            if not tool_paths['mkvmerge']:
                QMessageBox.critical(self, "Tool Not Found", "mkvmerge not found.")
                return

            runner = CommandRunner(self.config.settings, lambda msg: self.append_log(f'[Pre-Scan] {msg}'))

            for i, job_data in enumerate(initial_jobs):
                self.status_label.setText(f"Pre-scanning {Path(job_data['ref']).name}...")
                try:
                    track_info = mkv_utils.get_track_info_for_dialog(
                        job_data['ref'], job_data.get('sec'), job_data.get('ter'),
                        runner, tool_paths
                    )
                except Exception as e:
                    QMessageBox.warning(self, "Pre-scan Failed", f"Could not analyze tracks for {Path(job_data['ref']).name}:\n{e}")
                    return

                current_signature = self._generate_track_signature(track_info)
                current_layout = None

                # --- NEW AUTO-APPLY LOGIC ---
                # Decide if we can skip the dialog entirely
                should_auto_apply = (
                    auto_apply_enabled and
                    last_manual_layout is not None and
                    last_track_signature is not None and
                    current_signature == last_track_signature
                )

                if should_auto_apply:
                    self.append_log(f"Auto-applying previous layout to {Path(job_data['ref']).name}...")
                    current_layout = last_manual_layout
                else:
                    # Show the dialog if not auto-applying
                    layout_to_carry_over = None
                    if last_track_signature and current_signature == last_track_signature:
                        layout_to_carry_over = last_manual_layout

                    dialog = ManualSelectionDialog(track_info, self, previous_layout=layout_to_carry_over)
                    if dialog.exec():
                        current_layout = dialog.get_manual_layout()
                    else:
                        self.append_log("Batch run cancelled by user.")
                        self.status_label.setText("Ready")
                        return

                if current_layout:
                    job_data['manual_layout'] = current_layout
                    processed_jobs.append(job_data)
                    last_manual_layout = current_layout
                    last_track_signature = current_signature
                else:
                    self.append_log(f"Job '{Path(job_data['ref']).name}' was skipped.")
                    last_manual_layout = None
                    last_track_signature = None

            final_jobs = processed_jobs

        # ... (rest of function is unchanged)
        if not final_jobs:
            self.status_label.setText("Ready")
            self.append_log("No jobs to run after user selection.")
            return
        output_dir = self.config.get('output_folder')
        is_batch = Path(ref_path_str).is_dir() and len(final_jobs) > 1
        if is_batch:
            output_dir = str(Path(output_dir) / Path(ref_path_str).name)
        self.log_output.clear()
        self.status_label.setText(f'Starting batch of {len(final_jobs)} jobs…')
        self.progress_bar.setValue(0)
        self.sec_delay_label.setText('—')
        self.ter_delay_label.setText('—')
        worker = JobWorker(self.config.settings, final_jobs, and_merge, output_dir)
        worker.signals.log.connect(self.append_log)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.status.connect(self.update_status)
        worker.signals.finished_job.connect(self.job_finished)
        worker.signals.finished_all.connect(self.batch_finished)
        self.thread_pool.start(worker)

    # ... (the rest of the file is unchanged)
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
    def open_options_dialog(self):
        dialog = OptionsDialog(self.config, self)
        if dialog.exec():
            self.config.save()
            self.append_log('Settings saved.')
    def apply_config_to_ui(self):
        self.ref_input.setText(self.config.get('last_ref_path', ''))
        self.sec_input.setText(self.config.get('last_sec_path', ''))
        self.ter_input.setText(self.config.get('last_ter_path', ''))
        self._on_merge_mode_changed(self.plan_mode_radio.isChecked()) # This will set visibility
    def save_ui_to_config(self):
        self.config.set('last_ref_path', self.ref_input.text())
        self.config.set('last_sec_path', self.sec_input.text())
        self.config.set('last_ter_path', self.ter_input.text())
        self.config.save()
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
    def closeEvent(self, event):
        self.save_ui_to_config()
        super().closeEvent(event)
