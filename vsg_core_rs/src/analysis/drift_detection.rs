// src/analysis/drift_detection.rs
// Drift detection and audio diagnosis using DBSCAN clustering

use super::correlation::ChunkResult;
use std::collections::HashMap;

/// Audio diagnosis types
#[derive(Debug, Clone, PartialEq)]
pub enum AudioDiagnosis {
    Uniform,
    Stepping(SteppingDetails),
    PalDrift { rate: f64 },
    LinearDrift { rate: f64 },
    InsufficientData,
}

/// Details for stepping audio
#[derive(Debug, Clone, PartialEq)]
pub struct SteppingDetails {
    pub clusters: usize,
    pub cluster_info: Vec<ClusterInfo>,
    pub valid_clusters: Vec<usize>,
    pub invalid_clusters: Vec<usize>,
    pub correction_mode: String,
    pub fallback_mode: Option<String>,
}

/// Information about a single cluster
#[derive(Debug, Clone, PartialEq)]
pub struct ClusterInfo {
    pub cluster_id: i32,
    pub mean_delay_ms: f64,
    pub std_delay_ms: f64,
    pub chunk_count: usize,
    pub chunk_indices: Vec<usize>,
    pub time_range: (f64, f64),
    pub mean_match_pct: f64,
    pub min_match_pct: f64,
}

/// Quality validation thresholds
#[derive(Debug, Clone)]
pub struct QualityThresholds {
    pub min_chunks_per_cluster: usize,
    pub min_cluster_percentage: f64,
    pub min_cluster_duration_s: f64,
    pub min_match_quality_pct: f64,
    pub min_total_clusters: usize,
}

impl QualityThresholds {
    /// Strict preset
    pub fn strict() -> Self {
        QualityThresholds {
            min_chunks_per_cluster: 3,
            min_cluster_percentage: 10.0,
            min_cluster_duration_s: 30.0,
            min_match_quality_pct: 90.0,
            min_total_clusters: 3,
        }
    }

    /// Normal preset (default)
    pub fn normal() -> Self {
        QualityThresholds {
            min_chunks_per_cluster: 3,
            min_cluster_percentage: 5.0,
            min_cluster_duration_s: 20.0,
            min_match_quality_pct: 85.0,
            min_total_clusters: 2,
        }
    }

    /// Lenient preset
    pub fn lenient() -> Self {
        QualityThresholds {
            min_chunks_per_cluster: 2,
            min_cluster_percentage: 3.0,
            min_cluster_duration_s: 10.0,
            min_match_quality_pct: 75.0,
            min_total_clusters: 2,
        }
    }
}

/// Configuration for drift detection
#[derive(Debug, Clone)]
pub struct DriftConfig {
    // DBSCAN parameters
    pub dbscan_epsilon_ms: f64,        // Default: 20.0
    pub dbscan_min_samples: usize,     // Default: 2

    // Stepping parameters
    pub stepping_correction_mode: String,  // full, strict, filtered, disabled
    pub stepping_quality_mode: String,     // strict, normal, lenient, custom
    pub stepping_filtered_fallback: String, // nearest, reject
    pub quality_thresholds: Option<QualityThresholds>,

    // PAL detection
    pub pal_framerate: f64,           // Default: 25.0
    pub pal_framerate_tolerance: f64, // Default: 0.1
    pub pal_drift_rate: f64,          // Default: 40.9 ms/s
    pub pal_drift_tolerance: f64,     // Default: 5.0 ms/s

    // Linear drift detection
    pub drift_slope_threshold_lossy: f64,    // Default: 2.0 ms/s
    pub drift_slope_threshold_lossless: f64, // Default: 0.2 ms/s
    pub drift_r2_threshold: f64,             // Default: 0.85
    pub drift_r2_threshold_lossless: f64,    // Default: 0.90

    // Minimum chunks
    pub min_accepted_chunks: usize,   // Default: 6
}

