# vsg_core/models/types.py
"""Literal type aliases for type-safe string values.

These replace enums to avoid JSON serialization issues while maintaining
type safety through Literal types. Type checkers (mypy, pyright) will
flag invalid string values.

Usage:
    from vsg_core.models.types import TrackTypeStr, AnalysisModeStr, SnapModeStr
"""

from typing import Literal

# Track types - used in Track dataclass for categorizing media tracks
TrackTypeStr = Literal["video", "audio", "subtitles"]

# Analysis mode - determines how source comparison is performed
AnalysisModeStr = Literal["Audio Correlation", "VideoDiff"]

# Snap mode - determines how chapter timestamps snap to keyframes
SnapModeStr = Literal["previous", "nearest"]

# =========================================================================
# Sync & Subtitle Settings
# =========================================================================

# How subtitle sync delay is calculated
SubtitleSyncModeStr = Literal[
    "time-based",
    "video-verified",
]

# Final rounding for all sync modes
SubtitleRoundingStr = Literal["floor", "round", "ceil"]

# Sync timing direction
SyncModeStr = Literal["positive_only", "allow_negative"]

# =========================================================================
# Frame Matching Settings
# =========================================================================

# Hash algorithm for frame comparison
FrameHashAlgorithmStr = Literal["dhash", "phash", "average_hash", "whash"]

# Frame comparison method
FrameComparisonMethodStr = Literal["hash", "ssim", "mse"]

# Video-verified matching method
VideoVerifiedMethodStr = Literal["classic", "neural"]

# =========================================================================
# Audio Analysis Settings
# =========================================================================

# Source separation mode
SourceSeparationModeStr = Literal["none", "instrumental", "vocals"]

# Source separation device
SourceSeparationDeviceStr = Literal["auto", "cpu", "cuda", "rocm", "mps"]

# Audio filtering method
FilteringMethodStr = Literal["None", "Low-Pass Filter", "Dialogue Band-Pass Filter"]

# Correlation algorithm
CorrelationMethodStr = Literal[
    "Standard Correlation (SCC)",
    "Phase Correlation (GCC-PHAT)",
    "Onset Detection",
    "GCC-SCOT",
    "Whitened Cross-Correlation",
    "Spectrogram Correlation",
    "VideoDiff",
]

# Correlation algorithm for source-separated audio (no VideoDiff)
CorrelationMethodSourceSepStr = Literal[
    "Standard Correlation (SCC)",
    "Phase Correlation (GCC-PHAT)",
    "Onset Detection",
    "GCC-SCOT",
    "Whitened Cross-Correlation",
    "Spectrogram Correlation",
]

# Delay selection strategy
DelaySelectionModeStr = Literal[
    "Mode (Most Common)",
    "Mode (Clustered)",
    "Mode (Early Cluster)",
    "First Stable",
    "Average",
]

# =========================================================================
# Stepping Correction Settings
# =========================================================================

# Stepping correction mode
SteppingCorrectionModeStr = Literal["full", "filtered", "strict", "disabled"]

# Stepping quality mode
SteppingQualityModeStr = Literal["strict", "normal", "lenient", "custom"]

# Filtered stepping fallback
SteppingFilteredFallbackStr = Literal[
    "nearest", "interpolate", "uniform", "skip", "reject"
]

# How to handle subs spanning stepping boundaries
SteppingBoundaryModeStr = Literal["start", "majority", "midpoint"]

# =========================================================================
# Resampling Settings
# =========================================================================

# Resampling engine
ResampleEngineStr = Literal["aresample", "atempo", "rubberband"]

# Rubberband transient handling
RubberbandTransientsStr = Literal["crisp", "mixed", "smooth"]

# =========================================================================
# Sync Stability Settings
# =========================================================================

# Outlier detection mode for sync stability
SyncStabilityOutlierModeStr = Literal["any", "threshold"]

# =========================================================================
# OCR Settings
# =========================================================================

# OCR engine
OcrEngineStr = Literal[
    "easyocr", "paddleocr", "lfm2vl-450m", "qwen35-4b", "paddleocr-vl"
]

# OCR output format
OcrOutputFormatStr = Literal["ass", "srt"]

# OCR binarization method
OcrBinarizationMethodStr = Literal["otsu"]
