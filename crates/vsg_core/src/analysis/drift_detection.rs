//! Drift detection for audio sync analysis.
//!
//! Analyzes chunk delay patterns to detect:
//! - PAL drift (NTSC→PAL speedup)
//! - Linear drift (sample rate mismatch, encoding issues)
//! - Stepping (multiple delay clusters from edits/reel changes)
//!
//! All functions are pure - no I/O, no side effects.

use serde::{Deserialize, Serialize};

use super::types::ChunkResult;

/// Type of drift detected in sync analysis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum DriftType {
    /// No drift - uniform delay across all chunks.
    #[default]
    Uniform,
    /// PAL speedup detected (NTSC 23.976fps → PAL 25fps).
    /// Expected drift rate: ~40.9 ms/s
    PalDrift,
    /// Linear drift detected (gradual accumulating offset).
    /// Could indicate sample rate mismatch or encoding issues.
    LinearDrift,
    /// Stepping detected (multiple distinct delay clusters).
    /// Indicates edits, reel changes, or content differences.
    Stepping,
}

impl std::fmt::Display for DriftType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DriftType::Uniform => write!(f, "Uniform"),
            DriftType::PalDrift => write!(f, "PAL Drift"),
            DriftType::LinearDrift => write!(f, "Linear Drift"),
            DriftType::Stepping => write!(f, "Stepping"),
        }
    }
}

/// Detailed drift diagnosis result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DriftDiagnosis {
    /// Type of drift detected.
    pub drift_type: DriftType,
    /// Human-readable description.
    pub description: String,
    /// Drift rate in ms/s (for PAL/Linear drift).
    pub drift_rate_ms_per_sec: Option<f64>,
    /// R² correlation coefficient (for linear drift).
    pub r_squared: Option<f64>,
    /// Number of clusters detected (for stepping).
    pub cluster_count: Option<usize>,
    /// Video framerate if provided.
    pub framerate: Option<f64>,
}

impl Default for DriftDiagnosis {
    fn default() -> Self {
        Self {
            drift_type: DriftType::Uniform,
            description: "No drift detected - delays are consistent".to_string(),
            drift_rate_ms_per_sec: None,
            r_squared: None,
            cluster_count: None,
            framerate: None,
        }
    }
}

impl DriftDiagnosis {
    /// Create a uniform (no drift) diagnosis.
    pub fn uniform() -> Self {
        Self::default()
    }

    /// Create a PAL drift diagnosis.
    pub fn pal_drift(drift_rate: f64, framerate: f64) -> Self {
        Self {
            drift_type: DriftType::PalDrift,
            description: format!(
                "PAL drift detected: {:.2} ms/s (framerate {:.2}fps, expected ~40.9 ms/s for NTSC→PAL)",
                drift_rate, framerate
            ),
            drift_rate_ms_per_sec: Some(drift_rate),
            r_squared: None,
            cluster_count: None,
            framerate: Some(framerate),
        }
    }

    /// Create a linear drift diagnosis.
    pub fn linear_drift(drift_rate: f64, r_squared: f64) -> Self {
        Self {
            drift_type: DriftType::LinearDrift,
            description: format!(
                "Linear drift detected: {:.2} ms/s (R²={:.3})",
                drift_rate, r_squared
            ),
            drift_rate_ms_per_sec: Some(drift_rate),
            r_squared: Some(r_squared),
            cluster_count: None,
            framerate: None,
        }
    }

    /// Create a stepping diagnosis.
    pub fn stepping(cluster_count: usize) -> Self {
        Self {
            drift_type: DriftType::Stepping,
            description: format!(
                "Stepping detected: {} distinct delay clusters (possible edits or reel changes)",
                cluster_count
            ),
            drift_rate_ms_per_sec: None,
            r_squared: None,
            cluster_count: Some(cluster_count),
            framerate: None,
        }
    }
}

