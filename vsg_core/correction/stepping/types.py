# vsg_core/correction/stepping/types.py
"""Stepping correction dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...analysis.types import ChunkResult, ClusterDiagnostic


# ---------------------------------------------------------------------------
# Core EDL type (kept mutable for drift_rate_ms_s update)
# ---------------------------------------------------------------------------


@dataclass(slots=True, unsafe_hash=True)
class AudioSegment:
    """Represents an action point on the target timeline for assembly."""

    start_s: float
    end_s: float
    delay_ms: int
    delay_raw: float = 0.0  # Raw float delay for subtitle precision
    drift_rate_ms_s: float = 0.0


# ---------------------------------------------------------------------------
# Dense analysis data loaded from temp folder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SteppingData:
    """Dense analysis data loaded from temp folder JSON."""

    source_key: str
    track_id: int
    windows: list[ChunkResult]
    clusters: list[ClusterDiagnostic]


# ---------------------------------------------------------------------------
# Transition / splice types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransitionZone:
    """Region where delay changes — needs boundary refinement."""

    ref_start_s: float  # End of cluster A's last window
    ref_end_s: float  # Start of cluster B's first window
    delay_before_ms: float
    delay_after_ms: float
    correction_ms: float  # delay_after - delay_before


@dataclass(frozen=True, slots=True)
class SilenceZone:
    """A detected silent region in audio."""

    start_s: float
    end_s: float
    center_s: float
    avg_db: float
    duration_ms: float
    source: str  # "rms", "vad", "combined"


@dataclass(frozen=True, slots=True)
class BoundaryResult:
    """Rich result from silence zone selection for audit trail."""

    zone: SilenceZone | None  # Best zone, or None if nothing found
    score: float  # Composite score from _pick_best_zone (0 if no zone)
    near_transient: bool  # True if transients detected near the chosen zone
    overlaps_speech: bool  # True if zone is RMS-only (VAD detected speech there)


@dataclass(frozen=True, slots=True)
class SplicePoint:
    """Precise splice location for a single transition."""

    ref_time_s: float  # Position in reference (Source 1) timeline
    src2_time_s: float  # Position in target (Source 2) timeline
    delay_before_ms: float
    delay_after_ms: float
    correction_ms: float  # delay_after - delay_before
    silence_zone: SilenceZone | None  # Best silence zone for splice
    boundary_result: BoundaryResult | None = None  # Rich audit data
    snap_metadata: dict[str, object] = field(default_factory=dict)
