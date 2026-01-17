// src/analysis/correlation.rs
// Audio correlation engine for delay detection
// Implements GCC-PHAT and other correlation methods

use num_complex::Complex64;
use rustfft::FftPlanner;
use rayon::prelude::*;

/// CRITICAL: GCC-PHAT normalization epsilon - must be exactly 1e-9
const GCC_PHAT_EPSILON: f64 = 1e-9;

/// Default sample rate for audio processing
const DEFAULT_SAMPLE_RATE: u32 = 48000;

/// Chunk result from correlation analysis
#[derive(Debug, Clone)]
pub struct ChunkResult {
    pub delay_ms: i32,          // Rounded delay for mkvmerge
    pub raw_delay_ms: f64,      // Unrounded delay for precision
    pub confidence: f64,        // Match confidence 0-100
    pub start_time_s: f64,      // Start time of chunk in seconds
    pub accepted: bool,         // True if confidence >= threshold
}

/// Configuration for correlation analysis
#[derive(Debug, Clone)]
pub struct CorrelationConfig {
    pub chunk_duration_s: f64,
    pub scan_start_pct: f64,
    pub scan_end_pct: f64,
    pub min_match_pct: f64,
    pub chunk_count: usize,
}

impl Default for CorrelationConfig {
    fn default() -> Self {
        CorrelationConfig {
            chunk_duration_s: 15.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
            min_match_pct: 5.0,
            chunk_count: 10,
        }
    }
}

/// Normalize peak confidence by comparing to noise floor and second-best peak
/// CRITICAL: This must match the Python implementation exactly
fn normalize_peak_confidence(correlation: &[Complex64], peak_idx: usize) -> f64 {
    let abs_corr: Vec<f64> = correlation.iter().map(|c| c.norm()).collect();
    let peak_value = abs_corr[peak_idx];

    // Metric 1: Noise floor using median (more robust than mean)
    let mut sorted = abs_corr.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let noise_floor_median = sorted[sorted.len() / 2];
    let prominence_ratio = peak_value / (noise_floor_median + 1e-9);

    // Metric 2: Find second-best peak (excluding immediate neighbors)
    let neighbor_range = (abs_corr.len() / 100).max(1);
    let start_mask = peak_idx.saturating_sub(neighbor_range);
    let end_mask = (peak_idx + neighbor_range + 1).min(abs_corr.len());

    let second_best = abs_corr.iter()
        .enumerate()
        .filter(|(i, _)| *i < start_mask || *i >= end_mask)
        .map(|(_, v)| *v)
        .max_by(|a, b| a.partial_cmp(b).unwrap())
        .unwrap_or(noise_floor_median);

    let uniqueness_ratio = peak_value / (second_best + 1e-9);

    // Metric 3: SNR using robust background estimation
    let threshold_90 = sorted[(sorted.len() as f64 * 0.9) as usize];
    let background: Vec<f64> = abs_corr.iter()
        .copied()
        .filter(|v| *v < threshold_90)
        .collect();

    let bg_stddev = if background.len() > 10 {
        let mean = background.iter().sum::<f64>() / background.len() as f64;
        let variance = background.iter()
            .map(|v| (v - mean).powi(2))
            .sum::<f64>() / background.len() as f64;
        variance.sqrt()
    } else {
        1e-9
    };

    let snr_ratio = peak_value / (bg_stddev + 1e-9);

    // Combine metrics with empirically tuned weights
    let confidence = (prominence_ratio * 5.0) + (uniqueness_ratio * 8.0) + (snr_ratio * 1.5);

    // Scale to 0-100 range
    (confidence / 3.0).min(100.0).max(0.0)
}