/// Configuration for drift detection.
#[derive(Debug, Clone)]
pub struct DriftDetectionConfig {
    /// Minimum chunks required for drift analysis.
    pub min_chunks: usize,
    /// R² threshold for linear drift detection (lossy codecs).
    pub r2_threshold_lossy: f64,
    /// R² threshold for linear drift detection (lossless codecs).
    pub r2_threshold_lossless: f64,
    /// Slope threshold for linear drift (lossy codecs) in ms/s.
    pub slope_threshold_lossy: f64,
    /// Slope threshold for linear drift (lossless codecs) in ms/s.
    pub slope_threshold_lossless: f64,
    /// DBSCAN epsilon for clustering (ms).
    pub dbscan_epsilon_ms: f64,
    /// DBSCAN minimum samples per cluster.
    pub dbscan_min_samples: usize,
    /// Whether the codec is lossless (PCM, FLAC, TrueHD).
    pub is_lossless_codec: bool,
}

impl Default for DriftDetectionConfig {
    fn default() -> Self {
        Self {
            min_chunks: 6,
            r2_threshold_lossy: 0.7,
            r2_threshold_lossless: 0.9,
            slope_threshold_lossy: 0.5,
            slope_threshold_lossless: 0.1,
            dbscan_epsilon_ms: 50.0,
            dbscan_min_samples: 3,
            is_lossless_codec: false,
        }
    }
}

impl DriftDetectionConfig {
    /// Get the R² threshold based on codec type.
    pub fn r2_threshold(&self) -> f64 {
        if self.is_lossless_codec {
            self.r2_threshold_lossless
        } else {
            self.r2_threshold_lossy
        }
    }

    /// Get the slope threshold based on codec type.
    pub fn slope_threshold(&self) -> f64 {
        if self.is_lossless_codec {
            self.slope_threshold_lossless
        } else {
            self.slope_threshold_lossy
        }
    }

    /// Set codec type based on codec ID string.
    pub fn with_codec(mut self, codec_id: Option<&str>) -> Self {
        if let Some(codec) = codec_id {
            let codec_lower = codec.to_lowercase();
            self.is_lossless_codec = codec_lower.contains("pcm")
                || codec_lower.contains("flac")
                || codec_lower.contains("truehd")
                || codec_lower.contains("mlp");
        }
        self
    }
}

/// Diagnose drift from chunk correlation results.
///
/// Pure function - no I/O, no side effects.
///
/// Checks for drift types in order of specificity:
/// 1. PAL drift (requires framerate ≈25fps and slope ≈40.9 ms/s)
/// 2. Stepping (multiple delay clusters via DBSCAN)
/// 3. Linear drift (linear regression with good R² fit)
/// 4. Uniform (default - no drift detected)
///
/// # Arguments
/// * `chunks` - Chunk correlation results
/// * `config` - Drift detection configuration
/// * `framerate` - Optional video framerate for PAL detection
///
/// # Returns
/// Drift diagnosis with type and details.
pub fn diagnose_drift(
    chunks: &[ChunkResult],
    config: &DriftDetectionConfig,
    framerate: Option<f64>,
) -> DriftDiagnosis {
    // Get accepted chunks only
    let accepted: Vec<&ChunkResult> = chunks.iter().filter(|c| c.accepted).collect();

    // Need minimum chunks for drift analysis
    if accepted.len() < config.min_chunks {
        return DriftDiagnosis {
            description: format!(
                "Insufficient chunks for drift analysis ({} accepted, need {})",
                accepted.len(),
                config.min_chunks
            ),
            ..Default::default()
        };
    }

    // Extract times and delays
    let times: Vec<f64> = accepted.iter().map(|c| c.chunk_start_secs).collect();
    let delays: Vec<f64> = accepted.iter().map(|c| c.delay_ms_raw).collect();

    // Test 1: Check for PAL drift (specific linear drift)
    if let Some(fps) = framerate {
        if let Some(diagnosis) = check_pal_drift(&times, &delays, fps) {
            return diagnosis;
        }
    }

    // Test 2: Check for stepping (multiple clusters)
    if let Some(diagnosis) = check_stepping(&delays, config) {
        return diagnosis;
    }

    // Test 3: Check for linear drift
    if let Some(diagnosis) = check_linear_drift(&times, &delays, config) {
        return diagnosis;
    }

    // Default: uniform delay
    DriftDiagnosis::uniform()
}

