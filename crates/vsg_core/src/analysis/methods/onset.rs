//! Onset Detection correlation method.
//!
//! Detects audio transients (speech onsets, drum hits, etc.) and correlates
//! the onset strength envelopes rather than raw waveforms. This is more robust
//! when comparing different audio mixes since it matches *when things happen*
//! rather than exact waveform shape.
//!
//! Algorithm (matching librosa's onset_strength):
//! 1. Compute STFT magnitude spectrogram
//! 2. Apply mel filterbank (optional, improves robustness)
//! 3. Compute spectral flux (frame-to-frame magnitude difference)
//! 4. Half-wave rectify (keep only positive differences = onsets)
//! 5. Sum across frequency bands to get 1D onset envelope
//! 6. Correlate envelopes using GCC-PHAT

use std::f64::consts::PI;
use std::sync::Mutex;

use rustfft::{num_complex::Complex, FftPlanner};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioChunk, CorrelationResult};

use super::CorrelationMethod;

/// Onset Detection correlator.
///
/// Computes onset strength envelopes and correlates them using GCC-PHAT.
/// More robust to different audio mixes (e.g., separated vocals vs. original).
pub struct Onset {
    /// FFT size for STFT (window size).
    n_fft: usize,
    /// Hop length between STFT frames.
    hop_length: usize,
    /// Cached FFT planner for efficiency.
    planner: Mutex<FftPlanner<f64>>,
}

impl Onset {
    /// Create a new Onset correlator with default parameters.
    ///
    /// Default: n_fft=2048, hop_length=512 (matching librosa defaults).
    pub fn new() -> Self {
        Self {
            n_fft: 2048,
            hop_length: 512,
            planner: Mutex::new(FftPlanner::new()),
        }
    }

    /// Create a Hann window of the specified size.
    fn hann_window(&self, size: usize) -> Vec<f64> {
        (0..size)
            .map(|i| 0.5 * (1.0 - (2.0 * PI * i as f64 / size as f64).cos()))
            .collect()
    }

    /// Compute Short-Time Fourier Transform magnitude spectrogram.
    ///
    /// Returns a 2D array where each row is a frequency bin and each column is a time frame.
    fn compute_stft_magnitude(&self, samples: &[f64]) -> Vec<Vec<f64>> {
        let window = self.hann_window(self.n_fft);
        let num_frames = (samples.len().saturating_sub(self.n_fft)) / self.hop_length + 1;
        let num_bins = self.n_fft / 2 + 1; // Only positive frequencies

        if num_frames == 0 {
            return vec![];
        }

        let mut planner = self.planner.lock().unwrap();
        let fft = planner.plan_fft_forward(self.n_fft);
        drop(planner);

        let mut spectrogram = vec![vec![0.0; num_frames]; num_bins];

        for (frame_idx, start) in (0..samples.len().saturating_sub(self.n_fft))
            .step_by(self.hop_length)
            .enumerate()
        {
            if frame_idx >= num_frames {
                break;
            }

            // Apply window and prepare for FFT
            let mut buffer: Vec<Complex<f64>> = samples[start..start + self.n_fft]
                .iter()
                .zip(window.iter())
                .map(|(&s, &w)| Complex::new(s * w, 0.0))
                .collect();

            // Compute FFT
            fft.process(&mut buffer);

            // Store magnitudes for positive frequencies
            for (bin, spec) in spectrogram.iter_mut().enumerate().take(num_bins) {
                spec[frame_idx] = buffer[bin].norm();
            }
        }

        spectrogram
    }

    /// Compute onset strength envelope from audio samples.
    ///
    /// Implements spectral flux onset detection:
    /// 1. Compute magnitude spectrogram
    /// 2. Compute frame-to-frame difference
    /// 3. Half-wave rectify (keep positive differences)
    /// 4. Sum across frequency bands
    fn compute_onset_envelope(&self, samples: &[f64]) -> Vec<f64> {
        let spectrogram = self.compute_stft_magnitude(samples);

        if spectrogram.is_empty() || spectrogram[0].len() < 2 {
            return vec![];
        }

        let num_frames = spectrogram[0].len();
        let num_bins = spectrogram.len();
        let mut envelope = vec![0.0; num_frames];

        // First frame has no previous frame, set to 0
        envelope[0] = 0.0;

        // Compute spectral flux for each frame
        for frame in 1..num_frames {
            let mut flux = 0.0;
            for bin in 0..num_bins {
                // Difference from previous frame
                let diff = spectrogram[bin][frame] - spectrogram[bin][frame - 1];
                // Half-wave rectification: only positive differences (onsets)
                if diff > 0.0 {
                    flux += diff;
                }
            }
            envelope[frame] = flux;
        }

        // Normalize envelope
        let max_val = envelope
            .iter()
            .cloned()
            .fold(0.0_f64, |a, b| a.max(b.abs()));
        if max_val > 1e-10 {
            for val in &mut envelope {
                *val /= max_val;
            }
        }

        envelope
    }

