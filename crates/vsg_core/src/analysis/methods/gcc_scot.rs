//! GCC-SCOT (Smoothed Coherence Transform) method.
//!
//! Similar to GCC-PHAT but weights by signal coherence instead of just phase.
//! Better than PHAT when one signal has more noise than the other.

use std::sync::Mutex;

use rustfft::{num_complex::Complex, FftPlanner};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioChunk, CorrelationResult};

use super::CorrelationMethod;

/// GCC-SCOT correlator.
///
/// Normalizes by geometric mean of auto-spectra, giving more weight to
/// frequencies where both signals are strong. Better than PHAT when
/// one signal has more noise than the other.
pub struct GccScot {
    /// Cached FFT planner for efficiency.
    planner: Mutex<FftPlanner<f64>>,
}

impl GccScot {
    /// Create a new GCC-SCOT correlator.
    pub fn new() -> Self {
        Self {
            planner: Mutex::new(FftPlanner::new()),
        }
    }

    /// Compute GCC-SCOT correlation.
    fn compute_gcc_scot(&self, reference: &[f64], other: &[f64]) -> Vec<f64> {
        let n = reference.len() + other.len() - 1;
        let fft_len = n.next_power_of_two();

        // Get cached FFT plans
        let mut planner = self.planner.lock().unwrap();
        let fft = planner.plan_fft_forward(fft_len);
        let ifft = planner.plan_fft_inverse(fft_len);
        drop(planner);

        // Prepare signals (zero-padded)
        let mut ref_fft: Vec<Complex<f64>> = reference
            .iter()
            .map(|&x| Complex::new(x, 0.0))
            .collect();
        ref_fft.resize(fft_len, Complex::new(0.0, 0.0));

        let mut other_fft: Vec<Complex<f64>> = other
            .iter()
            .map(|&x| Complex::new(x, 0.0))
            .collect();
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

        // SCOT weighting: normalize by geometric mean of auto-spectra
        // This gives more weight to frequencies where both signals are strong
        for (i, val) in g.iter_mut().enumerate() {
            let r_power = ref_fft[i].norm_sqr();
            let t_power = other_fft[i].norm_sqr();
            let scot_weight = (r_power * t_power).sqrt() + 1e-9;
            *val /= scot_weight;
        }

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
        let (peak_idx, peak_value) = abs_corr
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(i, &v)| (i, v))
            .unwrap_or((center, 0.0));

        // The lag at which peak occurs (relative to center)
        let lag = peak_idx as isize - center as isize;
        let delay = -lag;

        // Simple confidence: peak prominence over mean
        let mean: f64 = abs_corr.iter().sum::<f64>() / abs_corr.len() as f64;
        let confidence = (peak_value / (mean + 1e-9)) * 10.0;

        (delay, confidence.clamp(0.0, 100.0))
    }
}

impl Default for GccScot {
    fn default() -> Self {
        Self::new()
    }
}

impl CorrelationMethod for GccScot {
    fn name(&self) -> &str {
        "GCC-SCOT"
    }

    fn description(&self) -> &str {
        "Smoothed Coherence Transform - weights by signal coherence"
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

        let correlation = self.compute_gcc_scot(&reference.samples, &other.samples);
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

        Ok(self.compute_gcc_scot(&reference.samples, &other.samples))
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
    fn gcc_scot_correlates_identical_signals() {
        let gcc = GccScot::new();
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
    fn gcc_scot_detects_delay() {
        let gcc = GccScot::new();
        let delay = 50;
        let samples = make_impulse_signal(2000);

        let ref_chunk = make_chunk(samples.clone(), 1000);

        let mut delayed: Vec<f64> = vec![0.0; delay];
        delayed.extend(&samples[..(2000 - delay)]);
        let other_chunk = make_chunk(delayed, 1000);

        let result = gcc.correlate(&ref_chunk, &other_chunk).unwrap();

        assert!(
            (result.delay_samples - delay as f64).abs() < 10.0,
            "Expected ~{} delay, got {}",
            delay,
            result.delay_samples
        );
    }
}