/// Check for PAL drift (NTSC→PAL speedup).
///
/// PAL drift occurs when 23.976fps NTSC content is sped up to 25fps PAL.
/// This causes a drift rate of approximately 40.9 ms/s.
fn check_pal_drift(times: &[f64], delays: &[f64], framerate: f64) -> Option<DriftDiagnosis> {
    // PAL standard is 25fps (±0.1)
    let is_pal_framerate = (framerate - 25.0).abs() < 0.1;

    if !is_pal_framerate {
        return None;
    }

    // Calculate linear regression
    let (slope, _, _) = linear_regression(times, delays);

    // PAL speedup: 23.976fps → 25fps = ~40.9 ms/s drift
    // Formula: (25/23.976 - 1) * 1000 ≈ 40.9 ms/s
    // Allow ±5ms/s tolerance for encoding variations
    let expected_pal_drift = 40.9;
    let tolerance = 5.0;

    if (slope - expected_pal_drift).abs() < tolerance {
        return Some(DriftDiagnosis::pal_drift(slope, framerate));
    }

    None
}

/// Check for stepping (multiple delay clusters).
///
/// Uses DBSCAN-like clustering to detect distinct delay groups.
fn check_stepping(delays: &[f64], config: &DriftDetectionConfig) -> Option<DriftDiagnosis> {
    let labels = dbscan_cluster(delays, config.dbscan_epsilon_ms, config.dbscan_min_samples);

    // Count unique clusters (excluding noise labeled as -1)
    let unique_clusters: std::collections::HashSet<i32> =
        labels.iter().filter(|&&l| l >= 0).copied().collect();

    let cluster_count = unique_clusters.len();

    // Need at least 2 clusters for stepping
    if cluster_count > 1 {
        return Some(DriftDiagnosis::stepping(cluster_count));
    }

    None
}

/// Check for linear drift (gradual accumulating offset).
fn check_linear_drift(
    times: &[f64],
    delays: &[f64],
    config: &DriftDetectionConfig,
) -> Option<DriftDiagnosis> {
    let (slope, _, r_squared) = linear_regression(times, delays);

    let slope_threshold = config.slope_threshold();
    let r2_threshold = config.r2_threshold();

    // Slope must exceed threshold (significant drift rate)
    if slope.abs() <= slope_threshold {
        return None;
    }

    // R² must exceed threshold (good linear fit)
    if r_squared <= r2_threshold {
        return None;
    }

    Some(DriftDiagnosis::linear_drift(slope, r_squared))
}

/// Simple linear regression: y = slope * x + intercept
///
/// Returns (slope, intercept, r_squared).
fn linear_regression(x: &[f64], y: &[f64]) -> (f64, f64, f64) {
    if x.len() < 2 || x.len() != y.len() {
        return (0.0, 0.0, 0.0);
    }

    let n = x.len() as f64;

    // Calculate means
    let x_mean = x.iter().sum::<f64>() / n;
    let y_mean = y.iter().sum::<f64>() / n;

    // Calculate slope and intercept
    let mut numerator = 0.0;
    let mut denominator = 0.0;

    for i in 0..x.len() {
        let x_diff = x[i] - x_mean;
        let y_diff = y[i] - y_mean;
        numerator += x_diff * y_diff;
        denominator += x_diff * x_diff;
    }

    if denominator.abs() < 1e-10 {
        return (0.0, y_mean, 0.0);
    }

    let slope = numerator / denominator;
    let intercept = y_mean - slope * x_mean;

    // Calculate R² (coefficient of determination)
    let mut ss_res = 0.0; // Residual sum of squares
    let mut ss_tot = 0.0; // Total sum of squares

    for i in 0..x.len() {
        let y_pred = slope * x[i] + intercept;
        ss_res += (y[i] - y_pred).powi(2);
        ss_tot += (y[i] - y_mean).powi(2);
    }

    let r_squared = if ss_tot.abs() < 1e-10 {
        1.0 // Perfect fit (all y values are the same)
    } else {
        1.0 - (ss_res / ss_tot)
    };

    (slope, intercept, r_squared.max(0.0)) // R² can't be negative
}

