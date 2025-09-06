# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFileDialog, QGroupBox, QTextEdit, QProgressBar,
    QCheckBox
)
from PySide6.QtCore import Qt

from vsg_core.config import AppConfig
from .controller import MainController


class MainWindow(QMainWindow):
    """Slim UI shell: builds widgets & delegates logic to MainController."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video/Audio Sync & Merge - PySide6 Edition')
        self.setGeometry(100, 100, 1000, 600)

        self.config = AppConfig()
        self.controller = MainController(self)

        self._build_ui()
        self.controller.apply_config_to_ui()

    # ---------- UI construction ----------
    def _build_ui(self):
        self.ref_input = QLineEdit()
        self.sec_input = QLineEdit()
        self.ter_input = QLineEdit()

        self.log_output = QTextEdit(); self.log_output.setReadOnly(True); self.log_output.setFontFamily('monospace')
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); self.progress_bar.setTextVisible(True)
        self.status_label = QLabel('Ready')
        self.sec_delay_label = QLabel('—')
        self.ter_delay_label = QLabel('—')

        self.auto_apply_check = QCheckBox("Auto-apply this layout to all matching files in batch")
        self.auto_apply_strict_check = QCheckBox("Strict match (type + lang + codec)")
        self.archive_logs_check = QCheckBox("Archive logs to a zip file on batch completion")

        central = QWidget(); self.setCentralWidget(central)
        main = QVBoxLayout(central)

        # Top row
        top_row = QHBoxLayout()
        self.options_btn = QPushButton('Settings…')
        self.options_btn.clicked.connect(self.controller.open_options_dialog)
        top_row.addWidget(self.options_btn); top_row.addStretch()
        main.addLayout(top_row)

        # Inputs
        inputs_group = QGroupBox('Input Files (File or Directory)')
        inputs_layout = QVBoxLayout(inputs_group)
        inputs_layout.addLayout(self._create_file_input('Reference:', self.ref_input, lambda: self.controller.browse_for_path(self.ref_input, "Select Reference File or Directory")))
        inputs_layout.addLayout(self._create_file_input('Secondary:', self.sec_input, lambda: self.controller.browse_for_path(self.sec_input, "Select Secondary File or Directory")))
        inputs_layout.addLayout(self._create_file_input('Tertiary:', self.ter_input, lambda: self.controller.browse_for_path(self.ter_input, "Select Tertiary File or Directory")))
        main.addWidget(inputs_group)

        # Manual behavior
        manual_group = QGroupBox("Manual Selection Behavior")
        manual_layout = QVBoxLayout(manual_group)
        helper = QLabel("For Analyze & Merge, you’ll select tracks per file. "
                        "Auto-apply reuses your last layout when the track signature matches.")
        helper.setWordWrap(True)
        manual_layout.addWidget(helper)
        manual_layout.addWidget(self.auto_apply_check)
        manual_layout.addWidget(self.auto_apply_strict_check)
        main.addWidget(manual_group)

        # Actions
        actions_group = QGroupBox('Actions')
        actions_main_layout = QVBoxLayout(actions_group)
        actions_button_layout = QHBoxLayout()
        analyze_btn = QPushButton('Analyze Only')
        analyze_merge_btn = QPushButton('Analyze & Merge')
        analyze_btn.clicked.connect(lambda: self.controller.start_batch(and_merge=False))
        analyze_merge_btn.clicked.connect(lambda: self.controller.start_batch(and_merge=True))
        actions_button_layout.addWidget(analyze_btn)
        actions_button_layout.addWidget(analyze_merge_btn)
        actions_button_layout.addStretch()
        actions_main_layout.addLayout(actions_button_layout)
        actions_main_layout.addWidget(self.archive_logs_check)
        main.addWidget(actions_group)

        # Status / progress
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel('Status:'))
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        main.addLayout(status_layout)

        # Results
        results_group = QGroupBox('Latest Job Results')
        results_layout = QHBoxLayout(results_group)
        results_layout.addWidget(QLabel('Secondary Delay:'))
        results_layout.addWidget(self.sec_delay_label)
        results_layout.addSpacing(20)
        results_layout.addWidget(QLabel('Tertiary Delay:'))
        results_layout.addWidget(self.ter_delay_label)
        results_layout.addStretch()
        main.addWidget(results_group)

        # Log
        log_group = QGroupBox('Log')
        log_layout = QVBoxLayout(log_group)
        log_layout.addWidget(self.log_output)
        main.addWidget(log_group)

    def _create_file_input(self, label_text: str, line_edit: QLineEdit, on_browse):
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text), 1)
        layout.addWidget(line_edit, 8)
        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(on_browse)
        layout.addWidget(browse_btn, 1)
        return layout

    # ---------- lifecycle ----------
    def closeEvent(self, event):
        self.controller.on_close()
        super().closeEvent(event)