impl Default for DriftConfig {
    fn default() -> Self {
        DriftConfig {
            dbscan_epsilon_ms: 20.0,
            dbscan_min_samples: 2,
            stepping_correction_mode: "full".to_string(),
            stepping_quality_mode: "normal".to_string(),
            stepping_filtered_fallback: "nearest".to_string(),
            quality_thresholds: None,
            pal_framerate: 25.0,
            pal_framerate_tolerance: 0.1,
            pal_drift_rate: 40.9,
            pal_drift_tolerance: 5.0,
            drift_slope_threshold_lossy: 2.0,
            drift_slope_threshold_lossless: 0.2,
            drift_r2_threshold: 0.85,
            drift_r2_threshold_lossless: 0.90,
            min_accepted_chunks: 6,
        }
    }
}

/// Validation result for a cluster
#[derive(Debug, Clone)]
struct ClusterValidation {
    valid: bool,
    checks_passed: usize,
    total_checks: usize,
    cluster_size: usize,
    cluster_percentage: f64,
    cluster_duration_s: f64,
    avg_match_quality: f64,
    min_match_quality: f64,
    time_range: (f64, f64),
}

/// Build cluster information from DBSCAN labels
fn build_cluster_info(
    labels: &[Option<usize>],
    accepted: &[&ChunkResult],
    delays: &[f64],
) -> Vec<ClusterInfo> {
    // Group chunks by cluster label
    let mut cluster_members: HashMap<usize, Vec<usize>> = HashMap::new();

    for (i, &label_opt) in labels.iter().enumerate() {
        if let Some(label) = label_opt {
            cluster_members.entry(label).or_insert_with(Vec::new).push(i);
        }
    }

    // Build cluster info for each cluster
    let mut clusters: Vec<ClusterInfo> = cluster_members
        .into_iter()
        .map(|(label, indices)| {
            let member_delays: Vec<f64> = indices.iter().map(|&i| delays[i]).collect();
            let mean_delay = member_delays.iter().sum::<f64>() / member_delays.len() as f64;
            let variance = member_delays.iter()
                .map(|&d| (d - mean_delay).powi(2))
                .sum::<f64>() / member_delays.len() as f64;
            let std_delay = variance.sqrt();

            let start_times: Vec<f64> = indices.iter().map(|&i| accepted[i].start_time_s).collect();
            let min_time = start_times.iter().cloned().fold(f64::INFINITY, f64::min);
            let max_time = start_times.iter().cloned().fold(f64::NEG_INFINITY, f64::max);

            let match_scores: Vec<f64> = indices.iter().map(|&i| accepted[i].confidence).collect();
            let mean_match = match_scores.iter().sum::<f64>() / match_scores.len() as f64;
            let min_match = match_scores.iter().cloned().fold(f64::INFINITY, f64::min);

            ClusterInfo {
                cluster_id: label as i32,
                mean_delay_ms: mean_delay,
                std_delay_ms: std_delay,
                chunk_count: indices.len(),
                chunk_indices: indices,
                time_range: (min_time, max_time),
                mean_match_pct: mean_match,
                min_match_pct: min_match,
            }
        })
        .collect();

    // Sort by mean delay
    clusters.sort_by(|a, b| a.mean_delay_ms.partial_cmp(&b.mean_delay_ms).unwrap());

    clusters
}

/// Validate a single cluster against quality thresholds
fn validate_cluster(
    cluster: &ClusterInfo,
    total_chunks: usize,
    chunk_duration_s: f64,
    thresholds: &QualityThresholds,
) -> ClusterValidation {
    let cluster_percentage = (cluster.chunk_count as f64 / total_chunks as f64) * 100.0;
    let cluster_duration_s = (cluster.time_range.1 - cluster.time_range.0) + chunk_duration_s;

    // Perform validation checks
    let checks = [
        cluster.chunk_count >= thresholds.min_chunks_per_cluster,
        cluster_percentage >= thresholds.min_cluster_percentage,
        cluster_duration_s >= thresholds.min_cluster_duration_s,
        cluster.mean_match_pct >= thresholds.min_match_quality_pct,
    ];

    let checks_passed = checks.iter().filter(|&&c| c).count();
    let all_passed = checks.iter().all(|&c| c);

    ClusterValidation {
        valid: all_passed,
        checks_passed,
        total_checks: checks.len(),
        cluster_size: cluster.chunk_count,
        cluster_percentage,
        cluster_duration_s,
        avg_match_quality: cluster.mean_match_pct,
        min_match_quality: cluster.min_match_pct,
        time_range: cluster.time_range,
    }
}