/// Simple DBSCAN clustering for 1D data.
///
/// Returns cluster labels for each point. -1 means noise.
fn dbscan_cluster(values: &[f64], epsilon: f64, min_samples: usize) -> Vec<i32> {
    let n = values.len();
    if n == 0 {
        return vec![];
    }

    let mut labels = vec![-1i32; n]; // -1 = unassigned/noise
    let mut cluster_id = 0i32;

    for i in 0..n {
        // Skip already processed points
        if labels[i] != -1 {
            continue;
        }

        // Find neighbors within epsilon
        let neighbors: Vec<usize> = (0..n)
            .filter(|&j| (values[i] - values[j]).abs() <= epsilon)
            .collect();

        // Check if core point (enough neighbors)
        if neighbors.len() < min_samples {
            // Mark as noise (will stay -1)
            continue;
        }

        // Start a new cluster
        labels[i] = cluster_id;

        // Expand cluster using a queue
        let mut queue: Vec<usize> = neighbors.clone();
        let mut queue_idx = 0;

        while queue_idx < queue.len() {
            let j = queue[queue_idx];
            queue_idx += 1;

            // Skip if already in a cluster
            if labels[j] >= 0 && labels[j] != cluster_id {
                continue;
            }

            // Add to cluster
            labels[j] = cluster_id;

            // Find j's neighbors
            let j_neighbors: Vec<usize> = (0..n)
                .filter(|&k| (values[j] - values[k]).abs() <= epsilon)
                .collect();

            // If j is a core point, add its neighbors to the queue
            if j_neighbors.len() >= min_samples {
                for &k in &j_neighbors {
                    if labels[k] == -1 {
                        queue.push(k);
                    }
                }
            }
        }

        cluster_id += 1;
    }

    labels
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(index: usize, start_secs: f64, delay_ms: f64) -> ChunkResult {
        ChunkResult {
            chunk_index: index,
            chunk_start_secs: start_secs,
            delay_ms_raw: delay_ms,
            delay_ms_rounded: delay_ms.round() as i64,
            match_pct: 95.0,
            accepted: true,
            reject_reason: None,
        }
    }

    #[test]
    fn uniform_delays_detected_as_uniform() {
        let chunks: Vec<ChunkResult> = (0..10)
            .map(|i| make_chunk(i + 1, i as f64 * 10.0, -500.0))
            .collect();

        let config = DriftDetectionConfig::default();
        let diagnosis = diagnose_drift(&chunks, &config, None);

        assert_eq!(diagnosis.drift_type, DriftType::Uniform);
    }

    #[test]
    fn pal_drift_detected_at_25fps() {
        // Simulate PAL drift: ~40.9ms per second
        let chunks: Vec<ChunkResult> = (0..10)
            .map(|i| {
                let time = i as f64 * 10.0;
                let delay = time * 40.9; // PAL drift rate
                make_chunk(i + 1, time, delay)
            })
            .collect();

        let config = DriftDetectionConfig::default();
        let diagnosis = diagnose_drift(&chunks, &config, Some(25.0));

        assert_eq!(diagnosis.drift_type, DriftType::PalDrift);
        assert!(diagnosis.drift_rate_ms_per_sec.is_some());
    }

    #[test]
    fn pal_drift_not_detected_at_24fps() {
        // Same drift but wrong framerate
        let chunks: Vec<ChunkResult> = (0..10)
            .map(|i| {
                let time = i as f64 * 10.0;
                let delay = time * 40.9;
                make_chunk(i + 1, time, delay)
            })
            .collect();

        let config = DriftDetectionConfig::default();
        let diagnosis = diagnose_drift(&chunks, &config, Some(24.0));

        // Should be detected as linear drift instead
        assert_ne!(diagnosis.drift_type, DriftType::PalDrift);
    }

    #[test]
    fn linear_drift_detected() {
        // Simulate linear drift: 2 ms/s
        let chunks: Vec<ChunkResult> = (0..10)
            .map(|i| {
                let time = i as f64 * 10.0;
                let delay = time * 2.0; // 2 ms/s drift
                make_chunk(i + 1, time, delay)
            })
            .collect();

        let config = DriftDetectionConfig::default();
        let diagnosis = diagnose_drift(&chunks, &config, None);

        assert_eq!(diagnosis.drift_type, DriftType::LinearDrift);
        assert!(diagnosis.r_squared.unwrap() > 0.9);
    }

    #[test]
    fn stepping_detected() {
        // Two distinct clusters of delays
        let mut chunks = Vec::new();
        for i in 0..5 {
            chunks.push(make_chunk(i + 1, i as f64 * 10.0, -500.0));
        }
        for i in 5..10 {
            chunks.push(make_chunk(i + 1, i as f64 * 10.0, -1500.0)); // Different delay
        }

        let config = DriftDetectionConfig::default();
        let diagnosis = diagnose_drift(&chunks, &config, None);

        assert_eq!(diagnosis.drift_type, DriftType::Stepping);
        assert_eq!(diagnosis.cluster_count, Some(2));
    }

    #[test]
    fn insufficient_chunks_returns_uniform() {
        let chunks: Vec<ChunkResult> = (0..3)
            .map(|i| make_chunk(i + 1, i as f64 * 10.0, -500.0))
            .collect();

        let config = DriftDetectionConfig {
            min_chunks: 6,
            ..Default::default()
        };
        let diagnosis = diagnose_drift(&chunks, &config, None);

        assert_eq!(diagnosis.drift_type, DriftType::Uniform);
        assert!(diagnosis.description.contains("Insufficient"));
    }

    #[test]
    fn linear_regression_calculates_correctly() {
        // y = 2x + 10
        let x = vec![0.0, 1.0, 2.0, 3.0, 4.0];
        let y = vec![10.0, 12.0, 14.0, 16.0, 18.0];

        let (slope, intercept, r_squared) = linear_regression(&x, &y);

        assert!((slope - 2.0).abs() < 0.001);
        assert!((intercept - 10.0).abs() < 0.001);
        assert!((r_squared - 1.0).abs() < 0.001); // Perfect fit
    }

    #[test]
    fn dbscan_finds_clusters() {
        // Two clusters: around 0 and around 100
        let values = vec![0.0, 1.0, 2.0, 100.0, 101.0, 102.0];
        let labels = dbscan_cluster(&values, 10.0, 2);

        // Should have 2 clusters
        let unique: std::collections::HashSet<i32> =
            labels.iter().filter(|&&l| l >= 0).copied().collect();
        assert_eq!(unique.len(), 2);
    }

    #[test]
    fn dbscan_marks_noise() {
        // One clear cluster, one outlier
        let values = vec![0.0, 1.0, 2.0, 1000.0]; // 1000 is an outlier
        let labels = dbscan_cluster(&values, 10.0, 3);

        // Outlier should be noise (-1)
        assert_eq!(labels[3], -1);
    }

    #[test]
    fn codec_detection_works() {
        let config = DriftDetectionConfig::default().with_codec(Some("A_FLAC"));
        assert!(config.is_lossless_codec);

        let config = DriftDetectionConfig::default().with_codec(Some("A_AAC"));
        assert!(!config.is_lossless_codec);

        let config = DriftDetectionConfig::default().with_codec(Some("A_TRUEHD"));
        assert!(config.is_lossless_codec);
    }
}
