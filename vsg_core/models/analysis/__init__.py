# vsg_core/models/analysis/__init__.py
"""
Analysis result models for audio correlation and sync detection.

These dataclasses represent the typed results from correlation algorithms,
delay selection, drift detection, and sync stability analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class DiagnosisType(Enum):
    """Type of audio sync issue detected."""

    UNIFORM = auto()  # No drift/stepping - consistent delay
    PAL_DRIFT = auto()  # PAL speedup drift (~40.9 ms/s)
    LINEAR_DRIFT = auto()  # General linear drift
    STEPPING = auto()  # Multiple delay segments (edit points)


class DelaySelectionMode(Enum):
    """Available modes for selecting final delay from chunk results."""

    MODE_SIMPLE = "Mode (Most Common)"
    AVERAGE = "Average"
    MODE_CLUSTERED = "Mode (Clustered)"
    MODE_EARLY_CLUSTER = "Mode (Early Cluster)"
    FIRST_STABLE = "First Stable"


@dataclass
class ChunkResult:
    """Single chunk correlation result."""

    chunk_index: int
    start_time: float  # Start time in seconds
    delay_samples: int  # Delay in samples (rounded)
    delay_ms: int  # Delay in milliseconds (rounded)
    raw_delay_ms: float  # Unrounded delay for precision
    confidence: float  # Match confidence 0-100
    accepted: bool  # Whether chunk met acceptance threshold

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        return {
            "delay": self.delay_ms,
            "raw_delay": self.raw_delay_ms,
            "match": self.confidence,
            "start": self.start_time,
            "accepted": self.accepted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], chunk_index: int = 0) -> ChunkResult:
        """Create from dictionary for backward compatibility."""
        delay_ms = data.get("delay", 0)
        raw_delay = data.get("raw_delay", float(delay_ms))
        return cls(
            chunk_index=chunk_index,
            start_time=data.get("start", 0.0),
            delay_samples=0,  # Not stored in legacy format
            delay_ms=delay_ms,
            raw_delay_ms=raw_delay,
            confidence=data.get("match", 0.0),
            accepted=data.get("accepted", False),
        )


@dataclass
class ClusterInfo:
    """Information about a delay cluster (for stepping detection)."""

    cluster_id: int
    mean_delay_ms: float
    std_delay_ms: float
    chunk_count: int
    chunk_numbers: list[int]
    time_range: tuple[float, float]  # (start, end) in seconds
    mean_match_pct: float
    min_match_pct: float


@dataclass
class ClusterValidation:
    """Validation result for a single cluster."""

    valid: bool
    checks: dict[str, dict[str, Any]]  # Check name -> {passed, value, threshold, label}
    passed_count: int
    total_checks: int
    cluster_size: int
    cluster_percentage: float
    cluster_duration_s: float
    avg_match_quality: float
    min_match_quality: float
    time_range: tuple[float, float]


@dataclass
class DriftDiagnosis:
    """Result of drift/stepping detection analysis."""

    diagnosis_type: DiagnosisType
    drift_rate_ms_s: float | None = None  # For PAL/linear drift
    cluster_count: int | None = None  # For stepping
    cluster_details: list[ClusterInfo] = field(default_factory=list)
    valid_clusters: dict[int, list[int]] = field(default_factory=dict)
    invalid_clusters: dict[int, list[int]] = field(default_factory=dict)
    validation_results: dict[int, ClusterValidation] = field(default_factory=dict)
    correction_mode: str = "full"
    fallback_mode: str = "nearest"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        result: dict[str, Any] = {}
        if self.drift_rate_ms_s is not None:
            result["rate"] = self.drift_rate_ms_s
        if self.cluster_count is not None:
            result["clusters"] = self.cluster_count
        if self.cluster_details:
            result["cluster_details"] = [
                {
                    "cluster_id": c.cluster_id,
                    "mean_delay_ms": c.mean_delay_ms,
                    "std_delay_ms": c.std_delay_ms,
                    "chunk_count": c.chunk_count,
                    "chunk_numbers": c.chunk_numbers,
                    "time_range": c.time_range,
                    "mean_match_pct": c.mean_match_pct,
                    "min_match_pct": c.min_match_pct,
                }
                for c in self.cluster_details
            ]
        if self.valid_clusters:
            result["valid_clusters"] = self.valid_clusters
        if self.invalid_clusters:
            result["invalid_clusters"] = self.invalid_clusters
        if self.validation_results:
            result["validation_results"] = {
                k: {
                    "valid": v.valid,
                    "checks": v.checks,
                    "passed_count": v.passed_count,
                    "total_checks": v.total_checks,
                }
                for k, v in self.validation_results.items()
            }
        result["correction_mode"] = self.correction_mode
        result["fallback_mode"] = self.fallback_mode
        return result


@dataclass
class StabilityOutlier:
    """Information about an outlier chunk in stability analysis."""

    chunk_index: int
    time_s: float
    delay_ms: float
    deviation_ms: float
    cluster_id: int | None = None


@dataclass
class StabilityResult:
    """Result of sync stability analysis."""

    source: str
    variance_detected: bool
    max_variance_ms: float = 0.0
    std_dev_ms: float = 0.0
    mean_delay_ms: float = 0.0
    min_delay_ms: float = 0.0
    max_delay_ms: float = 0.0
    chunk_count: int = 0
    outlier_count: int = 0
    outliers: list[StabilityOutlier] = field(default_factory=list)
    cluster_count: int = 1
    is_stepping: bool = False
    cluster_issues: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        result = {
            "source": self.source,
            "variance_detected": self.variance_detected,
            "max_variance_ms": self.max_variance_ms,
            "chunk_count": self.chunk_count,
            "outlier_count": self.outlier_count,
            "cluster_count": self.cluster_count,
            "is_stepping": self.is_stepping,
        }
        if self.std_dev_ms:
            result["std_dev_ms"] = self.std_dev_ms
        if self.mean_delay_ms:
            result["mean_delay_ms"] = self.mean_delay_ms
        if self.min_delay_ms:
            result["min_delay_ms"] = self.min_delay_ms
        if self.max_delay_ms:
            result["max_delay_ms"] = self.max_delay_ms
        if self.outliers:
            result["outliers"] = [
                {
                    "chunk_index": o.chunk_index,
                    "time_s": o.time_s,
                    "delay_ms": o.delay_ms,
                    "deviation_ms": o.deviation_ms,
                }
                for o in self.outliers[:10]
            ]
        if self.cluster_issues:
            result["cluster_issues"] = self.cluster_issues
        if self.reason:
            result["reason"] = self.reason
        return result


@dataclass
class DelayResult:
    """Final delay selection result."""

    rounded_ms: int  # Rounded for mkvmerge compatibility
    raw_ms: float  # Unrounded for subtitle precision
    method: str  # Which selection method was used
    fallback_used: bool = False  # Whether a fallback method was used


@dataclass
class CorrelationResult:
    """Complete correlation analysis result for one source."""

    source_key: str
    chunks: list[ChunkResult]
    diagnosis: DriftDiagnosis | None
    stability: StabilityResult | None
    final_delay: DelayResult | None
    correlation_method: str
    accepted_count: int
    total_count: int

    @property
    def accepted_chunks(self) -> list[ChunkResult]:
        """Get only accepted chunks."""
        return [c for c in self.chunks if c.accepted]


__all__ = [
    # Enums
    "DiagnosisType",
    "DelaySelectionMode",
    # Core result types
    "ChunkResult",
    "ClusterInfo",
    "ClusterValidation",
    "DriftDiagnosis",
    "StabilityOutlier",
    "StabilityResult",
    "DelayResult",
    "CorrelationResult",
]
