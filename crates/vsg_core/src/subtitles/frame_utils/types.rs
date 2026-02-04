//! Types for frame utilities.
//!
//! Contains all enums and structs used by the frame_utils module.

use std::path::PathBuf;

/// Video properties detected from a file.
#[derive(Debug, Clone)]
pub struct VideoProperties {
    /// Frames per second.
    pub fps: f64,
    /// FPS as fraction (numerator, denominator) e.g. (24000, 1001).
    pub fps_fraction: (u32, u32),
    /// Duration in milliseconds.
    pub duration_ms: f64,
    /// Estimated frame count.
    pub frame_count: u32,
    /// Video width in pixels.
    pub width: u32,
    /// Video height in pixels.
    pub height: u32,
    /// Whether the video is interlaced.
    pub interlaced: bool,
    /// Field order for interlaced content.
    pub field_order: FieldOrder,
    /// Content type classification.
    pub content_type: ContentType,
    /// Whether this is SD content (height <= 576).
    pub is_sd: bool,
    /// Whether this appears to be DVD content.
    pub is_dvd: bool,
    /// How properties were detected.
    pub detection_source: String,
}

impl Default for VideoProperties {
    fn default() -> Self {
        Self {
            fps: 23.976,
            fps_fraction: (24000, 1001),
            duration_ms: 0.0,
            frame_count: 0,
            width: 1920,
            height: 1080,
            interlaced: false,
            field_order: FieldOrder::Progressive,
            content_type: ContentType::Progressive,
            is_sd: false,
            is_dvd: false,
            detection_source: "default".to_string(),
        }
    }
}

impl VideoProperties {
    /// Get frame duration in milliseconds.
    pub fn frame_duration_ms(&self) -> f64 {
        1000.0 / self.fps
    }
}

/// Field order for interlaced content.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FieldOrder {
    /// Progressive (non-interlaced).
    #[default]
    Progressive,
    /// Top Field First.
    TopFieldFirst,
    /// Bottom Field First.
    BottomFieldFirst,
    /// Unknown field order.
    Unknown,
}

impl FieldOrder {
    /// Parse from ffprobe field_order string.
    pub fn from_ffprobe(s: &str) -> Self {
        match s {
            "tt" | "tb" => Self::TopFieldFirst,
            "bb" | "bt" => Self::BottomFieldFirst,
            "progressive" => Self::Progressive,
            _ => Self::Unknown,
        }
    }

    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Progressive => "progressive",
            Self::TopFieldFirst => "tff",
            Self::BottomFieldFirst => "bff",
            Self::Unknown => "unknown",
        }
    }

    /// Whether this is TFF (for deinterlacing).
    pub fn is_tff(&self) -> bool {
        matches!(self, Self::TopFieldFirst)
    }
}

/// Content type classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ContentType {
    /// Progressive content.
    #[default]
    Progressive,
    /// Interlaced content.
    Interlaced,
    /// Telecine (24fps film to 29.97fps video).
    Telecine,
    /// Unknown content type.
    Unknown,
}

impl ContentType {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Progressive => "progressive",
            Self::Interlaced => "interlaced",
            Self::Telecine => "telecine",
            Self::Unknown => "unknown",
        }
    }
}

/// Hash algorithm for frame comparison.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum HashAlgorithm {
    /// Perceptual hash (DCT-based) - best for different encodes.
    #[default]
    PHash,
    /// Difference hash - fast, good for same encode.
    DHash,
    /// Average hash - simplest, fastest.
    AHash,
    /// Block hash - good for partial image matching.
    BlockHash,
}

impl HashAlgorithm {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::PHash => "phash",
            Self::DHash => "dhash",
            Self::AHash => "ahash",
            Self::BlockHash => "blockhash",
        }
    }

    /// Parse from string.
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "phash" => Some(Self::PHash),
            "dhash" => Some(Self::DHash),
            "ahash" | "average_hash" => Some(Self::AHash),
            "blockhash" => Some(Self::BlockHash),
            _ => None,
        }
    }
}

/// Comparison method for frames.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ComparisonMethod {
    /// Perceptual hash + hamming distance.
    #[default]
    Hash,
    /// Structural Similarity Index.
    Ssim,
    /// Mean Squared Error.
    Mse,
}

