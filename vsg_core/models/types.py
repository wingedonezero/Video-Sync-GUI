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
    "timebase-frame-locked-timestamps",
    "duration-align",
    "correlation-frame-snap",
    "subtitle-anchored-frame-snap",
    "correlation-guided-frame-anchor",
    "video-verified",
]

# Final rounding for all sync modes
SubtitleRoundingStr = Literal["floor", "round", "ceil"]

# Frame snap mode for VideoTimestamps (timebase-frame-locked)
VideoTimestampsSnapModeStr = Literal["start", "exact"]

# Rounding mode for VideoTimestamps frame boundaries
VideoTimestampsRoundingStr = Literal["floor", "round", "ceil"]

# Sync timing direction
SyncModeStr = Literal["positive_only", "allow_negative"]

# =========================================================================
# Frame Matching Settings
# =========================================================================

# Hash algorithm for frame comparison
FrameHashAlgorithmStr = Literal["dhash", "phash", "average_hash", "whash"]

# Frame comparison method
FrameComparisonMethodStr = Literal["hash", "ssim", "mse"]

# =========================================================================
# Fallback Modes (what to do when sync mode fails)
# =========================================================================

# Duration-align fallback
DurationAlignFallbackStr = Literal["none", "abort", "duration-offset"]

# Correlation-frame-snap fallback
CorrelationSnapFallbackStr = Literal["snap-to-frame", "use-raw", "abort"]

# Subtitle-anchored-frame-snap fallback
SubAnchorFallbackStr = Literal["abort", "use-median"]

# Correlation-guided-frame-anchor fallback
CorrAnchorFallbackStr = Literal["use-correlation", "use-median", "abort"]

# =========================================================================
# Interlaced / Telecine Settings
# =========================================================================

# Content detection mode for interlaced handling
InterlacedForceModeStr = Literal["auto", "interlaced", "telecine", "progressive"]

# Analyzed video content type (from idet analysis)
ContentTypeStr = Literal[
    "progressive",  # True progressive, no duplicates
    "interlaced",  # Pure interlaced (TFF or BFF)
    "telecine",  # Legacy: detected from metadata only
    "telecine_hard",  # Interlaced with pulldown (needs VFM + VDecimate)
    "telecine_soft",  # Progressive with pulldown/duplicates (needs VDecimate only)
    "mixed",  # Mix of interlaced and progressive sections
    "unknown",  # Could not determine
]

# Video field order (from analysis)
FieldOrderStr = Literal["progressive", "tff", "bff"]

# Hash algorithm for interlaced content (includes ahash, not in progressive)
InterlacedHashAlgorithmStr = Literal["ahash", "phash", "dhash", "whash"]

# Deinterlace method for frame extraction
DeinterlaceMethodStr = Literal["bwdif", "yadif", "yadifmod", "bob", "w3fdif"]

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
    "DTW (Dynamic Time Warping)",
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
    "DTW (Dynamic Time Warping)",
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

# How to fill delay gaps in stepping correction
SteppingFillModeStr = Literal["silence", "auto", "content"]

# How to handle subs spanning stepping boundaries
SteppingBoundaryModeStr = Literal["start", "majority", "midpoint"]

# Silence detection method for stepping
SilenceDetectionMethodStr = Literal["smart_fusion", "ffmpeg_silencedetect", "rms_basic"]

# Video-aware boundary snapping mode
VideoSnapModeStr = Literal["scenes", "keyframes", "any_frame"]

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
OcrEngineStr = Literal["tesseract", "easyocr", "paddleocr"]

# OCR output format
OcrOutputFormatStr = Literal["ass", "srt"]

# OCR binarization method
OcrBinarizationMethodStr = Literal["otsu"]
