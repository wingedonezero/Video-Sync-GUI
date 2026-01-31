# vsg_qt/main_window/window.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vsg_core.config import AppConfig

from .controller import MainController


class MainWindow(QMainWindow):
    """Slim UI shell: builds widgets & delegates logic to MainController."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video/Audio Sync & Merge - PySide6 Edition")
        self.setGeometry(100, 100, 1000, 600)

        self.config = AppConfig()
        self.controller = MainController(self)

        self._build_ui()
        self.controller.apply_config_to_ui()

    def _build_ui(self):
        # Quick Analysis Inputs
        self.ref_input = QLineEdit()
        self.sec_input = QLineEdit()
        self.ter_input = QLineEdit()

        # Log and Status
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFontFamily("monospace")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.status_label = QLabel("Ready")

        # Delay Labels
        self.delay_labels: list[QLabel] = []

        # Other Controls
        self.archive_logs_check = QCheckBox(
            "Archive logs to a zip file on batch completion"
        )

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        top_row = QHBoxLayout()
        self.options_btn = QPushButton("Settings…")
        top_row.addWidget(self.options_btn)
        top_row.addStretch()
        main_layout.addLayout(top_row)

        actions_group = QGroupBox("Main Workflow")
        actions_layout = QVBoxLayout(actions_group)
        self.queue_jobs_btn = QPushButton("Open Job Queue for Merging...")
        self.queue_jobs_btn.setStyleSheet("font-size: 14px; padding: 5px;")
        actions_layout.addWidget(self.queue_jobs_btn)
        actions_layout.addWidget(self.archive_logs_check)
        main_layout.addWidget(actions_group)

        analysis_group = QGroupBox("Quick Analysis (Analyze Only)")
        analysis_layout = QVBoxLayout(analysis_group)
        analysis_layout.addLayout(
            self._create_file_input(
                "Source 1 (Reference):",
                self.ref_input,
                lambda: self.controller.browse_for_path(
                    self.ref_input, "Select Reference File or Directory"
                ),
            )
        )
        analysis_layout.addLayout(
            self._create_file_input(
                "Source 2:",
                self.sec_input,
                lambda: self.controller.browse_for_path(
                    self.sec_input, "Select Secondary File or Directory"
                ),
            )
        )
        analysis_layout.addLayout(
            self._create_file_input(
                "Source 3:",
                self.ter_input,
                lambda: self.controller.browse_for_path(
                    self.ter_input, "Select Tertiary File or Directory"
                ),
            )
        )
        analyze_btn = QPushButton("Analyze Only")
        analysis_layout.addWidget(analyze_btn, 0, Qt.AlignRight)
        main_layout.addWidget(analysis_group)

        # Connect signals
        self.options_btn.clicked.connect(self.controller.open_options_dialog)
        analyze_btn.clicked.connect(self.controller.start_batch_analyze_only)
        self.queue_jobs_btn.clicked.connect(self.controller.open_job_queue)

        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        main_layout.addLayout(status_layout)

        results_group = QGroupBox("Latest Job Results")
        results_layout = QHBoxLayout(results_group)
        # DYNAMIC FIX: Create a few labels for delays
        for i in range(2, 5):  # Create labels for Source 2, 3, 4
            results_layout.addWidget(QLabel(f"Source {i} Delay:"))
            delay_label = QLabel("—")
            self.delay_labels.append(delay_label)
            results_layout.addWidget(delay_label)
            results_layout.addSpacing(20)
        # Store references to the first two for backward compatibility if needed elsewhere
        self.sec_delay_label = self.delay_labels[0]
        self.ter_delay_label = self.delay_labels[1]
        results_layout.addStretch()
        main_layout.addWidget(results_group)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.addWidget(self.log_output)
        main_layout.addWidget(log_group)

    def _create_file_input(self, label_text: str, line_edit: QLineEdit, on_browse):
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text), 1)
        layout.addWidget(line_edit, 8)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(on_browse)
        layout.addWidget(browse_btn, 1)
        return layout

    def closeEvent(self, event):
        self.controller.on_close()
        super().closeEvent(event)
