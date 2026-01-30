# vsg_qt/report_dialogs/report_viewer.py
"""
Report viewer dialog for displaying detailed batch results.

Shows a table of all jobs with their status, warnings, stepping info,
and sync delays. Selecting a job shows detailed information in a panel below.
"""

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vsg_core.reporting import ReportWriter


class ReportViewer(QDialog):
    """
    Dialog for viewing detailed batch report.

    Features:
    - Table view of all jobs with status, issues, stepping, delays
    - Color coding for status (green=success, yellow=warnings, red=failed)
    - Details panel showing full info for selected job
    """

    def __init__(self, report_path: Path, parent=None):
        """
        Initialize the report viewer.

        Args:
            report_path: Path to the JSON report file
            parent: Parent widget
        """
        super().__init__(parent)
        self.report_path = report_path
        self.report_data: dict[str, Any] = {}
        self.current_job: dict[str, Any] | None = None

        self._load_report()
        self._setup_ui()

    def _load_report(self):
        """Load the report data from disk."""
        try:
            self.report_data = ReportWriter.load(self.report_path)
        except Exception as e:
            self.report_data = {"error": str(e), "jobs": []}

    def _setup_ui(self):
        """Set up the dialog UI."""
        batch_name = self.report_data.get("batch_name", "Unknown")
        self.setWindowTitle(f"Batch Report: {batch_name}")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header with summary
        header = self._create_header()
        layout.addWidget(header)

        # Main content splitter (table + details)
        splitter = QSplitter(Qt.Vertical)

        # Job table
        self.table = self._create_table()
        splitter.addWidget(self.table)

        # Details panel
        details_widget = self._create_details_panel()
        splitter.addWidget(details_widget)

        # Set initial splitter sizes (60% table, 40% details)
        splitter.setSizes([400, 250])

        layout.addWidget(splitter)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setMinimumWidth(80)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # Populate table
        self._populate_table()

    def _create_header(self) -> QWidget:
        """Create the header widget with summary info."""
        header = QFrame()
        header.setFrameShape(QFrame.StyledPanel)
        layout = QHBoxLayout(header)

        # Summary stats
        summary = self.report_data.get("summary", {})
        successful = summary.get("successful", 0)
        warnings = summary.get("warnings", 0)
        failed = summary.get("failed", 0)
        total = self.report_data.get("total_jobs", 0)

        summary_text = f"Summary: {successful} successful"
        if warnings > 0:
            summary_text += f", {warnings} with warnings"
        if failed > 0:
            summary_text += f", {failed} failed"
        summary_text += f" ({total} total)"

        summary_label = QLabel(summary_text)
        summary_font = QFont()
        summary_font.setBold(True)
        summary_label.setFont(summary_font)
        layout.addWidget(summary_label)

        layout.addStretch()

        # Output directory
        output_dir = self.report_data.get("output_directory", "")
        if output_dir:
            dir_label = QLabel(f"Output: {Path(output_dir).name}")
            dir_label.setToolTip(output_dir)
            layout.addWidget(dir_label)

        return header

    def _create_table(self) -> QTableWidget:
        """Create the jobs table."""
        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(
            ["#", "Name", "Status", "Issues", "Stepping", "Stability", "Delays"]
        )

        # Configure table
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        # Column widths
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # #
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Name
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Issues
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Stepping
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Stability
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Delays

        # Connect selection changed
        table.itemSelectionChanged.connect(self._on_selection_changed)

        return table

    def _create_details_panel(self) -> QWidget:
        """Create the details panel."""
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)

        # Title
        self.details_title = QLabel("Select a job to view details")
        title_font = QFont()
        title_font.setBold(True)
        self.details_title.setFont(title_font)
        layout.addWidget(self.details_title)

        # Details text area
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        layout.addWidget(self.details_text)

        return panel

    def _populate_table(self):
        """Populate the table with job data."""
        jobs = self.report_data.get("jobs", [])
        self.table.setRowCount(len(jobs))

        for row, job in enumerate(jobs):
            # Index
            idx_item = QTableWidgetItem(str(job.get("index", row + 1)))
            idx_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, idx_item)

            # Name
            name_item = QTableWidgetItem(job.get("name", "Unknown"))
            self.table.setItem(row, 1, name_item)

            # Status
            status = job.get("status", "Unknown")
            status_text = ReportWriter.get_job_status_summary(job)
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignCenter)

            # Color coding
            if status == "Failed":
                status_item.setForeground(QColor("#dc3545"))  # Red
                status_item.setBackground(QColor("#f8d7da"))
            elif "Warning" in status_text:
                status_item.setForeground(QColor("#856404"))  # Dark yellow
                status_item.setBackground(QColor("#fff3cd"))
            else:
                status_item.setForeground(QColor("#155724"))  # Dark green
                status_item.setBackground(QColor("#d4edda"))

            self.table.setItem(row, 2, status_item)

            # Issues count
            issues = job.get("audit_results", {}).get("total_issues", 0)
            issues_item = QTableWidgetItem(str(issues) if issues > 0 else "-")
            issues_item.setTextAlignment(Qt.AlignCenter)
            if issues > 0:
                issues_item.setForeground(QColor("#856404"))
            self.table.setItem(row, 3, issues_item)

            # Stepping
            stepping_text = ReportWriter.get_stepping_summary(job)
            stepping_item = QTableWidgetItem(stepping_text)
            stepping_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, stepping_item)

            # Stability
            stability_text = ReportWriter.get_sync_stability_summary(job)
            stability_item = QTableWidgetItem(stability_text)
            stability_item.setTextAlignment(Qt.AlignCenter)
            # Color coding for stability issues
            if stability_text != "-" and stability_text != "OK":
                stability_item.setForeground(QColor("#856404"))
            self.table.setItem(row, 5, stability_item)

            # Delays
            delays_text = ReportWriter.get_delays_summary(job)
            delays_item = QTableWidgetItem(delays_text)
            delays_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 6, delays_item)

        # Select first row if any
        if jobs:
            self.table.selectRow(0)

    def _on_selection_changed(self):
        """Handle table selection change."""
        selected = self.table.selectedItems()
        if not selected:
            self.current_job = None
            self._update_details(None)
            return

        row = selected[0].row()
        jobs = self.report_data.get("jobs", [])
        if 0 <= row < len(jobs):
            self.current_job = jobs[row]
            self._update_details(self.current_job)

    def _update_details(self, job: dict[str, Any] | None):
        """Update the details panel with job info."""
        if not job:
            self.details_title.setText("Select a job to view details")
            self.details_text.clear()
            return

        name = job.get("name", "Unknown")
        self.details_title.setText(f"Details for: {name}")

        # Build details text
        lines = []

        # Status
        status = job.get("status", "Unknown")
        lines.append(f"<b>Status:</b> {status}")

        # Error (if failed)
        error = job.get("error")
        if error:
            lines.append(f"<b style='color: #dc3545;'>Error:</b> {error}")

        lines.append("")

        # Output path
        output_path = job.get("output_path")
        if output_path:
            lines.append(f"<b>Output:</b> {output_path}")

        # Completed time
        completed_at = job.get("completed_at")
        if completed_at:
            lines.append(f"<b>Completed:</b> {completed_at}")

        lines.append("")

        # Delays
        delays = job.get("delays", {})
        if delays:
            lines.append("<b>Sync Delays:</b>")
            for source, delay in sorted(delays.items()):
                sign = "+" if delay >= 0 else ""
                lines.append(f"  {source}: {sign}{delay}ms")
        else:
            lines.append("<b>Sync Delays:</b> None")

        lines.append("")

        # Stepping info
        stepping = job.get("stepping", {})
        applied_to = stepping.get("applied_to", [])
        detected_disabled = stepping.get("detected_disabled", [])
        detected_separated = stepping.get("detected_separated", [])
        quality_issues = stepping.get("quality_issues", [])

        if applied_to or detected_disabled or detected_separated:
            lines.append("<b>Stepping Correction:</b>")

            if applied_to:
                lines.append(
                    f"  <span style='color: #28a745;'>Applied to:</span> {', '.join(applied_to)}"
                )

            if detected_disabled:
                lines.append(
                    f"  <span style='color: #ffc107;'>Detected (disabled):</span> {', '.join(detected_disabled)}"
                )

            if detected_separated:
                lines.append(
                    f"  <span style='color: #fd7e14;'>Detected (separated):</span> {', '.join(detected_separated)}"
                )

            if quality_issues:
                lines.append("")
                lines.append("<b style='color: #dc3545;'>Stepping Quality Issues:</b>")
                for issue in quality_issues:
                    severity = issue.get("severity", "info")
                    message = issue.get("message", "")
                    if severity == "high":
                        lines.append(
                            f"  <span style='color: #dc3545;'>! {message}</span>"
                        )
                    else:
                        lines.append(f"  - {message}")
        else:
            lines.append("<b>Stepping Correction:</b> Not applied")

        lines.append("")

        # Sync stability info
        sync_stability = job.get("sync_stability", [])
        if sync_stability:
            lines.append("<b>Sync Stability (Correlation Variance):</b>")
            for stability in sync_stability:
                source = stability.get("source", "Unknown")
                variance_detected = stability.get("variance_detected", False)
                max_variance = stability.get("max_variance_ms", 0)
                std_dev = stability.get("std_dev_ms", 0)
                outliers = stability.get("outliers", [])

                if variance_detected:
                    lines.append(
                        f"  <span style='color: #fd7e14;'>{source}: Variance detected</span>"
                    )
                    lines.append(
                        f"    Max variance: {max_variance:.3f}ms, Std dev: {std_dev:.3f}ms"
                    )
                    if outliers:
                        outlier_strs = [
                            f"{o.get('delay_ms', 0):.1f}ms" for o in outliers[:5]
                        ]
                        lines.append(f"    Outliers: {', '.join(outlier_strs)}")
                else:
                    lines.append(f"  {source}: OK")
        else:
            lines.append("<b>Sync Stability:</b> Not analyzed")

        lines.append("")

        # Audit results
        audit = job.get("audit_results", {})
        total_issues = audit.get("total_issues", 0)
        audit_details = audit.get("details", [])

        lines.append(f"<b>Audit Issues:</b> {total_issues}")
        if audit_details:
            for detail in audit_details:
                auditor = detail.get("auditor", "Unknown")
                message = detail.get("message", "")
                lines.append(f"  - [{auditor}] {message}")

        # Validator issues (for future)
        validator_issues = job.get("validator_issues", [])
        if validator_issues:
            lines.append("")
            lines.append("<b>Validator Issues:</b>")
            for issue in validator_issues:
                lines.append(f"  - {issue}")

        self.details_text.setHtml("<br>".join(lines))