impl ComparisonMethod {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Hash => "hash",
            Self::Ssim => "ssim",
            Self::Mse => "mse",
        }
    }

    /// Parse from string.
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "hash" => Some(Self::Hash),
            "ssim" => Some(Self::Ssim),
            "mse" => Some(Self::Mse),
            _ => None,
        }
    }
}

/// Deinterlace method for interlaced content.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum DeinterlaceMethod {
    /// Auto-detect whether to deinterlace.
    #[default]
    Auto,
    /// No deinterlacing (raw frames).
    None,
    /// YADIF - good quality, moderate speed.
    Yadif,
    /// YADIFmod - better edge handling.
    YadifMod,
    /// Bob - fast, doubles framerate.
    Bob,
    /// BWDIF - motion adaptive, best quality.
    Bwdif,
}

impl DeinterlaceMethod {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::None => "none",
            Self::Yadif => "yadif",
            Self::YadifMod => "yadifmod",
            Self::Bob => "bob",
            Self::Bwdif => "bwdif",
        }
    }

    /// Parse from string.
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "auto" => Some(Self::Auto),
            "none" => Some(Self::None),
            "yadif" => Some(Self::Yadif),
            "yadifmod" => Some(Self::YadifMod),
            "bob" => Some(Self::Bob),
            "bwdif" => Some(Self::Bwdif),
            _ => None,
        }
    }
}

/// Video indexer backend selection.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum IndexerBackend {
    /// FFMS2 - fast index, widely used.
    #[default]
    Ffms2,
    /// BestSource - slower first load, more accurate.
    BestSource,
    /// L-SMASH - alternative backend.
    LSmash,
}

impl IndexerBackend {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Ffms2 => "ffms2",
            Self::BestSource => "bestsource",
            Self::LSmash => "lsmash",
        }
    }

    /// Parse from string.
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "ffms2" => Some(Self::Ffms2),
            "bestsource" => Some(Self::BestSource),
            "lsmash" | "l-smash" => Some(Self::LSmash),
            _ => None,
        }
    }
}

/// Force mode for interlaced handling.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum InterlacedForceMode {
    /// Auto-detect interlacing.
    #[default]
    Auto,
    /// Force progressive handling.
    Progressive,
    /// Force interlaced handling.
    Interlaced,
    /// Force telecine handling.
    Telecine,
}

impl InterlacedForceMode {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Progressive => "progressive",
            Self::Interlaced => "interlaced",
            Self::Telecine => "telecine",
        }
    }
}

/// Configuration for VideoReader.
#[derive(Debug, Clone, Default)]
pub struct VideoReaderConfig {
    /// Deinterlace method to use.
    pub deinterlace: DeinterlaceMethod,
    /// Indexer backend to use.
    pub indexer_backend: IndexerBackend,
    /// Temporary directory for index cache.
    pub temp_dir: Option<PathBuf>,
}

/// Result of comparing two frames.
#[derive(Debug, Clone)]
pub struct FrameCompareResult {
    /// Distance/similarity metric (lower = more similar, 0 = identical).
    pub distance: f64,
    /// Whether frames are considered matching (below threshold).
    pub is_match: bool,
    /// Method used for comparison.
    pub method: ComparisonMethod,
}

/// Result of verifying a frame sequence.
#[derive(Debug, Clone)]
pub struct SequenceVerifyResult {
    /// Number of frames that matched.
    pub matched_count: usize,
    /// Total frames tested.
    pub total_count: usize,
    /// Average distance across sequence.
    pub avg_distance: f64,
    /// Whether sequence is verified (matched_count >= 70% of total).
    pub verified: bool,
}

impl SequenceVerifyResult {
    /// Check if sequence passes verification threshold.
    pub fn passes_threshold(&self, threshold_pct: f64) -> bool {
        if self.total_count == 0 {
            return false;
        }
        let ratio = self.matched_count as f64 / self.total_count as f64;
        ratio >= threshold_pct
    }
}

/// Result of testing a candidate offset at checkpoints.
#[derive(Debug, Clone)]
pub struct CandidateResult {
    /// Frame offset being tested.
    pub frame_offset: i32,
    /// Approximate offset in milliseconds.
    pub approx_ms: f64,
    /// Overall quality score.
    pub score: f64,
    /// Number of checkpoints that matched.
    pub matched_checkpoints: usize,
    /// Number of checkpoints with verified sequences.
    pub sequence_verified: usize,
    /// Average distance across all checkpoints.
    pub avg_distance: f64,
    /// Detailed match results for each checkpoint.
    pub match_details: Vec<CheckpointMatch>,
}

