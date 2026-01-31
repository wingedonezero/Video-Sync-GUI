# vsg_core/pipeline_components/result_auditor.py
"""
Result auditor component.

Wraps the FinalAuditor for post-merge validation.
"""

from collections.abc import Callable
from pathlib import Path

from ..io.runner import CommandRunner
from ..postprocess import FinalAuditor


class ResultAuditor:
    """Audits merged output files for quality and correctness."""

    @staticmethod
    def audit_output(
        output_file: Path,
        context: object,
        runner: CommandRunner,
        log_callback: Callable[[str], None]
    ) -> int:
        """
        Audits the merged output file.

        Args:
            output_file: Path to the merged output file
            context: Context object from sync planning
            runner: CommandRunner for execution
            log_callback: Logging callback function

        Returns:
            Number of issues found (0 = no issues)
        """
        log_callback("--- Post-Merge: Running Final Audit ---")
        issues = 0

        try:
            auditor = FinalAuditor(context, runner)
            issues = auditor.run(output_file)
        except Exception as audit_error:
            log_callback(f"[ERROR] Final audit step failed: {audit_error}")

        return issues
