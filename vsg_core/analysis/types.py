# vsg_core/analysis/types.py
"""
Analysis-specific result types.

These dataclasses represent the output of analysis module functions.
They are local to the analysis module (not shared across the codebase).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field


@dataclass(frozen=True, slots=True)
class ChunkResult:
    """Result from correlating one audio chunk pair."""

    delay_ms: int  # Rounded delay in milliseconds
    raw_delay_ms: float  # Precise float delay in milliseconds
    match_pct: float  # Match quality / confidence score (0-100)
    start_s: float  # Chunk start position in seconds
    accepted: bool  # True if match_pct >= threshold


@dataclass(frozen=True, slots=True)
class TrackSelection:
    """Result of audio track selection for correlation analysis."""

    track_id: int  # mkvmerge track ID
    track_index: int  # 0-based index within audio tracks
    selected_by: str  # "language", "explicit", "first"
    language: str  # Language code (e.g., "jpn", "eng")
    codec: str  # Codec name (e.g., "FLAC", "AAC")
    channels: int  # Number of audio channels
    formatted_name: str  # Human-readable description for logging


@dataclass(frozen=True, slots=True)
class DelayCalculation:
    """Result of delay calculation from correlation results."""

    rounded_ms: int  # Rounded delay for mkvmerge (integer milliseconds)
    raw_ms: float  # Unrounded delay for subtitle precision (float milliseconds)
    selection_method: str  # "mode", "average", "first stable", etc.
    accepted_chunks: int  # Number of chunks that passed quality threshold
    total_chunks: int  # Total number of chunks analyzed


@dataclass(frozen=True, slots=True)
class ContainerDelayInfo:
    """Container delay information for a source."""

    video_delay_ms: float  # Video track container delay
    audio_delays_ms: dict[int, float]  # Audio track ID -> relative delay
    selected_audio_delay_ms: float  # Delay for the audio track used in correlation


@dataclass(frozen=True, slots=True)
class GlobalShiftCalculation:
    """Result of global shift calculation to eliminate negative delays."""

    shift_ms: int  # Rounded global shift applied to all tracks
    raw_shift_ms: float  # Unrounded global shift for subtitle precision
    most_negative_ms: int  # Most negative delay before shift (rounded)
    most_negative_raw_ms: float  # Most negative delay before shift (raw)
    applied: bool  # Whether shift was actually applied (based on sync mode)


# =========================================================================
# Drift / Stepping Diagnosis Results (from diagnose_audio_issue)
# =========================================================================


@dataclass(frozen=True, slots=True)
class UniformDiagnosis:
    """No drift or stepping detected — uniform delay across all chunks."""

    diagnosis: str = "UNIFORM"


@dataclass(frozen=True, slots=True)
class DriftDiagnosis:
    """Linear or PAL drift detected — delay increases linearly over time."""

    diagnosis: str  # "PAL_DRIFT" or "LINEAR_DRIFT"
    rate: float  # Drift rate in ms/s from regression slope


@dataclass(frozen=True, slots=True)
class SteppingDiagnosis:
    """Stepped delay clusters detected — delay jumps at discrete points."""

    diagnosis: str = "STEPPING"
    cluster_count: int = 0
    cluster_details: list[dict[str, object]] = dataclass_field(default_factory=list)
    valid_clusters: dict[int, list[int]] = dataclass_field(default_factory=dict)
    invalid_clusters: dict[int, list[int]] = dataclass_field(default_factory=dict)
    validation_results: dict[int, dict[str, object]] = dataclass_field(
        default_factory=dict
    )
    correction_mode: str = "full"
    fallback_mode: str | None = None


# Union of all possible diagnosis outcomes
DiagnosisResult = UniformDiagnosis | DriftDiagnosis | SteppingDiagnosis
