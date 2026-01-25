//! Standard Cross-Correlation (SCC) method.
//!
//! Uses FFT-based cross-correlation for efficient computation.
//! This is the primary method for audio sync analysis.

use rustfft::{num_complex::Complex, FftPlanner};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioChunk, CorrelationResult};

use super::CorrelationMethod;

/// Standard Cross-Correlation using FFT.
///
/// Computes normalized cross-correlation between two audio signals
/// using the convolution theorem: corr(a,b) = IFFT(FFT(a) * conj(FFT(b)))
pub struct Scc {
    /// Whether to normalize the correlation output.
    normalize: bool,
}

impl Scc {
    /// Create a new SCC correlator.
    pub fn new() -> Self {
        Self { normalize: true }
    }

    /// Create a non-normalizing SCC correlator.
    #[allow(dead_code)]
    pub fn without_normalization() -> Self {
        Self { normalize: false }
    }

    /// Compute FFT-based cross-correlation.
    ///
    /// Returns the cross-correlation array where index n represents
    /// the correlation when `other` is shifted by n samples.
    fn compute_cross_correlation(&self, reference: &[f64], other: &[f64]) -> Vec<f64> {
        // Pad to power of 2 for efficient FFT
        // Use length that can contain full correlation (len1 + len2 - 1)
        let correlation_len = reference.len() + other.len() - 1;
        let fft_len = correlation_len.next_power_of_two();

        // Create FFT planner
        let mut planner = FftPlanner::<f64>::new();
        let fft = planner.plan_fft_forward(fft_len);
        let ifft = planner.plan_fft_inverse(fft_len);

        // Prepare reference signal (zero-padded)
        let mut ref_complex: Vec<Complex<f64>> = reference
            .iter()
            .map(|&x| Complex::new(x, 0.0))
            .collect();
        ref_complex.resize(fft_len, Complex::new(0.0, 0.0));

        // Prepare other signal (zero-padded)
        let mut other_complex: Vec<Complex<f64>> = other
            .iter()
            .map(|&x| Complex::new(x, 0.0))
            .collect();
        other_complex.resize(fft_len, Complex::new(0.0, 0.0));

        // Compute FFTs
        fft.process(&mut ref_complex);
        fft.process(&mut other_complex);

        // Multiply ref by conjugate of other (correlation in frequency domain)
        let mut product: Vec<Complex<f64>> = ref_complex
            .iter()
            .zip(other_complex.iter())
            .map(|(a, b)| a * b.conj())
            .collect();

        // Inverse FFT
        ifft.process(&mut product);

        // Extract real parts and normalize by FFT length
        let scale = 1.0 / fft_len as f64;
        let mut correlation: Vec<f64> = product.iter().map(|c| c.re * scale).collect();

        // Normalize by signal energies if requested
        if self.normalize {
            let ref_energy: f64 = reference.iter().map(|x| x * x).sum();
            let other_energy: f64 = other.iter().map(|x| x * x).sum();
            let norm_factor = (ref_energy * other_energy).sqrt();

            if norm_factor > 1e-10 {
                for val in &mut correlation {
                    *val /= norm_factor;
                }
            }
        }

        // Rearrange to center zero-lag
        // FFT correlation has zero-lag at index 0, negative lags wrap around
        // We want: [..., -2, -1, 0, 1, 2, ...]
        let half = fft_len / 2;
        let mut centered = vec![0.0; fft_len];
        for i in 0..fft_len {
            let new_idx = (i + half) % fft_len;
            centered[new_idx] = correlation[i];
        }

        centered
    }

    /// Find the peak in the correlation array.
    ///
    /// Returns (delay_samples, peak_value) where delay is how much to shift `other`
    /// to align with `reference`. Positive delay means `other` is behind.
    fn find_peak(&self, correlation: &[f64]) -> (isize, f64) {
        let center = correlation.len() / 2;

        let (max_idx, max_val) = correlation
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(i, &v)| (i, v))
            .unwrap_or((center, 0.0));

        // The lag at which peak occurs
        let lag = max_idx as isize - center as isize;

        // Delay is the negation of lag:
        // - Peak at positive lag means ref leads (other is behind) = positive delay
        // - Peak at negative lag means ref lags (other is ahead) = negative delay
        let delay = -lag;

        (delay, max_val)
    }
}

impl Default for Scc {
    fn default() -> Self {
        Self::new()
    }
}

impl CorrelationMethod for Scc {
    fn name(&self) -> &str {
        "SCC"
    }

