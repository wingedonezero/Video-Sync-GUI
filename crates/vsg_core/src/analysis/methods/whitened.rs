//! Whitened Cross-Correlation method.
//!
//! Whitening equalizes the magnitude spectrum of both signals before correlation,
//! making it robust to spectral differences caused by processing, different
//! recording conditions, or frequency-dependent effects.

use std::sync::Mutex;

use rustfft::{num_complex::Complex, FftPlanner};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioChunk, CorrelationResult};

use super::CorrelationMethod;

/// Whitened Cross-Correlation.
///
/// Whitening equalizes the magnitude spectrum of both signals, focusing
/// on timing/phase alignment rather than spectral content matching.
/// Useful for comparing audio that has been processed differently.
pub struct Whitened {
    /// Cached FFT planner for efficiency.
    planner: Mutex<FftPlanner<f64>>,
}

impl Whitened {
    /// Create a new Whitened correlator.
    pub fn new() -> Self {
        Self {
            planner: Mutex::new(FftPlanner::new()),
        }
    }

    /// Compute whitened cross-correlation.
    fn compute_whitened(&self, reference: &[f64], other: &[f64]) -> Vec<f64> {
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

        // Whiten both signals: normalize magnitude while preserving phase
        for val in &mut ref_fft {
            let mag = val.norm();
            if mag > 1e-9 {
                *val /= mag;
            }
        }
        for val in &mut other_fft {
            let mag = val.norm();
            if mag > 1e-9 {
                *val /= mag;
            }
        }

        // Cross-correlation in whitened space
        let mut g: Vec<Complex<f64>> = ref_fft
            .iter()
            .zip(other_fft.iter())
            .map(|(r, t)| r * t.conj())
            .collect();

        // Inverse FFT
        ifft.process(&mut g);

        // Extract real parts and normalize
        let scale = 1.0 / fft_len as f64;
        let correlation: Vec<f64> = g.iter().map(|c| c.re * scale).collect();

        // Rearrange to center zero-lag (same as SCC)
        let half = fft_len / 2;
        let mut centered = vec![0.0; fft_len];
        for i in 0..fft_len {
            let new_idx = (i + half) % fft_len;
            centered[new_idx] = correlation[i];
        }

        centered
    }

    /// Find peak and compute confidence.
    fn find_peak_with_confidence(&self, correlation: &[f64]) -> (isize, f64) {
        let center = correlation.len() / 2;

        // Find peak (using absolute values)
        let abs_corr: Vec<f64> = correlation.iter().map(|x| x.abs()).collect();
        let (peak_idx, _peak_value) = abs_corr
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(i, &v)| (i, v))
            .unwrap_or((center, 0.0));

        // The lag at which peak occurs (relative to center)
        let lag = peak_idx as isize - center as isize;
        let delay = -lag;

        // Use normalized peak confidence
        let confidence = self.compute_normalized_confidence(&abs_corr, peak_idx);

        (delay, confidence)
    }

    /// Compute normalized confidence (same algorithm as GCC-PHAT).
    fn compute_normalized_confidence(&self, abs_corr: &[f64], peak_idx: usize) -> f64 {
        let peak_value = abs_corr[peak_idx];

        // Metric 1: Prominence over noise floor (using median)
        let mut sorted = abs_corr.to_vec();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let noise_floor_median = sorted[sorted.len() / 2];
        let prominence_ratio = peak_value / (noise_floor_median + 1e-9);

        // Metric 2: Uniqueness vs second-best peak
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

        // Metric 3: SNR
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

        // Combine metrics
        let confidence = (prominence_ratio * 5.0) + (uniqueness_ratio * 8.0) + (snr_ratio * 1.5);
        (confidence / 3.0).clamp(0.0, 100.0)
    }
}

impl Default for Whitened {
    fn default() -> Self {
        Self::new()
    }
}

impl CorrelationMethod for Whitened {
    fn name(&self) -> &str {
        "Whitened"
    }

    fn description(&self) -> &str {
        "Whitened Cross-Correlation - robust to spectral differences"
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

        let correlation = self.compute_whitened(&reference.samples, &other.samples);
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

        Ok(self.compute_whitened(&reference.samples, &other.samples))
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
    fn make_impulse_signal(len: usize) -> Vec<f64> {
        let mut samples = vec![0.0; len];
        let center = len / 2;
        for i in 0..len {
            let dist = (i as f64 - center as f64).abs();
            samples[i] = (-dist * dist / 1000.0).exp();
        }
        samples
    }

    #[test]
    fn whitened_correlates_identical_signals() {
        let w = Whitened::new();
        let samples = make_impulse_signal(2000);
        let chunk = make_chunk(samples, 1000);

        let result = w.correlate(&chunk, &chunk).unwrap();

        assert!(
            result.delay_samples.abs() < 5.0,
            "Expected ~0 delay, got {}",
            result.delay_samples
        );
    }

    #[test]
    fn whitened_detects_delay() {
        let w = Whitened::new();
        let delay = 50;
        let samples = make_impulse_signal(2000);

        let ref_chunk = make_chunk(samples.clone(), 1000);

        let mut delayed: Vec<f64> = vec![0.0; delay];
        delayed.extend(&samples[..(2000 - delay)]);
        let other_chunk = make_chunk(delayed, 1000);

        let result = w.correlate(&ref_chunk, &other_chunk).unwrap();

        assert!(
            (result.delay_samples - delay as f64).abs() < 10.0,
            "Expected ~{} delay, got {}",
            delay,
            result.delay_samples
        );
    }
}
