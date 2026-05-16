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
    # DBSCAN noise points: (time_s, delay_ms) pairs for recovery
    noise_points: tuple[tuple[float, float], ...] = ()


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
    # Extended audit data from new pipeline (optional for backward compat)
    video_scene: SceneDetectResult | None = None
    overlap_start_s: float | None = None
    overlap_end_s: float | None = None
    overlap_dur_ms: float = 0.0
    track_validations: tuple[TrackValidation, ...] = ()
    # How much the correction overflows the selected silence zone.
    # 0 = zone large enough to fully absorb the correction. Positive
    # means the insert/trim will bleed that many ms into real audio
    # content on one side of the silence region.
    zone_overflow_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class FrameRefinementResult:
    """Outcome of the frame-precision pass for one splice point.

    ``mode`` is the only required-to-read field; the others carry
    diagnostics for the audit trail. When ``mode == "refined"``, the
    enclosing ``SplicePoint.src2_time_s`` has been rewritten to
    ``video_src2_time_s`` (the exact first-AFTER frame) and the original
    audio-derived position is preserved in ``audio_src2_time_s`` for
    transparency.
    """

    mode: str  # "refined" | "skipped_disabled" | "skipped_gate"
    # | "skipped_no_video" | "skipped_low_confidence" | "skipped_jump_mismatch"
    # | "fallback_outside_silence" | "fallback_no_first_after"
    reason: str = ""  # short human-readable explanation

    # Anchor measurements (raw, before / after windows)
    before_anchor_offset_frames: int | None = None
    after_anchor_offset_frames: int | None = None
    before_anchor_score: float = 0.0
    after_anchor_score: float = 0.0

    # Jump confirmation against audio's expected per-segment delay change
    audio_expected_jump_frames: int | None = None
    measured_jump_frames: int | None = None
    jump_confirmed: bool = False

    # Seam location (in src2 frame indices, absolute)
    last_before_frame: int | None = None
    first_after_frame: int | None = None

    # The two splice-point candidates and which one we used
    audio_src2_time_s: float = 0.0  # original splice picked by boundary_refiner
    video_src2_time_s: float | None = None  # video-derived; None when skipped
    frame_drift_ms: float = 0.0  # video - audio (signed)

    # Configured gates for the run (echoed for audit clarity)
    target_fps: float | None = None


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
    # Optional frame-precision refinement result. ``None`` when the
    # refinement pass didn't run (older code paths, or stepping
    # correction outside the refinement gate).
    frame_refinement: FrameRefinementResult | None = None


# ---------------------------------------------------------------------------
# Video scene detection types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SceneCut:
    """A detected video scene cut from frame histogram comparison."""

    time_s: float  # Timestamp of the cut frame
    frame: int  # Frame number
    diff: float  # Histogram difference (0-1, higher = more different)
    mean: float  # Mean Y value of the frame
    cut_type: str  # "HARD_CUT" or "BLACK"


@dataclass(frozen=True, slots=True)
class BlackZone:
    """A detected black frame zone in video."""

    start_s: float
    end_s: float
    dur_ms: float


@dataclass(frozen=True, slots=True)
class SceneDetectResult:
    """Combined result from video scene detection."""

    cuts: list[SceneCut]
    black_zones: list[BlackZone]


# ---------------------------------------------------------------------------
# Track validation types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrackValidation:
    """Safety check result for a single audio track at an edit point."""

    track_name: str
    db: float  # RMS energy at the edit point
    is_speech: bool  # True if Silero VAD detected speech
    status: str  # "TRUE SILENCE", "SILENCE", "QUIET", "CROSSFADE", "SPEECH"
