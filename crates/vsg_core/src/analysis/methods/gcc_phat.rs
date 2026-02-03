//! GCC-PHAT (Generalized Cross-Correlation with Phase Transform) method.
//!
//! Uses phase-only correlation which is more robust to reverberation
//! and amplitude differences between signals.

use std::sync::Mutex;

use rustfft::{num_complex::Complex, FftPlanner};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioChunk, CorrelationResult};

use super::CorrelationMethod;

/// GCC-PHAT correlator.
///
/// Normalizes the cross-spectrum by its magnitude, keeping only phase
/// information. This makes it robust to:
/// - Different recording levels
/// - Reverberation
/// - Some spectral differences
pub struct GccPhat {
    /// Cached FFT planner for efficiency.
    planner: Mutex<FftPlanner<f64>>,
}

impl GccPhat {
    /// Create a new GCC-PHAT correlator.
    pub fn new() -> Self {
        Self {
            planner: Mutex::new(FftPlanner::new()),
        }
    }

    /// Compute GCC-PHAT correlation.
    fn compute_gcc_phat(&self, reference: &[f64], other: &[f64]) -> Vec<f64> {
        let n = reference.len() + other.len() - 1;
        let fft_len = n.next_power_of_two();

        // Get cached FFT plans
        let mut planner = self.planner.lock().unwrap();
        let fft = planner.plan_fft_forward(fft_len);
        let ifft = planner.plan_fft_inverse(fft_len);
        drop(planner);

        // Prepare signals (zero-padded)
        let mut ref_fft: Vec<Complex<f64>> =
            reference.iter().map(|&x| Complex::new(x, 0.0)).collect();
        ref_fft.resize(fft_len, Complex::new(0.0, 0.0));

        let mut other_fft: Vec<Complex<f64>> =
            other.iter().map(|&x| Complex::new(x, 0.0)).collect();
        other_fft.resize(fft_len, Complex::new(0.0, 0.0));

        // Compute FFTs
        fft.process(&mut ref_fft);
        fft.process(&mut other_fft);

        // Cross-power spectrum: R * conj(T)
        let mut g: Vec<Complex<f64>> = ref_fft
            .iter()
            .zip(other_fft.iter())
            .map(|(r, t)| r * t.conj())
            .collect();

        // PHAT weighting: normalize by magnitude (keep phase only)
        for val in &mut g {
            let mag = val.norm();
            if mag > 1e-9 {
                *val /= mag;
            }
        }

        // Inverse FFT
        ifft.process(&mut g);

        // Extract real parts and normalize
        let scale = 1.0 / fft_len as f64;
        let correlation: Vec<f64> = g.iter().map(|c| c.re * scale).collect();

        // Rearrange to center zero-lag (same as SCC)
        // FFT correlation has zero-lag at index 0, negative lags wrap around
        let half = fft_len / 2;
        let mut centered = vec![0.0; fft_len];
        for i in 0..fft_len {
            let new_idx = (i + half) % fft_len;
            centered[new_idx] = correlation[i];
        }

        centered
    }

    /// Find peak and compute confidence using normalized peak confidence.
    fn find_peak_with_confidence(&self, correlation: &[f64]) -> (isize, f64) {
        let center = correlation.len() / 2;

        // Find peak (using absolute values for GCC-PHAT)
        let abs_corr: Vec<f64> = correlation.iter().map(|x| x.abs()).collect();
        let (peak_idx, _peak_value) = abs_corr
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(i, &v)| (i, v))
            .unwrap_or((center, 0.0));

        // The lag at which peak occurs (relative to center)
        let lag = peak_idx as isize - center as isize;

        // Delay is negation of lag (same convention as SCC)
        let delay = -lag;

        // Normalized peak confidence
        let confidence = self.normalize_peak_confidence(&abs_corr, peak_idx);