/// Details for a single checkpoint match test.
#[derive(Debug, Clone)]
pub struct CheckpointMatch {
    /// Source frame index tested.
    pub source_frame: u32,
    /// Target frame index tested (source + offset).
    pub target_frame: u32,
    /// Distance between frames.
    pub distance: f64,
    /// Whether initial frame matched.
    pub is_match: bool,
    /// Frames matched in sequence verification.
    pub sequence_matched: usize,
    /// Total frames in sequence.
    pub sequence_length: usize,
    /// Whether sequence was verified.
    pub sequence_verified: bool,
    /// Average distance in sequence.
    pub sequence_avg_dist: f64,
}

/// Settings for video-verified sync mode.
#[derive(Debug, Clone)]
pub struct VideoVerifiedSettings {
    // General settings
    /// Number of checkpoints to test across the video.
    pub num_checkpoints: usize,
    /// Search range in frames around correlation value.
    pub search_range_frames: i32,
    /// Number of consecutive frames to verify.
    pub sequence_length: usize,
    /// Whether to use PTS for sub-frame precision.
    pub use_pts_precision: bool,
    /// Whether to run frame alignment audit.
    pub frame_audit_enabled: bool,

    // Hash settings
    /// Hash algorithm to use.
    pub hash_algorithm: HashAlgorithm,
    /// Hash size (8 or 16).
    pub hash_size: u8,
    /// Maximum hash distance for a match.
    pub hash_threshold: u32,
    /// Window radius for initial frame search.
    pub window_radius: i32,
    /// Comparison method.
    pub comparison_method: ComparisonMethod,

    // Interlaced handling
    /// Whether interlaced handling is enabled.
    pub interlaced_handling_enabled: bool,
    /// Force mode for interlaced detection.
    pub interlaced_force_mode: InterlacedForceMode,
    /// Deinterlace method for interlaced content.
    pub interlaced_deinterlace_method: DeinterlaceMethod,
    /// Number of checkpoints for interlaced content.
    pub interlaced_num_checkpoints: usize,
    /// Search range for interlaced content.
    pub interlaced_search_range_frames: i32,
    /// Hash algorithm for interlaced content.
    pub interlaced_hash_algorithm: HashAlgorithm,
    /// Hash size for interlaced content.
    pub interlaced_hash_size: u8,
    /// Hash threshold for interlaced content.
    pub interlaced_hash_threshold: u32,
    /// Comparison method for interlaced content.
    pub interlaced_comparison_method: ComparisonMethod,
    /// Sequence length for interlaced content.
    pub interlaced_sequence_length: usize,
    /// Whether to fall back to audio if frame matching fails.
    pub interlaced_fallback_to_audio: bool,
}

impl Default for VideoVerifiedSettings {
    fn default() -> Self {
        Self {
            // General settings
            num_checkpoints: 5,
            search_range_frames: 3,
            sequence_length: 10,
            use_pts_precision: false,
            frame_audit_enabled: false,

            // Hash settings
            hash_algorithm: HashAlgorithm::PHash,
            hash_size: 16,
            hash_threshold: 12,
            window_radius: 1,
            comparison_method: ComparisonMethod::Hash,

            // Interlaced handling - same defaults, can be customized
            interlaced_handling_enabled: true,
            interlaced_force_mode: InterlacedForceMode::Auto,
            interlaced_deinterlace_method: DeinterlaceMethod::Bwdif,
            interlaced_num_checkpoints: 5,
            interlaced_search_range_frames: 3,
            interlaced_hash_algorithm: HashAlgorithm::PHash,
            interlaced_hash_size: 16,
            interlaced_hash_threshold: 15, // Slightly higher for interlaced
            interlaced_comparison_method: ComparisonMethod::Hash,
            interlaced_sequence_length: 10,
            interlaced_fallback_to_audio: true,
        }
    }
}

