# vsg_qt/report_dialogs/batch_completion_dialog.py
"""
Batch completion dialog with Show Report button.

Replaces the simple QMessageBox with a proper dialog that includes
a button to open the detailed report viewer.
"""

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class BatchCompletionDialog(QDialog):
    """
    Dialog shown when batch processing completes.

    Shows summary statistics and provides buttons to close or view the
    detailed report.
    """

    def __init__(
        self,
        parent,
        total_jobs: int,
        successful: int,
        warnings: int,
        failed: int,
        stepping_jobs: list[dict[str, Any]],
        stepping_disabled_jobs: list[dict[str, Any]],
        report_path: Path | None = None
    ):
        """
        Initialize the completion dialog.

        Args:
            parent: Parent widget
            total_jobs: Total number of jobs processed
            successful: Number of successful jobs (no issues)
            warnings: Number of jobs with warnings
            failed: Number of failed jobs
            stepping_jobs: List of jobs that used stepping correction
            stepping_disabled_jobs: List of jobs with stepping detected but disabled
            report_path: Path to the JSON report file (for Show Report button)
        """
        super().__init__(parent)
        self.report_path = report_path
        self._setup_ui(total_jobs, successful, warnings, failed,
                       stepping_jobs, stepping_disabled_jobs)

    def _setup_ui(
        self,
        total_jobs: int,
        successful: int,
        warnings: int,
        failed: int,
        stepping_jobs: list[dict[str, Any]],
        stepping_disabled_jobs: list[dict[str, Any]]
    ):
        """Set up the dialog UI."""
        # Determine dialog type based on results
        if failed > 0:
            self.setWindowTitle("Batch Complete - Errors")
            icon_text = "X"
            icon_color = "#dc3545"  # Red
        elif stepping_disabled_jobs:
            self.setWindowTitle("Batch Complete - Review Required")
            icon_text = "!"
            icon_color = "#fd7e14"  # Orange
        elif warnings > 0 or stepping_jobs:
            self.setWindowTitle("Batch Complete - Warnings")
            icon_text = "!"
            icon_color = "#ffc107"  # Yellow
        else:
            self.setWindowTitle("Batch Complete")
            icon_text = "\u2713"  # Checkmark
            icon_color = "#28a745"  # Green

        self.setMinimumWidth(450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Header with icon
        header_layout = QHBoxLayout()

        icon_label = QLabel(icon_text)
        icon_label.setFixedSize(48, 48)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"""
            QLabel {{
                background-color: {icon_color};
                color: white;
                border-radius: 24px;
                font-size: 24px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(icon_label)

        title_label = QLabel(f"Processed {total_jobs} Job{'s' if total_jobs != 1 else ''}")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Summary section
        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)

        summary_label = QLabel("Batch Summary")
        summary_font = QFont()
        summary_font.setBold(True)
        summary_label.setFont(summary_font)
        summary_layout.addWidget(summary_label)

        # Stats grid
        stats_text = []
        stats_text.append(f"  Successful: {successful}")
        stats_text.append(f"  Warnings: {warnings}")
        stats_text.append(f"  Failed: {failed}")

        for line in stats_text:
            lbl = QLabel(line)
            if "Failed" in line and failed > 0:
                lbl.setStyleSheet("color: #dc3545;")  # Red
            elif "Warnings" in line and warnings > 0:
                lbl.setStyleSheet("color: #ffc107;")  # Yellow
            elif "Successful" in line and successful > 0:
                lbl.setStyleSheet("color: #28a745;")  # Green
            summary_layout.addWidget(lbl)

        layout.addWidget(summary_frame)

        # Stepping info section (if applicable)
        if stepping_jobs:
            stepping_frame = QFrame()
            stepping_frame.setFrameShape(QFrame.StyledPanel)
            stepping_layout = QVBoxLayout(stepping_frame)

            stepping_label = QLabel(f"Stepping Correction Applied ({len(stepping_jobs)} job{'s' if len(stepping_jobs) != 1 else ''})")
            stepping_font = QFont()
            stepping_font.setBold(True)
            stepping_label.setFont(stepping_font)
            stepping_layout.addWidget(stepping_label)

            info_label = QLabel("Quality checks performed - see report for details")
            info_label.setStyleSheet("font-style: italic;")
            stepping_layout.addWidget(info_label)

            # Show first few jobs
            for job_info in stepping_jobs[:3]:
                sources_str = ', '.join(job_info.get('sources', []))
                job_label = QLabel(f"  {job_info.get('name', 'Unknown')}: {sources_str}")
                stepping_layout.addWidget(job_label)

            if len(stepping_jobs) > 3:
                more_label = QLabel(f"  ... and {len(stepping_jobs) - 3} more")
                stepping_layout.addWidget(more_label)

            layout.addWidget(stepping_frame)

        # Stepping disabled warning section
        if stepping_disabled_jobs:
            warning_frame = QFrame()
            warning_frame.setFrameShape(QFrame.StyledPanel)
            warning_layout = QVBoxLayout(warning_frame)

            warning_label = QLabel(f"Stepping Detected - Correction Disabled ({len(stepping_disabled_jobs)} job{'s' if len(stepping_disabled_jobs) != 1 else ''})")
            warning_font = QFont()
            warning_font.setBold(True)
            warning_label.setFont(warning_font)
            warning_label.setStyleSheet("color: #ffc107;")  # Yellow - visible on both themes
            warning_layout.addWidget(warning_label)

            warning_text = QLabel("These files have timing inconsistencies.\nMANUAL REVIEW REQUIRED!")
            warning_layout.addWidget(warning_text)

            layout.addWidget(warning_frame)

        # Report path info
        if self.report_path:
            report_label = QLabel(f"Report: {self.report_path.name}")
            report_label.setToolTip(str(self.report_path))
            layout.addWidget(report_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        if self.report_path:
            show_report_btn = QPushButton("Show Report")
            show_report_btn.clicked.connect(self._show_report)
            show_report_btn.setMinimumWidth(100)
            button_layout.addWidget(show_report_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        ok_btn.setMinimumWidth(80)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)

    def _show_report(self):
        """Open the report viewer dialog."""
        if not self.report_path:
            return

        from .report_viewer import ReportViewer

        viewer = ReportViewer(self.report_path, self.parent())
        viewer.exec()