/// GCC-PHAT (Generalized Cross-Correlation with Phase Transform)
/// CRITICAL: Must match Python implementation exactly
pub fn gcc_phat(ref_chunk: &[f32], tgt_chunk: &[f32], sample_rate: u32) -> (f64, f64) {
    let n = ref_chunk.len() + tgt_chunk.len() - 1;

    // Convert to Complex64
    let ref_complex: Vec<Complex64> = ref_chunk.iter()
        .map(|&x| Complex64::new(x as f64, 0.0))
        .collect();
    let tgt_complex: Vec<Complex64> = tgt_chunk.iter()
        .map(|&x| Complex64::new(x as f64, 0.0))
        .collect();

    // Prepare FFT
    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(n);
    let ifft = planner.plan_fft_inverse(n);

    // FFT of both signals
    let mut ref_fft = vec![Complex64::new(0.0, 0.0); n];
    let mut tgt_fft = vec![Complex64::new(0.0, 0.0); n];

    for (i, &val) in ref_complex.iter().enumerate() {
        ref_fft[i] = val;
    }
    for (i, &val) in tgt_complex.iter().enumerate() {
        tgt_fft[i] = val;
    }

    fft.process(&mut ref_fft);
    fft.process(&mut tgt_fft);

    // Cross-power spectrum
    let mut g: Vec<Complex64> = ref_fft.iter()
        .zip(tgt_fft.iter())
        .map(|(r, t)| r * t.conj())
        .collect();

    // CRITICAL: Phase normalization with epsilon = 1e-9
    let g_phat: Vec<Complex64> = g.iter()
        .map(|&x| x / (x.norm() + GCC_PHAT_EPSILON))
        .collect();

    // IFFT
    let mut r_phat = g_phat.clone();
    ifft.process(&mut r_phat);

    // Find peak
    let k = r_phat.iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.norm().partial_cmp(&b.norm()).unwrap())
        .map(|(i, _)| i)
        .unwrap();

    // CRITICAL: Lag calculation matches Python exactly
    let lag_samples = if k > n / 2 {
        k as i64 - n as i64
    } else {
        k as i64
    };

    // CRITICAL: Delay in ms = (lag_samples / sr) * 1000.0
    let delay_ms = (lag_samples as f64 / sample_rate as f64) * 1000.0;
    let confidence = normalize_peak_confidence(&r_phat, k);

    (delay_ms, confidence)
}

/// Standard Cross-Correlation (SCC)
pub fn scc(ref_chunk: &[f32], tgt_chunk: &[f32], sample_rate: u32) -> (f64, f64) {
    // Normalize chunks
    let ref_mean = ref_chunk.iter().sum::<f32>() / ref_chunk.len() as f32;
    let ref_std = (ref_chunk.iter()
        .map(|&x| (x - ref_mean).powi(2))
        .sum::<f32>() / ref_chunk.len() as f32)
        .sqrt();

    let tgt_mean = tgt_chunk.iter().sum::<f32>() / tgt_chunk.len() as f32;
    let tgt_std = (tgt_chunk.iter()
        .map(|&x| (x - tgt_mean).powi(2))
        .sum::<f32>() / tgt_chunk.len() as f32)
        .sqrt();

    let r: Vec<f32> = ref_chunk.iter()
        .map(|&x| (x - ref_mean) / (ref_std + 1e-9))
        .collect();
    let t: Vec<f32> = tgt_chunk.iter()
        .map(|&x| (x - tgt_mean) / (tgt_std + 1e-9))
        .collect();

    // Use FFT for correlation (faster than direct convolution)
    let n = r.len() + t.len() - 1;
    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(n);
    let ifft = planner.plan_fft_inverse(n);

    let mut r_fft = vec![Complex64::new(0.0, 0.0); n];
    let mut t_fft = vec![Complex64::new(0.0, 0.0); n];

    for (i, &val) in r.iter().enumerate() {
        r_fft[i] = Complex64::new(val as f64, 0.0);
    }
    for (i, &val) in t.iter().enumerate() {
        t_fft[i] = Complex64::new(val as f64, 0.0);
    }

    fft.process(&mut r_fft);
    fft.process(&mut t_fft);

    let mut corr: Vec<Complex64> = r_fft.iter()
        .zip(t_fft.iter())
        .map(|(r, t)| r * t.conj())
        .collect();

    ifft.process(&mut corr);

    let k = corr.iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.norm().partial_cmp(&b.norm()).unwrap())
        .map(|(i, _)| i)
        .unwrap();

    let lag_samples = k as i64 - (t.len() - 1) as i64;
    let delay_ms = (lag_samples as f64 / sample_rate as f64) * 1000.0;

    // Match percentage calculation
    let match_pct = (corr[k].norm() / (r.iter().map(|&x| x.powi(2)).sum::<f32>().sqrt() as f64
        * t.iter().map(|&x| x.powi(2)).sum::<f32>().sqrt() as f64 + 1e-9)) * 100.0;

    (delay_ms, match_pct)
}

