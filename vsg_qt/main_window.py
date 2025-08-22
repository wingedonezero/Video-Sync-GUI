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

class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video/Audio Sync & Merge - PySide6 Edition')
        self.setGeometry(100, 100, 1000, 600)

        self.config = AppConfig()
        self.thread_pool = QThreadPool()

        # --- UI Widgets ---
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
        """Initializes the layout and widgets of the main window."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Buttons ---
        top_button_layout = QHBoxLayout()
        options_btn = QPushButton('Settings…')
        options_btn.clicked.connect(self.open_options_dialog)
        top_button_layout.addWidget(options_btn)
        top_button_layout.addStretch()
        main_layout.addLayout(top_button_layout)

        # --- Input Files Group ---
        inputs_group = QGroupBox('Input Files (File or Directory)')
        inputs_layout = QVBoxLayout(inputs_group)
        inputs_layout.addLayout(self._create_file_input('Reference:', self.ref_input, self._browse_ref))
        inputs_layout.addLayout(self._create_file_input('Secondary:', self.sec_input, self._browse_sec))
        inputs_layout.addLayout(self._create_file_input('Tertiary:', self.ter_input, self._browse_ter))
        main_layout.addWidget(inputs_group)

        # --- Actions Group ---
        actions_group = QGroupBox('Actions')
        actions_layout = QHBoxLayout(actions_group)
        analyze_btn = QPushButton('Analyze Only')
        analyze_merge_btn = QPushButton('Analyze & Merge')
        analyze_btn.clicked.connect(lambda: self.start_job(and_merge=False))
        analyze_merge_btn.clicked.connect(lambda: self.start_job(and_merge=True))
        actions_layout.addWidget(analyze_btn)
        actions_layout.addWidget(analyze_merge_btn)
        actions_layout.addStretch()
        main_layout.addWidget(actions_group)

        # --- Status & Progress ---
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel('Status:'))
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        main_layout.addLayout(status_layout)

        # --- Results Display ---
        results_group = QGroupBox('Latest Job Results')
        results_layout = QHBoxLayout(results_group)
        results_layout.addWidget(QLabel('Secondary Delay:'))
        results_layout.addWidget(self.sec_delay_label)
        results_layout.addSpacing(20)
        results_layout.addWidget(QLabel('Tertiary Delay:'))
        results_layout.addWidget(self.ter_delay_label)
        results_layout.addStretch()
        main_layout.addWidget(results_group)

        # --- Log Output ---
        log_group = QGroupBox('Log')
        log_layout = QVBoxLayout(log_group)
        self.log_output.setReadOnly(True)
        self.log_output.setFontFamily('monospace')
        log_layout.addWidget(self.log_output)
        main_layout.addWidget(log_group)

    def _create_file_input(self, label_text: str, line_edit: QLineEdit, browse_slot):
        """Helper to create a labeled file input row."""
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text), 1)
        layout.addWidget(line_edit, 8)
        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(browse_slot)
        layout.addWidget(browse_btn, 1)
        return layout

    def _browse_ref(self):
        self._browse_for_path(self.ref_input, "Select Reference File or Directory")

    def _browse_sec(self):
        self._browse_for_path(self.sec_input, "Select Secondary File or Directory")

    def _browse_ter(self):
        self._browse_for_path(self.ter_input, "Select Tertiary File or Directory")

    def _browse_for_path(self, line_edit: QLineEdit, caption: str):
        """Opens a file dialog that accepts both files and directories."""
        dialog = QFileDialog(self, caption)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile) # Allows selecting files or dirs
        if dialog.exec():
            line_edit.setText(dialog.selectedFiles()[0])

    def open_options_dialog(self):
        """Opens the settings dialog."""
        dialog = OptionsDialog(self.config, self)
        if dialog.exec():
            self.config.save()
            self.append_log('Settings saved.')

    def apply_config_to_ui(self):
        """Applies loaded settings to the UI (e.g., last used paths)."""
        self.ref_input.setText(self.config.get('last_ref_path', ''))
        self.sec_input.setText(self.config.get('last_sec_path', ''))
        self.ter_input.setText(self.config.get('last_ter_path', ''))

    def save_ui_to_config(self):
        """Saves current UI state (e.g., paths) to the config object."""
        self.config.set('last_ref_path', self.ref_input.text())
        self.config.set('last_sec_path', self.sec_input.text())
        self.config.set('last_ter_path', self.ter_input.text())
        self.config.save()

    def start_job(self, and_merge: bool):
        """Prepares and starts a background worker for the job."""
        ref_path = self.ref_input.text().strip()
        if not ref_path or not Path(ref_path).exists():
            QMessageBox.warning(self, "Input Error", "A valid Reference path is required.")
            return

        self.save_ui_to_config()
        self.log_output.clear()
        self.status_label.setText('Starting job…')
        self.progress_bar.setValue(0)
        self.sec_delay_label.setText('—')
        self.ter_delay_label.setText('—')

        worker = JobWorker(
            self.config.settings,
            ref_path,
            self.sec_input.text().strip() or None,
            self.ter_input.text().strip() or None,
            and_merge
        )

        # Connect worker signals to main thread slots
        worker.signals.log.connect(self.append_log)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.status.connect(self.update_status)
        worker.signals.finished.connect(self.job_finished)

        self.thread_pool.start(worker)

    # --- Worker Signal Slots ---

    def append_log(self, message: str):
        self.log_output.append(message)
        if self.config.get('log_autoscroll', True):
            self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def update_progress(self, value: float): # Value is 0.0 to 1.0
        self.progress_bar.setValue(int(value * 100))

    def update_status(self, message: str):
        self.status_label.setText(message)

    def job_finished(self, result: dict):
        status = result.get('status', 'Unknown')
        if status == 'Failed':
            self.update_status(f'Job failed: {result.get("error", "Unknown error")}')
            QMessageBox.critical(self, "Job Failed", result.get("error", "An unknown error occurred."))
        else:
            self.update_status(f'Job finished with status: {status}')

        if 'delay_sec' in result:
            self.sec_delay_label.setText(f"{result['delay_sec']} ms" if result['delay_sec'] is not None else "—")
        if 'delay_ter' in result:
            self.ter_delay_label.setText(f"{result['delay_ter']} ms" if result['delay_ter'] is not None else "—")