        (delay, confidence)
    }

    /// Normalize peak confidence using multiple metrics.
    /// Matches Python's _normalize_peak_confidence function.
    fn normalize_peak_confidence(&self, abs_corr: &[f64], peak_idx: usize) -> f64 {
        let peak_value = abs_corr[peak_idx];

        // Metric 1: Prominence over noise floor (using median)
        let mut sorted = abs_corr.to_vec();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let noise_floor_median = sorted[sorted.len() / 2];
        let prominence_ratio = peak_value / (noise_floor_median + 1e-9);

        // Metric 2: Uniqueness vs second-best peak
        // Exclude neighbors around peak (1% of array size)
        let neighbor_range = (abs_corr.len() / 100).max(1);
        let start_mask = peak_idx.saturating_sub(neighbor_range);
        let end_mask = (peak_idx + neighbor_range + 1).min(abs_corr.len());

        let second_best = abs_corr
            .iter()
            .enumerate()
            .filter(|(i, _)| *i < start_mask || *i >= end_mask)
            .map(|(_, &v)| v)
            .max_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .unwrap_or(noise_floor_median);
        let uniqueness_ratio = peak_value / (second_best + 1e-9);

        // Metric 3: SNR using background standard deviation
        // Use lower 90% of values
        let threshold_90_idx = (abs_corr.len() * 90) / 100;
        let threshold_90 = sorted.get(threshold_90_idx).copied().unwrap_or(peak_value);
        let background: Vec<f64> = abs_corr
            .iter()
            .filter(|&&x| x < threshold_90)
            .copied()
            .collect();

        let bg_stddev = if background.len() > 10 {
            let mean: f64 = background.iter().sum::<f64>() / background.len() as f64;
            let variance: f64 = background.iter().map(|x| (x - mean).powi(2)).sum::<f64>()
                / background.len() as f64;
            variance.sqrt()
        } else {
            1e-9
        };
        let snr_ratio = peak_value / (bg_stddev + 1e-9);

        // Combine metrics with empirical weights (matching Python)
        let confidence = (prominence_ratio * 5.0) + (uniqueness_ratio * 8.0) + (snr_ratio * 1.5);

        // Scale to 0-100 range
        let confidence = confidence / 3.0;

        confidence.clamp(0.0, 100.0)
    }
}

impl Default for GccPhat {
    fn default() -> Self {
        Self::new()
    }
}

impl CorrelationMethod for GccPhat {
    fn name(&self) -> &str {
        "GCC-PHAT"
    }

    fn description(&self) -> &str {
        "Phase Correlation (GCC-PHAT) - robust to reverberation"
    }

    fn correlate(
        &self,
        reference: &AudioChunk,
        other: &AudioChunk,
    ) -> AnalysisResult<CorrelationResult> {
        if reference.samples.is_empty() || other.samples.is_empty() {
            return Err(AnalysisError::InvalidAudio("Empty audio chunk".to_string()));
        }

        if reference.sample_rate != other.sample_rate {
            return Err(AnalysisError::InvalidAudio(format!(
                "Sample rate mismatch: {} vs {}",
                reference.sample_rate, other.sample_rate
            )));
        }

        let correlation = self.compute_gcc_phat(&reference.samples, &other.samples);
        let (delay_samples, confidence) = self.find_peak_with_confidence(&correlation);

        Ok(CorrelationResult::new(
            delay_samples as f64,
            reference.sample_rate,
            confidence,
        ))
    }

    fn raw_correlation(
        &self,
        reference: &AudioChunk,
        other: &AudioChunk,
    ) -> AnalysisResult<Vec<f64>> {
        if reference.samples.is_empty() || other.samples.is_empty() {
            return Err(AnalysisError::InvalidAudio("Empty audio chunk".to_string()));
        }

        Ok(self.compute_gcc_phat(&reference.samples, &other.samples))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(samples: Vec<f64>, sample_rate: u32) -> AudioChunk {
        let duration_secs = samples.len() as f64 / sample_rate as f64;
        AudioChunk {
            samples,
            sample_rate,
            start_time_secs: 0.0,
            duration_secs,
        }
    }

    /// Create an impulse-like signal with clear time localization
    /// (better for testing phase-based methods)
    fn make_impulse_signal(len: usize) -> Vec<f64> {
        let mut samples = vec![0.0; len];
        // Add impulse in the middle with some spread (Gaussian-like)
        let center = len / 2;
        for i in 0..len {
            let dist = (i as f64 - center as f64).abs();
            samples[i] = (-dist * dist / 1000.0).exp();
        }
        samples
    }

    #[test]
    fn gcc_phat_correlates_identical_signals() {
        let gcc = GccPhat::new();
        let samples = make_impulse_signal(2000);
        let chunk = make_chunk(samples, 1000);

        let result = gcc.correlate(&chunk, &chunk).unwrap();

        assert!(
            result.delay_samples.abs() < 5.0,
            "Expected ~0 delay, got {}",
            result.delay_samples
        );
    }

    #[test]
    fn gcc_phat_detects_delay() {
        let gcc = GccPhat::new();
        let delay = 50;
        let samples = make_impulse_signal(2000);

        let ref_chunk = make_chunk(samples.clone(), 1000);

        let mut delayed: Vec<f64> = vec![0.0; delay];
        delayed.extend(&samples[..(2000 - delay)]);
        let other_chunk = make_chunk(delayed, 1000);

        let result = gcc.correlate(&ref_chunk, &other_chunk).unwrap();

        // GCC-PHAT should detect the delay with good precision for impulse signals
        assert!(
            (result.delay_samples - delay as f64).abs() < 10.0,
            "Expected ~{} delay, got {}",
            delay,
            result.delay_samples
        );
    }
}