/// Filter clusters based on quality validation
fn filter_clusters(
    cluster_info: &[ClusterInfo],
    total_chunks: usize,
    chunk_duration_s: f64,
    thresholds: &QualityThresholds,
) -> (Vec<usize>, Vec<usize>) {
    let mut valid_clusters = Vec::new();
    let mut invalid_clusters = Vec::new();

    for (i, cluster) in cluster_info.iter().enumerate() {
        let validation = validate_cluster(cluster, total_chunks, chunk_duration_s, thresholds);

        if validation.valid {
            valid_clusters.push(i);
        } else {
            invalid_clusters.push(i);
        }
    }

    (valid_clusters, invalid_clusters)
}

/// Simple DBSCAN implementation for 1D data
/// Returns cluster labels where None = noise, Some(label) = cluster ID
fn dbscan_1d(delays: &[f64], eps: f64, min_samples: usize) -> Vec<Option<usize>> {
    let n = delays.len();
    let mut labels = vec![None; n];
    let mut cluster_id = 0;

    for i in 0..n {
        // Skip if already labeled
        if labels[i].is_some() {
            continue;
        }

        // Find neighbors within eps distance
        let neighbors: Vec<usize> = (0..n)
            .filter(|&j| (delays[i] - delays[j]).abs() <= eps)
            .collect();

        // If not enough neighbors, mark as noise (for now)
        if neighbors.len() < min_samples {
            continue;
        }

        // Start a new cluster
        labels[i] = Some(cluster_id);

        // Expand cluster (BFS-style)
        let mut to_process: Vec<usize> = neighbors.clone();
        let mut processed = 0;

        while processed < to_process.len() {
            let point = to_process[processed];
            processed += 1;

            // Skip if already labeled
            if labels[point].is_some() {
                continue;
            }

            // Find neighbors of this point
            let point_neighbors: Vec<usize> = (0..n)
                .filter(|&j| (delays[point] - delays[j]).abs() <= eps)
                .collect();

            // Label this point
            labels[point] = Some(cluster_id);

            // If this is a core point, add its neighbors to the queue
            if point_neighbors.len() >= min_samples {
                for &neighbor in &point_neighbors {
                    if labels[neighbor].is_none() && !to_process.contains(&neighbor) {
                        to_process.push(neighbor);
                    }
                }
            }
        }

        cluster_id += 1;
    }

    labels
}

/// Perform linear regression and return (slope, intercept, r_squared)
fn linear_regression(times: &[f64], delays: &[f64]) -> (f64, f64, f64) {
    let n = times.len() as f64;

    let sum_x: f64 = times.iter().sum();
    let sum_y: f64 = delays.iter().sum();
    let sum_xy: f64 = times.iter().zip(delays.iter()).map(|(x, y)| x * y).sum();
    let sum_xx: f64 = times.iter().map(|x| x * x).sum();

    // Calculate slope and intercept
    let slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x);
    let intercept = (sum_y - slope * sum_x) / n;

    // Calculate R²
    let mean_y = sum_y / n;
    let ss_tot: f64 = delays.iter().map(|y| (y - mean_y).powi(2)).sum();
    let ss_res: f64 = times.iter().zip(delays.iter())
        .map(|(x, y)| {
            let predicted = slope * x + intercept;
            (y - predicted).powi(2)
        })
        .sum();

    let r_squared = if ss_tot > 0.0 {
        1.0 - (ss_res / ss_tot)
    } else {
        0.0
    };

    (slope, intercept, r_squared)
}