    /// Compute GCC-PHAT correlation on two envelopes.
    ///
    /// Returns (delay_frames, confidence) where delay is in envelope frames.
    fn correlate_envelopes(&self, ref_env: &[f64], other_env: &[f64]) -> (isize, f64) {
        if ref_env.is_empty() || other_env.is_empty() {
            return (0, 0.0);
        }

        let n = ref_env.len() + other_env.len() - 1;
        let fft_len = n.next_power_of_two();

        let mut planner = self.planner.lock().unwrap();
        let fft = planner.plan_fft_forward(fft_len);
        let ifft = planner.plan_fft_inverse(fft_len);
        drop(planner);

        // Zero-mean the envelopes for better correlation
        let ref_mean: f64 = ref_env.iter().sum::<f64>() / ref_env.len() as f64;
        let other_mean: f64 = other_env.iter().sum::<f64>() / other_env.len() as f64;

        // Prepare reference envelope
        let mut ref_fft: Vec<Complex<f64>> = ref_env
            .iter()
            .map(|&x| Complex::new(x - ref_mean, 0.0))
            .collect();
        ref_fft.resize(fft_len, Complex::new(0.0, 0.0));

        // Prepare other envelope
        let mut other_fft: Vec<Complex<f64>> = other_env
            .iter()
            .map(|&x| Complex::new(x - other_mean, 0.0))
            .collect();
        other_fft.resize(fft_len, Complex::new(0.0, 0.0));

        // Compute FFTs
        fft.process(&mut ref_fft);
        fft.process(&mut other_fft);

        // Cross-power spectrum with PHAT weighting
        let mut g: Vec<Complex<f64>> = ref_fft
            .iter()
            .zip(other_fft.iter())
            .map(|(r, t)| {
                let cross = r * t.conj();
                let mag = cross.norm();
                if mag > 1e-9 {
                    cross / mag
                } else {
                    Complex::new(0.0, 0.0)
                }
            })
            .collect();

        // Inverse FFT
        ifft.process(&mut g);

        // Find peak
        let scale = 1.0 / fft_len as f64;
        let correlation: Vec<f64> = g.iter().map(|c| c.re.abs() * scale).collect();

        let (peak_idx, _peak_val) = correlation
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(i, &v)| (i, v))
            .unwrap_or((0, 0.0));

        // Convert to signed lag
        let lag = if peak_idx > fft_len / 2 {
            peak_idx as isize - fft_len as isize
        } else {
            peak_idx as isize
        };

        // Compute confidence using normalized peak method
        let confidence = self.compute_confidence(&correlation, peak_idx);

        (-lag, confidence)
    }

    /// Compute confidence score using normalized peak analysis.
    ///
    /// Uses sigmoid transforms to ensure output is strictly 0-100%.
    fn compute_confidence(&self, correlation: &[f64], peak_idx: usize) -> f64 {
        if correlation.is_empty() {
            return 0.0;
        }

        let peak_value = correlation[peak_idx];

        // Metric 1: Prominence over median (noise floor)
        let mut sorted = correlation.to_vec();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let noise_floor = sorted[sorted.len() / 2];
        let prominence_ratio = peak_value / (noise_floor + 1e-9);

        // Metric 2: Uniqueness vs second-best peak
        let neighbor_range = (correlation.len() / 100).max(1);
        let start_mask = peak_idx.saturating_sub(neighbor_range);
        let end_mask = (peak_idx + neighbor_range + 1).min(correlation.len());

        let second_best = correlation
            .iter()
            .enumerate()
            .filter(|(i, _)| *i < start_mask || *i >= end_mask)
            .map(|(_, &v)| v)
            .max_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .unwrap_or(noise_floor);
        let uniqueness_ratio = peak_value / (second_best + 1e-9);

        // Metric 3: SNR using background standard deviation
        let threshold_90_idx = (correlation.len() * 90) / 100;
        let threshold_90 = sorted.get(threshold_90_idx).copied().unwrap_or(peak_value);
        let background: Vec<f64> = correlation
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

        // Sigmoid-like transform: score = 100 * (1 - 1/(1 + ratio/scale))
        // Maps ratio=0 -> 0%, ratio=scale -> 50%, ratio=inf -> 100%
        fn sigmoid_score(ratio: f64, scale: f64) -> f64 {
            100.0 * (1.0 - 1.0 / (1.0 + ratio / scale))
        }

        // Combine metrics with appropriate scales
        // prominence_ratio: good matches have 5+, excellent 20+
        // uniqueness_ratio: good matches have 1.5+, excellent 3+
        // snr_ratio: good matches have 10+, excellent 50+
        let prominence_score = sigmoid_score(prominence_ratio, 10.0);
        let uniqueness_score = sigmoid_score(uniqueness_ratio - 1.0, 2.0); // -1 since identical peaks have ratio=1
        let snr_score = sigmoid_score(snr_ratio, 30.0);

        // Weighted average (uniqueness is most important for correlation quality)
        let confidence = (prominence_score * 0.25 + uniqueness_score * 0.50 + snr_score * 0.25)
            .clamp(0.0, 100.0);

        confidence
    }
}

