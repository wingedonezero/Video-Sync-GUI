# vsg_core/models/results.py
"""
Result types for pipeline step validation and error reporting.
"""

from dataclasses import dataclass, field
from enum import Enum


class StepStatus(Enum):
    """Status codes for pipeline steps."""

    SUCCESS = "success"
    WARNING = "warning"  # Non-fatal issues that were handled
    FAILED = "failed"  # Fatal issues that should stop the job


@dataclass
class StepResult:
    """Result of a pipeline step execution."""

    status: StepStatus
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def is_fatal(self) -> bool:
        """Returns True if this result should stop the job."""
        return self.status == StepStatus.FAILED

    def has_issues(self) -> bool:
        """Returns True if there are any warnings or errors."""
        return self.status != StepStatus.SUCCESS or bool(self.warnings)

    def add_warning(self, message: str):
        """Add a warning message."""
        self.warnings.append(message)
        if self.status == StepStatus.SUCCESS:
            self.status = StepStatus.WARNING


@dataclass
class CorrectionResult:
    """Result of an audio correction operation."""

    success: bool
    error: str | None = None
    corrected_tracks: list[str] = field(default_factory=list)

    @classmethod
    def failed(cls, error: str) -> "CorrectionResult":
        """Create a failed result."""
        return cls(success=False, error=error)

    @classmethod
    def succeeded(cls, corrected_tracks: list[str]) -> "CorrectionResult":
        """Create a successful result."""
        return cls(success=True, corrected_tracks=corrected_tracks)
