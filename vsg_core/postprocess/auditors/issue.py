# vsg_core/postprocess/auditors/issue.py
"""
AuditIssue - structured representation of a single problem reported by an auditor.

These are collected per-job by FinalAuditor and surfaced in the batch report
so the user can see what went wrong without digging through the log file.
"""

from dataclasses import dataclass
from typing import Literal

SeverityStr = Literal["warning", "error"]


@dataclass(frozen=True, slots=True)
class AuditIssue:
    """A single problem found by an auditor during post-merge validation."""

    auditor: str  # Short name, e.g. "TrackFlags", "FrameLocked"
    severity: SeverityStr  # "warning" or "error"
    message: str  # Human-readable description (no [WARNING]/[ERROR] prefix)