impl VideoVerifiedSettings {
    /// Get the effective settings based on content type.
    ///
    /// Returns interlaced settings if content is interlaced and handling is enabled.
    pub fn effective_num_checkpoints(&self, is_interlaced: bool) -> usize {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_num_checkpoints
        } else {
            self.num_checkpoints
        }
    }

    /// Get effective search range.
    pub fn effective_search_range(&self, is_interlaced: bool) -> i32 {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_search_range_frames
        } else {
            self.search_range_frames
        }
    }

    /// Get effective hash algorithm.
    pub fn effective_hash_algorithm(&self, is_interlaced: bool) -> HashAlgorithm {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_hash_algorithm
        } else {
            self.hash_algorithm
        }
    }

    /// Get effective hash size.
    pub fn effective_hash_size(&self, is_interlaced: bool) -> u8 {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_hash_size
        } else {
            self.hash_size
        }
    }

    /// Get effective hash threshold.
    pub fn effective_hash_threshold(&self, is_interlaced: bool) -> u32 {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_hash_threshold
        } else {
            self.hash_threshold
        }
    }

    /// Get effective comparison method.
    pub fn effective_comparison_method(&self, is_interlaced: bool) -> ComparisonMethod {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_comparison_method
        } else {
            self.comparison_method
        }
    }

    /// Get effective sequence length.
    pub fn effective_sequence_length(&self, is_interlaced: bool) -> usize {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_sequence_length
        } else {
            self.sequence_length
        }
    }
}

/// Result of comparing video properties between source and target.
#[derive(Debug, Clone)]
pub struct VideoCompareResult {
    /// Recommended sync strategy.
    pub strategy: SyncStrategy,
    /// Whether FPS matches between videos.
    pub fps_match: bool,
    /// Ratio of source FPS to target FPS.
    pub fps_ratio: f64,
    /// Whether there's an interlacing mismatch.
    pub interlace_mismatch: bool,
    /// Whether deinterlacing is needed.
    pub needs_deinterlace: bool,
    /// Whether scaling is needed (PAL speedup, etc.).
    pub needs_scaling: bool,
    /// Scale factor if scaling needed.
    pub scale_factor: f64,
    /// Warning messages.
    pub warnings: Vec<String>,
}

/// Recommended sync strategy based on video comparison.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SyncStrategy {
    /// Frame-based matching should work well.
    #[default]
    FrameBased,
    /// Use timestamp-based matching (FPS mismatch).
    TimestampBased,
    /// Deinterlacing required for frame matching.
    Deinterlace,
    /// Scaling required (PAL speedup detected).
    Scale,
}

impl SyncStrategy {
    /// Get display name.
    pub fn name(&self) -> &'static str {
        match self {
            Self::FrameBased => "frame-based",
            Self::TimestampBased => "timestamp-based",
            Self::Deinterlace => "deinterlace",
            Self::Scale => "scale",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_field_order_parsing() {
        assert_eq!(FieldOrder::from_ffprobe("tt"), FieldOrder::TopFieldFirst);
        assert_eq!(FieldOrder::from_ffprobe("tb"), FieldOrder::TopFieldFirst);
        assert_eq!(FieldOrder::from_ffprobe("bb"), FieldOrder::BottomFieldFirst);
        assert_eq!(FieldOrder::from_ffprobe("progressive"), FieldOrder::Progressive);
        assert_eq!(FieldOrder::from_ffprobe("unknown"), FieldOrder::Unknown);
    }

    #[test]
    fn test_hash_algorithm_parsing() {
        assert_eq!(HashAlgorithm::from_str("phash"), Some(HashAlgorithm::PHash));
        assert_eq!(HashAlgorithm::from_str("DHASH"), Some(HashAlgorithm::DHash));
        assert_eq!(HashAlgorithm::from_str("invalid"), None);
    }

    #[test]
    fn test_video_properties_default() {
        let props = VideoProperties::default();
        assert!((props.fps - 23.976).abs() < 0.001);
        assert_eq!(props.fps_fraction, (24000, 1001));
        assert!(!props.interlaced);
    }

    #[test]
    fn test_sequence_verify_threshold() {
        let result = SequenceVerifyResult {
            matched_count: 7,
            total_count: 10,
            avg_distance: 5.0,
            verified: true,
        };
        assert!(result.passes_threshold(0.7));
        assert!(!result.passes_threshold(0.8));
    }

    #[test]
    fn test_video_verified_settings_effective() {
        let settings = VideoVerifiedSettings::default();

        // Progressive content uses normal settings
        assert_eq!(settings.effective_num_checkpoints(false), 5);
        assert_eq!(settings.effective_hash_threshold(false), 12);

        // Interlaced content uses interlaced settings
        assert_eq!(settings.effective_hash_threshold(true), 15);
    }
}