/// GCC-SCOT (Smoothed Coherence Transform)
pub fn gcc_scot(ref_chunk: &[f32], tgt_chunk: &[f32], sample_rate: u32) -> (f64, f64) {
    let n = ref_chunk.len() + tgt_chunk.len() - 1;

    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(n);
    let ifft = planner.plan_fft_inverse(n);

    let mut ref_fft = vec![Complex64::new(0.0, 0.0); n];
    let mut tgt_fft = vec![Complex64::new(0.0, 0.0); n];

    for (i, &val) in ref_chunk.iter().enumerate() {
        ref_fft[i] = Complex64::new(val as f64, 0.0);
    }
    for (i, &val) in tgt_chunk.iter().enumerate() {
        tgt_fft[i] = Complex64::new(val as f64, 0.0);
    }

    fft.process(&mut ref_fft);
    fft.process(&mut tgt_fft);

    // Cross-power spectrum
    let g: Vec<Complex64> = ref_fft.iter()
        .zip(tgt_fft.iter())
        .map(|(r, t)| r * t.conj())
        .collect();

    // SCOT weighting: normalize by geometric mean of auto-spectra
    let r_power: Vec<f64> = ref_fft.iter().map(|c| c.norm().powi(2)).collect();
    let t_power: Vec<f64> = tgt_fft.iter().map(|c| c.norm().powi(2)).collect();

    let g_scot: Vec<Complex64> = g.iter()
        .zip(r_power.iter().zip(t_power.iter()))
        .map(|(g, (rp, tp))| {
            let scot_weight = (rp * tp).sqrt() + 1e-9;
            g / scot_weight
        })
        .collect();

    let mut r_scot = g_scot;
    ifft.process(&mut r_scot);

    let k = r_scot.iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.norm().partial_cmp(&b.norm()).unwrap())
        .map(|(i, _)| i)
        .unwrap();

    let lag_samples = if k > n / 2 {
        k as i64 - n as i64
    } else {
        k as i64
    };

    let delay_ms = (lag_samples as f64 / sample_rate as f64) * 1000.0;

    // Match confidence
    let abs_mean = r_scot.iter().map(|c| c.norm()).sum::<f64>() / r_scot.len() as f64;
    let confidence = (r_scot[k].norm() / (abs_mean + 1e-9) * 10.0).min(100.0);

    (delay_ms, confidence)
}

/// GCC with Spectral Whitening
pub fn gcc_whitened(ref_chunk: &[f32], tgt_chunk: &[f32], sample_rate: u32) -> (f64, f64) {
    let n = ref_chunk.len() + tgt_chunk.len() - 1;

    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(n);
    let ifft = planner.plan_fft_inverse(n);

    let mut ref_fft = vec![Complex64::new(0.0, 0.0); n];
    let mut tgt_fft = vec![Complex64::new(0.0, 0.0); n];

    for (i, &val) in ref_chunk.iter().enumerate() {
        ref_fft[i] = Complex64::new(val as f64, 0.0);
    }
    for (i, &val) in tgt_chunk.iter().enumerate() {
        tgt_fft[i] = Complex64::new(val as f64, 0.0);
    }

    fft.process(&mut ref_fft);
    fft.process(&mut tgt_fft);

    // Whiten both signals: normalize magnitude while preserving phase
    let r_whitened: Vec<Complex64> = ref_fft.iter()
        .map(|r| r / (r.norm() + 1e-9))
        .collect();
    let t_whitened: Vec<Complex64> = tgt_fft.iter()
        .map(|t| t / (t.norm() + 1e-9))
        .collect();

    // Cross-correlation in whitened space
    let g_whitened: Vec<Complex64> = r_whitened.iter()
        .zip(t_whitened.iter())
        .map(|(r, t)| r * t.conj())
        .collect();

    let mut r_whitened_result = g_whitened;
    ifft.process(&mut r_whitened_result);

    let k = r_whitened_result.iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.norm().partial_cmp(&b.norm()).unwrap())
        .map(|(i, _)| i)
        .unwrap();

    let lag_samples = if k > n / 2 {
        k as i64 - n as i64
    } else {
        k as i64
    };

    let delay_ms = (lag_samples as f64 / sample_rate as f64) * 1000.0;
    let confidence = normalize_peak_confidence(&r_whitened_result, k);

    (delay_ms, confidence)
}