impl Default for Onset {
    fn default() -> Self {
        Self::new()
    }
}

impl CorrelationMethod for Onset {
    fn name(&self) -> &str {
        "Onset"
    }

    fn description(&self) -> &str {
        "Onset Detection - correlates audio transients/attacks"
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

        // Compute onset envelopes
        let ref_envelope = self.compute_onset_envelope(&reference.samples);
        let other_envelope = self.compute_onset_envelope(&other.samples);

        if ref_envelope.is_empty() || other_envelope.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "Audio too short for onset detection".to_string(),
            ));
        }

        // Correlate envelopes
        let (delay_frames, confidence) = self.correlate_envelopes(&ref_envelope, &other_envelope);

        // Convert frame delay to sample delay
        // Each frame is hop_length samples apart
        let delay_samples = delay_frames as f64 * self.hop_length as f64;

        Ok(CorrelationResult::new(
            delay_samples,
            reference.sample_rate,
            confidence,
        ))
    }

    fn raw_correlation(
        &self,
        reference: &AudioChunk,
        other: &AudioChunk,
    ) -> AnalysisResult<Vec<f64>> {
        // Onset uses frame-level correlation, not sample-level.
        // For peak_fit compatibility, create a synthetic correlation signal
        // with a Gaussian peak at the computed delay position.
        let result = self.correlate(reference, other)?;

        // Create a correlation-like signal at sample resolution
        let n_samples = reference.samples.len();
        let center = n_samples / 2;
        let delay_samples = result.delay_samples as isize;

        // Peak position (in correlation array coordinates)
        let peak_pos = (center as isize + delay_samples) as usize;

        // Create Gaussian peak with width proportional to hop_length
        let sigma = self.hop_length as f64;
        let confidence_scale = result.match_pct / 100.0; // 0-1 scale

        let correlation: Vec<f64> = (0..n_samples)
            .map(|i| {
                let dist = (i as f64 - peak_pos as f64).abs();
                confidence_scale * (-0.5 * (dist / sigma).powi(2)).exp()
            })
            .collect();

        Ok(correlation)
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

    /// Create a signal with impulses (clear onsets) at regular intervals
    fn make_impulse_train(len: usize, interval: usize) -> Vec<f64> {
        let mut samples = vec![0.0; len];
        for i in (0..len).step_by(interval) {
            // Create a short burst (simulating an onset)
            for j in 0..50.min(len - i) {
                samples[i + j] = (-(j as f64) / 10.0).exp() * (j as f64 * 0.5).sin();
            }
        }
        samples
    }

    #[test]
    fn onset_correlates_identical_signals() {
        let onset = Onset::new();
        let samples = make_impulse_train(48000, 4800); // 10 impulses per second at 48kHz
        let chunk = make_chunk(samples, 48000);

        let result = onset.correlate(&chunk, &chunk).unwrap();

        // Identical signals should have near-zero delay
        assert!(
            result.delay_samples.abs() < 1000.0, // Within ~20ms at 48kHz
            "Expected ~0 delay, got {} samples",
            result.delay_samples
        );
    }

    #[test]
    fn onset_detects_delay() {
        let onset = Onset::new();
        let delay_samples = 2400; // 50ms at 48kHz
        let samples = make_impulse_train(48000, 4800);

        let ref_chunk = make_chunk(samples.clone(), 48000);

        // Create delayed signal
        let mut delayed = vec![0.0; delay_samples];
        delayed.extend(&samples[..(48000 - delay_samples)]);
        let other_chunk = make_chunk(delayed, 48000);

        let result = onset.correlate(&ref_chunk, &other_chunk).unwrap();

        // Should detect approximate delay (onset detection has frame-level resolution)
        // With hop_length=512, resolution is ~10.7ms at 48kHz
        let tolerance = 1024.0; // ~21ms tolerance
        assert!(
            (result.delay_samples - delay_samples as f64).abs() < tolerance,
            "Expected ~{} delay, got {}",
            delay_samples,
            result.delay_samples
        );
    }

    #[test]
    fn onset_rejects_empty_chunks() {
        let onset = Onset::new();

        let empty = make_chunk(vec![], 48000);
        let signal = make_chunk(make_impulse_train(48000, 4800), 48000);

        assert!(onset.correlate(&empty, &signal).is_err());
        assert!(onset.correlate(&signal, &empty).is_err());
    }

    #[test]
    fn onset_rejects_sample_rate_mismatch() {
        let onset = Onset::new();

        let chunk1 = make_chunk(make_impulse_train(44100, 4410), 44100);
        let chunk2 = make_chunk(make_impulse_train(48000, 4800), 48000);

        assert!(onset.correlate(&chunk1, &chunk2).is_err());
    }
}
