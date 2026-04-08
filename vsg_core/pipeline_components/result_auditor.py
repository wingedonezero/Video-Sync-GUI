# vsg_core/pipeline_components/result_auditor.py
"""
Result auditor component.

Wraps the FinalAuditor for post-merge validation. Returns both the issue
count (for the legacy tally) and the structured list of issues so the
pipeline can surface them in the batch report.
"""

from collections.abc import Callable
from pathlib import Path

from ..io.runner import CommandRunner
from ..orchestrator.steps.context import Context
from ..postprocess import FinalAuditor
from ..postprocess.auditors import AuditIssue


class ResultAuditor:
    """Audits merged output files for quality and correctness."""

    @staticmethod
    def audit_output(
        output_file: Path,
        context: Context,
        runner: CommandRunner,
        log_callback: Callable[[str], None],
    ) -> tuple[int, list[AuditIssue]]:
        """
        Audits the merged output file.

        Args:
            output_file: Path to the merged output file
            context: Context object from sync planning
            runner: CommandRunner for execution
            log_callback: Logging callback function

        Returns:
            Tuple of (issue count, structured issue list). On failure the
            count is 0 and the list is empty — the error is logged via
            ``log_callback``.
        """
        log_callback("--- Post-Merge: Running Final Audit ---")

        try:
            auditor = FinalAuditor(context, runner)
            return auditor.run(output_file)
        except Exception as audit_error:
            log_callback(f"[ERROR] Final audit step failed: {audit_error}")
            return 0, []