/// Main function to diagnose audio sync issue
/// CRITICAL: Must match Python logic exactly
pub fn diagnose_audio_issue(
    chunks: &[ChunkResult],
    config: &DriftConfig,
    framerate: Option<f64>,
    codec_id: Option<&str>,
) -> AudioDiagnosis {
    // Filter accepted chunks
    let accepted: Vec<&ChunkResult> = chunks.iter()
        .filter(|c| c.accepted)
        .collect();

    // Check minimum chunks
    if accepted.len() < config.min_accepted_chunks {
        return AudioDiagnosis::InsufficientData;
    }

    // Extract times and delays
    let times: Vec<f64> = accepted.iter().map(|c| c.start_time_s).collect();
    let delays: Vec<f64> = accepted.iter().map(|c| c.delay_ms as f64).collect();

    // --- Test 1: Check for PAL Drift ---
    if let Some(fps) = framerate {
        let is_pal_framerate = (fps - config.pal_framerate).abs() < config.pal_framerate_tolerance;

        if is_pal_framerate {
            let (slope, _, _) = linear_regression(&times, &delays);

            // CRITICAL: PAL drift rate is ~40.9 ms/s ± 5ms tolerance
            if (slope - config.pal_drift_rate).abs() < config.pal_drift_tolerance {
                return AudioDiagnosis::PalDrift { rate: slope };
            }
        }
    }

    // --- Test 2: Check for Stepping (Clustered) ---
    // Run DBSCAN on delays
    // CRITICAL: eps = epsilon_ms (default 20.0), min_samples (default 2)
    let labels = dbscan_1d(&delays, config.dbscan_epsilon_ms, config.dbscan_min_samples);

    // Count unique clusters (excluding noise)
    let unique_clusters: std::collections::HashSet<usize> = labels.iter()
        .filter_map(|&l| l)
        .collect();

    if unique_clusters.len() > 1 {
        // Build cluster information
        let cluster_info = build_cluster_info(&labels, &accepted, &delays);

        // Check if stepping correction is disabled
        if config.stepping_correction_mode == "disabled" {
            return AudioDiagnosis::Uniform;
        }

        // Get quality thresholds
        let thresholds = config.quality_thresholds.clone().unwrap_or_else(|| {
            match config.stepping_quality_mode.as_str() {
                "strict" => QualityThresholds::strict(),
                "lenient" => QualityThresholds::lenient(),
                _ => QualityThresholds::normal(),
            }
        });

        // Get chunk duration from first accepted chunk (assume uniform)
        let chunk_duration_s = if !accepted.is_empty() {
            // We don't have duration stored in ChunkResult, use default 15.0
            15.0
        } else {
            15.0
        };

        // Filter clusters by quality
        let (valid_cluster_indices, invalid_cluster_indices) = filter_clusters(
            &cluster_info,
            accepted.len(),
            chunk_duration_s,
            &thresholds,
        );

        // Decide based on correction mode
        match config.stepping_correction_mode.as_str() {
            "full" | "strict" => {
                // Reject if ANY cluster is invalid
                if !invalid_cluster_indices.is_empty() {
                    return AudioDiagnosis::Uniform;
                }

                // Check minimum total clusters
                if valid_cluster_indices.len() < thresholds.min_total_clusters {
                    return AudioDiagnosis::Uniform;
                }

                // All clusters passed
                return AudioDiagnosis::Stepping(SteppingDetails {
                    clusters: valid_cluster_indices.len(),
                    cluster_info,
                    valid_clusters: valid_cluster_indices,
                    invalid_clusters: invalid_cluster_indices,
                    correction_mode: config.stepping_correction_mode.clone(),
                    fallback_mode: None,
                });
            }
            "filtered" => {
                // Use only valid clusters
                if valid_cluster_indices.len() < thresholds.min_total_clusters {
                    return AudioDiagnosis::Uniform;
                }

                // Check fallback mode
                if config.stepping_filtered_fallback == "reject" && !invalid_cluster_indices.is_empty() {
                    return AudioDiagnosis::Uniform;
                }

                // Accept filtered stepping
                return AudioDiagnosis::Stepping(SteppingDetails {
                    clusters: valid_cluster_indices.len(),
                    cluster_info,
                    valid_clusters: valid_cluster_indices,
                    invalid_clusters: invalid_cluster_indices,
                    correction_mode: config.stepping_correction_mode.clone(),
                    fallback_mode: Some(config.stepping_filtered_fallback.clone()),
                });
            }
            _ => {
                // Unknown mode - use legacy behavior
                let min_cluster_size = cluster_info.iter()
                    .map(|c| c.chunk_count)
                    .min()
                    .unwrap_or(0);

                if min_cluster_size >= thresholds.min_chunks_per_cluster {
                    let num_clusters = cluster_info.len();
                    return AudioDiagnosis::Stepping(SteppingDetails {
                        clusters: num_clusters,
                        cluster_info,
                        valid_clusters: (0..num_clusters).collect(),
                        invalid_clusters: Vec::new(),
                        correction_mode: config.stepping_correction_mode.clone(),
                        fallback_mode: None,
                    });
                } else {
                    return AudioDiagnosis::Uniform;
                }
            }
        }
    }

    // --- Test 3: Check for General Linear Drift ---
    let (slope, _, r_squared) = linear_regression(&times, &delays);

    // Determine if codec is lossless
    let is_lossless = if let Some(codec) = codec_id {
        let codec_lower = codec.to_lowercase();
        codec_lower.contains("pcm") || codec_lower.contains("flac") || codec_lower.contains("truehd")
    } else {
        false
    };

    // Select thresholds based on codec type
    let slope_threshold = if is_lossless {
        config.drift_slope_threshold_lossless
    } else {
        config.drift_slope_threshold_lossy
    };

    let r2_threshold = if is_lossless {
        config.drift_r2_threshold_lossless
    } else {
        config.drift_r2_threshold
    };

    // CRITICAL: Check slope and R² thresholds
    if slope.abs() > slope_threshold && r_squared > r2_threshold {
        return AudioDiagnosis::LinearDrift { rate: slope };
    }

    // --- Default: Uniform Delay ---
    AudioDiagnosis::Uniform
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(delay_ms: i32, start_time_s: f64, confidence: f64, accepted: bool) -> ChunkResult {
        ChunkResult {
            delay_ms,
            raw_delay_ms: delay_ms as f64,
            confidence,
            start_time_s,
            accepted,
        }
    }

    #[test]
    fn test_insufficient_data() {
        let chunks = vec![
            make_chunk(100, 0.0, 50.0, true),
            make_chunk(100, 15.0, 50.0, true),
        ];

        let config = DriftConfig::default();
        let diagnosis = diagnose_audio_issue(&chunks, &config, None, None);

        assert_eq!(diagnosis, AudioDiagnosis::InsufficientData);
    }

    #[test]
    fn test_uniform() {
        let chunks = vec![
            make_chunk(100, 0.0, 50.0, true),
            make_chunk(100, 15.0, 50.0, true),
            make_chunk(101, 30.0, 50.0, true),
            make_chunk(100, 45.0, 50.0, true),
            make_chunk(99, 60.0, 50.0, true),
            make_chunk(100, 75.0, 50.0, true),
        ];

        let config = DriftConfig::default();
        let diagnosis = diagnose_audio_issue(&chunks, &config, None, None);

        assert_eq!(diagnosis, AudioDiagnosis::Uniform);
    }

    #[test]
    fn test_pal_drift() {
        // Simulate PAL drift: 40.9 ms/s
        let mut chunks = Vec::new();
        for i in 0..10 {
            let time_s = i as f64 * 15.0;
            let delay_ms = (100.0 + 40.9 * time_s / 1000.0) as i32;
            chunks.push(make_chunk(delay_ms, time_s, 50.0, true));
        }

        let config = DriftConfig::default();
        let diagnosis = diagnose_audio_issue(&chunks, &config, Some(25.0), None);

        match diagnosis {
            AudioDiagnosis::PalDrift { rate } => {
                assert!((rate - 40.9).abs() < 1.0);
            }
            _ => panic!("Expected PAL drift, got {:?}", diagnosis),
        }
    }

    #[test]
    fn test_linear_drift() {
        // Simulate linear drift: 5 ms/s
        let mut chunks = Vec::new();
        for i in 0..10 {
            let time_s = i as f64 * 15.0;
            let delay_ms = (100.0 + 5.0 * time_s / 1000.0) as i32;
            chunks.push(make_chunk(delay_ms, time_s, 50.0, true));
        }

        let config = DriftConfig::default();
        let diagnosis = diagnose_audio_issue(&chunks, &config, Some(24.0), None);

        match diagnosis {
            AudioDiagnosis::LinearDrift { rate } => {
                assert!((rate - 5.0).abs() < 1.0);
            }
            _ => panic!("Expected linear drift, got {:?}", diagnosis),
        }
    }
}