/// Correlation method enum
#[derive(Debug, Clone, Copy)]
pub enum CorrelationMethod {
    GccPhat,
    Scc,
    GccScot,
    GccWhitened,
}

/// Process a single chunk with the specified correlation method
fn process_chunk(
    ref_audio: &[f32],
    tgt_audio: &[f32],
    start_sample: usize,
    chunk_samples: usize,
    sample_rate: u32,
    method: CorrelationMethod,
    min_match: f64,
    start_time_s: f64,
) -> Option<ChunkResult> {
    let end_sample = start_sample + chunk_samples;

    if end_sample > ref_audio.len() || end_sample > tgt_audio.len() {
        return None;
    }

    let ref_chunk = &ref_audio[start_sample..end_sample];
    let tgt_chunk = &tgt_audio[start_sample..end_sample];

    let (raw_delay_ms, confidence) = match method {
        CorrelationMethod::GccPhat => gcc_phat(ref_chunk, tgt_chunk, sample_rate),
        CorrelationMethod::Scc => scc(ref_chunk, tgt_chunk, sample_rate),
        CorrelationMethod::GccScot => gcc_scot(ref_chunk, tgt_chunk, sample_rate),
        CorrelationMethod::GccWhitened => gcc_whitened(ref_chunk, tgt_chunk, sample_rate),
    };

    let delay_ms = raw_delay_ms.round() as i32;
    let accepted = confidence >= min_match;

    Some(ChunkResult {
        delay_ms,
        raw_delay_ms,
        confidence,
        start_time_s,
        accepted,
    })
}

/// Run correlation analysis on full audio files
/// CRITICAL: Scan range and chunk processing must match Python
pub fn run_correlation(
    ref_audio: &[f32],
    tgt_audio: &[f32],
    sample_rate: u32,
    config: &CorrelationConfig,
    method: CorrelationMethod,
) -> Vec<ChunkResult> {
    let duration_s = ref_audio.len() as f64 / sample_rate as f64;

    // CRITICAL: Scan range 5% to 95% by default
    let scan_start_s = duration_s * (config.scan_start_pct / 100.0);
    let scan_end_s = duration_s * (config.scan_end_pct / 100.0);

    // Total duration of the scannable area, accounting for final chunk's length
    let scan_range = (scan_end_s - scan_start_s - config.chunk_duration_s).max(0.0);

    let starts: Vec<f64> = (0..config.chunk_count)
        .map(|i| {
            scan_start_s + (scan_range / (config.chunk_count - 1).max(1) as f64) * i as f64
        })
        .collect();

    let chunk_samples = (config.chunk_duration_s * sample_rate as f64).round() as usize;

    // CRITICAL: Parallel processing with rayon
    starts.par_iter()
        .enumerate()
        .filter_map(|(i, &t0)| {
            let start_sample = (t0 * sample_rate as f64).round() as usize;
            process_chunk(
                ref_audio,
                tgt_audio,
                start_sample,
                chunk_samples,
                sample_rate,
                method,
                config.min_match_pct,
                t0,
            )
        })
        .collect()
}
