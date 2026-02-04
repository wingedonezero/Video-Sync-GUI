# vsg_core/reporting/report_writer.py
"""
Persistent batch report writer.

Writes job results to disk as they complete, preventing data loss during large
batches. Reports are stored as JSON for easy parsing and can be loaded later
for display in the ReportViewer.
"""

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles numpy types."""

    def default(self, obj):
        if HAS_NUMPY:
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        return super().default(obj)


class ReportWriter:
    """
    Manages persistent batch reports.

    Creates a JSON report file at batch start and updates it after each job
    completes. Uses atomic writes to prevent corruption if the process crashes.
    """

    REPORT_VERSION = "1.0"

    def __init__(self, logs_folder: Path):
        """
        Initialize the report writer.

        Args:
            logs_folder: Directory where reports will be saved
        """
        self.logs_folder = Path(logs_folder)
        self.logs_folder.mkdir(parents=True, exist_ok=True)
        self.current_report_path: Path | None = None
        self.report_data: dict[str, Any] = {}

    def create_report(
        self, batch_name: str, is_batch: bool, output_dir: str, total_jobs: int
    ) -> Path:
        """
        Initialize a new report file at batch start.

        Args:
            batch_name: Name derived from source1 folder (batch) or filename (single)
            is_batch: True if processing multiple jobs
            output_dir: Directory where output files are written
            total_jobs: Total number of jobs to process

        Returns:
            Path to the created report file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Sanitize batch name for filename
        safe_name = self._sanitize_filename(batch_name)

        if is_batch:
            filename = f"{safe_name}_batch_report_{timestamp}.json"
        else:
            filename = f"{safe_name}_report_{timestamp}.json"

        self.current_report_path = self.logs_folder / filename

        self.report_data = {
            "version": self.REPORT_VERSION,
            "created_at": datetime.now().isoformat(),
            "finalized_at": None,
            "batch_name": batch_name,
            "is_batch": is_batch,
            "output_directory": output_dir,
            "total_jobs": total_jobs,
            "summary": {"successful": 0, "warnings": 0, "failed": 0, "total_issues": 0},
            "jobs": [],
        }

        self._write_report()
        return self.current_report_path

    def add_job(self, job_result: dict[str, Any], job_index: int) -> None:
        """
        Add a completed job's results to the report.

        Called immediately after each job finishes. Writes to disk right away
        so data is not lost if something goes wrong later.

        Args:
            job_result: Dict from PipelineResult (via asdict) with job results
            job_index: 1-based index of this job in the batch
        """
        if not self.report_data:
            return

        # Build the job entry
        job_entry = {
            "index": job_index,
            "name": job_result.get("name", "Unknown"),
            "status": job_result.get("status", "Unknown"),
            "output_path": job_result.get("output"),
            "completed_at": datetime.now().isoformat(),
            "delays": job_result.get("delays", {}),
            "error": job_result.get("error"),
            # Stepping information
            "stepping": {
                "applied_to": job_result.get("stepping_sources", []),
                "detected_disabled": job_result.get("stepping_detected_disabled", []),
                "detected_separated": job_result.get("stepping_detected_separated", []),
                "quality_issues": job_result.get("stepping_quality_issues", []),
            },
            # Audit results
            "audit_results": {
                "total_issues": job_result.get("issues", 0),
                "details": job_result.get("audit_details", []),
            },
            # Sync stability (correlation variance)
            "sync_stability": job_result.get("sync_stability_issues", []),
            # Validator issues (for future expansion)
            "validator_issues": job_result.get("validator_issues", []),
        }

        self.report_data["jobs"].append(job_entry)

        # Write immediately to prevent data loss
        self._write_report()

    def finalize(self) -> dict[str, Any]:
        """
        Finalize the report after all jobs complete.

        Calculates summary statistics and marks the report as complete.

        Returns:
            Complete summary dictionary including stepping info
        """
        if not self.report_data:
            return {}

        # Calculate summary from jobs
        successful = 0
        warnings = 0
        failed = 0
        total_issues = 0
        stepping_jobs = []
        stepping_disabled_jobs = []
        sync_stability_jobs = []

        for job in self.report_data.get("jobs", []):
            status = job.get("status", "Unknown")
            issues = job.get("audit_results", {}).get("total_issues", 0)

            if status == "Failed":
                failed += 1
            elif issues > 0:
                warnings += 1
            else:
                successful += 1

            total_issues += issues

            # Track stepping jobs
            stepping = job.get("stepping", {})
            if stepping.get("applied_to"):
                stepping_jobs.append(
                    {
                        "name": job.get("name", "Unknown"),
                        "sources": stepping.get("applied_to", []),
                    }
                )

            if stepping.get("detected_disabled"):
                stepping_disabled_jobs.append(
                    {
                        "name": job.get("name", "Unknown"),
                        "sources": stepping.get("detected_disabled", []),
                    }
                )

            # Track sync stability issues
            sync_stability = job.get("sync_stability", [])
            if sync_stability:
                affected_sources = [
                    s.get("source", "Unknown")
                    for s in sync_stability
                    if s.get("variance_detected")
                ]
                if affected_sources:
                    sync_stability_jobs.append(
                        {
                            "name": job.get("name", "Unknown"),
                            "sources": affected_sources,
                        }
                    )

        self.report_data["summary"] = {
            "successful": successful,
            "warnings": warnings,
            "failed": failed,
            "total_issues": total_issues,
            "stepping_jobs": stepping_jobs,
            "stepping_disabled_jobs": stepping_disabled_jobs,
            "sync_stability_jobs": sync_stability_jobs,
        }

        self.report_data["finalized_at"] = datetime.now().isoformat()

        self._write_report()

        return self.report_data["summary"]

    def get_report_path(self) -> Path | None:
        """Get the path to the current report file."""
        return self.current_report_path

    @staticmethod
    def load(report_path: Path) -> dict[str, Any]:
        """
        Load an existing report from disk.

        Args:
            report_path: Path to the JSON report file

        Returns:
            The report data dictionary

        Raises:
            FileNotFoundError: If report file doesn't exist
            json.JSONDecodeError: If report file is corrupted
        """
        with open(report_path, encoding="utf-8") as f:
            return json.load(f)

    def _write_report(self) -> None:
        """
        Write report to disk using atomic write pattern.

        Writes to a temporary file first, then renames to final location.
        This prevents corruption if the write is interrupted.
        """
        if not self.current_report_path:
            return

        # Write to temp file in same directory (ensures same filesystem for rename)
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", prefix="report_", dir=self.logs_folder
        )

        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(
                    self.report_data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder
                )

            # Atomic rename
            shutil.move(temp_path, self.current_report_path)
        except Exception:
            # Clean up temp file if something went wrong
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        Sanitize a string for use in a filename.

        Removes or replaces characters that are invalid in filenames.
        """
        # Replace common problematic characters
        invalid_chars = '<>:"/\\|?*'
        result = name
        for char in invalid_chars:
            result = result.replace(char, "_")

        # Collapse multiple underscores and trim
        while "__" in result:
            result = result.replace("__", "_")

        result = result.strip("_. ")

        # Limit length
        if len(result) > 100:
            result = result[:100]

        return result or "unnamed"

    @staticmethod
    def get_job_status_summary(job: dict[str, Any]) -> str:
        """
        Get a human-readable status summary for a job.

        Args:
            job: A job entry from the report

        Returns:
            Status string like "Success", "Warning (3 issues)", "Failed"
        """
        status = job.get("status", "Unknown")

        if status == "Failed":
            return "Failed"

        issues = job.get("audit_results", {}).get("total_issues", 0)
        if issues > 0:
            return f"Warning ({issues} issue{'s' if issues != 1 else ''})"

        return "Success"

    @staticmethod
    def get_stepping_summary(job: dict[str, Any]) -> str:
        """
        Get a human-readable stepping summary for a job.

        Args:
            job: A job entry from the report

        Returns:
            Stepping status string
        """
        stepping = job.get("stepping", {})
        applied = stepping.get("applied_to", [])
        disabled = stepping.get("detected_disabled", [])
        separated = stepping.get("detected_separated", [])

        parts = []

        if applied:
            parts.append(f"Corrected: {', '.join(applied)}")

        if disabled:
            parts.append(f"Disabled: {', '.join(disabled)}")

        if separated:
            parts.append(f"Separated: {', '.join(separated)}")

        return "; ".join(parts) if parts else "-"

    @staticmethod
    def get_delays_summary(job: dict[str, Any]) -> str:
        """
        Get a human-readable delays summary for a job.

        Args:
            job: A job entry from the report

        Returns:
            Delays string like "S2: +150ms, S3: -200ms"
        """
        delays = job.get("delays", {})
        if not delays:
            return "-"

        parts = []
        for source, delay in sorted(delays.items()):
            # Shorten "Source 2" to "S2"
            short_name = source.replace("Source ", "S")
            sign = "+" if delay >= 0 else ""
            parts.append(f"{short_name}: {sign}{delay}ms")

        return ", ".join(parts)

    @staticmethod
    def get_sync_stability_summary(job: dict[str, Any]) -> str:
        """
        Get a human-readable sync stability summary for a job.

        Args:
            job: A job entry from the report

        Returns:
            Stability status string
        """
        stability_issues = job.get("sync_stability", [])
        if not stability_issues:
            return "-"

        issues_with_variance = [
            s for s in stability_issues if s.get("variance_detected")
        ]
        if not issues_with_variance:
            return "OK"

        parts = []
        for issue in issues_with_variance:
            source = issue.get("source", "Unknown").replace("Source ", "S")
            variance = issue.get("max_variance_ms", 0)
            parts.append(f"{source}: {variance:.3f}ms")

        return ", ".join(parts)