    fn description(&self) -> &str {
        "Standard Cross-Correlation using FFT"
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

        let correlation = self.compute_cross_correlation(&reference.samples, &other.samples);
        let (offset, peak_val) = self.find_peak(&correlation);

        // Offset is how much to shift `other` to align with `reference`
        // Positive offset means `other` is behind (needs to be shifted forward)
        let delay_samples = offset as f64;

        Ok(CorrelationResult::new(
            delay_samples,
            reference.sample_rate,
            peak_val * 100.0, // Convert 0-1 correlation to 0-100 match percentage
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

        Ok(self.compute_cross_correlation(&reference.samples, &other.samples))
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

    #[test]
    fn scc_correlates_identical_signals() {
        let scc = Scc::new();

        // Create a simple signal
        let samples: Vec<f64> = (0..1000).map(|i| (i as f64 * 0.1).sin()).collect();
        let chunk = make_chunk(samples, 1000);

        let result = scc.correlate(&chunk, &chunk).unwrap();

        // Identical signals should have zero delay and high correlation
        assert!(
            result.delay_samples.abs() < 1.0,
            "Expected ~0 delay, got {}",
            result.delay_samples
        );
        assert!(
            result.match_pct > 90.0,
            "Expected high match percentage, got {}",
            result.match_pct
        );
    }

    #[test]
    fn scc_detects_positive_delay() {
        let scc = Scc::new();

        // Create a signal and a delayed version
        let delay = 50; // samples
        let samples: Vec<f64> = (0..1000).map(|i| (i as f64 * 0.1).sin()).collect();

        let ref_chunk = make_chunk(samples.clone(), 1000);

        // Create delayed signal (shift right = other is behind reference)
        let mut delayed: Vec<f64> = vec![0.0; delay];
        delayed.extend(&samples[..(1000 - delay)]);
        let other_chunk = make_chunk(delayed, 1000);

        let result = scc.correlate(&ref_chunk, &other_chunk).unwrap();

        // Other is behind by `delay` samples
        assert!(
            (result.delay_samples - delay as f64).abs() < 2.0,
            "Expected ~{} delay, got {}",
            delay,
            result.delay_samples
        );
    }

    #[test]
    fn scc_detects_negative_delay() {
        let scc = Scc::new();

        // Create a signal and an advanced version
        let advance = 50; // samples
        let samples: Vec<f64> = (0..1000).map(|i| (i as f64 * 0.1).sin()).collect();

        let ref_chunk = make_chunk(samples.clone(), 1000);

        // Create advanced signal (shift left = other is ahead of reference)
        let mut advanced: Vec<f64> = samples[advance..].to_vec();
        advanced.extend(vec![0.0; advance]);
        let other_chunk = make_chunk(advanced, 1000);

        let result = scc.correlate(&ref_chunk, &other_chunk).unwrap();

        // Other is ahead by `advance` samples
        assert!(
            (result.delay_samples + advance as f64).abs() < 2.0,
            "Expected ~-{} delay, got {}",
            advance,
            result.delay_samples
        );
    }

    #[test]
    fn scc_calculates_delay_ms() {
        let scc = Scc::new();

        // At 48000 Hz, 48 samples = 1ms
        let samples: Vec<f64> = (0..4800).map(|i| (i as f64 * 0.1).sin()).collect();
        let ref_chunk = make_chunk(samples.clone(), 48000);

        // Delay by 48 samples = 1ms
        let mut delayed: Vec<f64> = vec![0.0; 48];
        delayed.extend(&samples[..(4800 - 48)]);
        let other_chunk = make_chunk(delayed, 48000);

        let result = scc.correlate(&ref_chunk, &other_chunk).unwrap();

        assert!(
            (result.delay_ms_raw - 1.0).abs() < 0.1,
            "Expected ~1ms delay, got {}ms",
            result.delay_ms_raw
        );
    }

    #[test]
    fn scc_rejects_empty_chunks() {
        let scc = Scc::new();

        let empty = make_chunk(vec![], 1000);
        let signal = make_chunk(vec![1.0, 2.0, 3.0], 1000);

        assert!(scc.correlate(&empty, &signal).is_err());
        assert!(scc.correlate(&signal, &empty).is_err());
    }

    #[test]
    fn scc_rejects_sample_rate_mismatch() {
        let scc = Scc::new();

        let chunk1 = make_chunk(vec![1.0, 2.0, 3.0], 44100);
        let chunk2 = make_chunk(vec![1.0, 2.0, 3.0], 48000);

        assert!(scc.correlate(&chunk1, &chunk2).is_err());
    }
}
