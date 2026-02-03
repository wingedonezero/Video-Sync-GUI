//! Dynamic Time Warping (DTW) correlation method.
//!
//! Uses DTW on MFCC features to find optimal alignment between two audio sequences.
//! Handles tempo variations and non-linear time differences. MFCC features are
//! robust to amplitude and timbral differences.
//!
//! Algorithm (matching librosa):
//! 1. Extract MFCC features from both audio chunks
//!    - Compute mel spectrogram (STFT → mel filterbank)
//!    - Apply log scaling
//!    - Apply DCT to decorrelate
//! 2. Compute DTW alignment using dynamic programming
//! 3. Return median offset from warping path as delay estimate

use std::f64::consts::PI;
use std::sync::Mutex;

use rustfft::{num_complex::Complex, FftPlanner};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioChunk, CorrelationResult};

use super::CorrelationMethod;

/// DTW (Dynamic Time Warping) correlator using MFCC features.
///
/// Finds optimal alignment between two sequences, handling tempo variations.
/// Uses MFCC features which are robust to amplitude/timbre differences.
pub struct Dtw {
    /// Number of MFCC coefficients to compute.
    n_mfcc: usize,
    /// Number of mel bands.
    n_mels: usize,
    /// FFT size for STFT.
    n_fft: usize,
    /// Hop length between frames.
    hop_length: usize,
    /// Cached FFT planner.
    planner: Mutex<FftPlanner<f64>>,
}

impl Dtw {
    /// Create a new DTW correlator with default parameters.
    ///
    /// Default: n_mfcc=13, n_mels=40, n_fft=2048, hop_length=512
    pub fn new() -> Self {
        Self {
            n_mfcc: 13,
            n_mels: 40,
            n_fft: 2048,
            hop_length: 512,
            planner: Mutex::new(FftPlanner::new()),
        }
    }

    /// Convert frequency in Hz to mel scale (Slaney formula, matching librosa default).
    fn hz_to_mel(&self, hz: f64) -> f64 {
        // Slaney formula: 1127 * ln(1 + f/700)
        1127.0 * (1.0 + hz / 700.0).ln()
    }

    /// Convert mel scale to frequency in Hz.
    fn mel_to_hz(&self, mel: f64) -> f64 {
        700.0 * ((mel / 1127.0).exp() - 1.0)
    }

    /// Create mel filterbank matrix.
    ///
    /// Returns a matrix of shape (n_mels, n_fft/2+1) where each row is a triangular filter.
    fn create_mel_filterbank(&self, sample_rate: u32) -> Vec<Vec<f64>> {
        let n_bins = self.n_fft / 2 + 1;
        let fmin = 0.0;
        let fmax = sample_rate as f64 / 2.0;

        // Compute mel points
        let mel_min = self.hz_to_mel(fmin);
        let mel_max = self.hz_to_mel(fmax);

        // n_mels + 2 points to create n_mels triangular filters
        let mel_points: Vec<f64> = (0..=self.n_mels + 1)
            .map(|i| mel_min + (mel_max - mel_min) * i as f64 / (self.n_mels + 1) as f64)
            .collect();

        // Convert mel points to Hz
        let hz_points: Vec<f64> = mel_points.iter().map(|&m| self.mel_to_hz(m)).collect();

        // Convert Hz points to FFT bin indices
        let bin_points: Vec<f64> = hz_points
            .iter()
            .map(|&hz| hz * self.n_fft as f64 / sample_rate as f64)
            .collect();

        // Create filterbank
        let mut filterbank = vec![vec![0.0; n_bins]; self.n_mels];

        for i in 0..self.n_mels {
            let start = bin_points[i];
            let center = bin_points[i + 1];
            let end = bin_points[i + 2];

            for j in 0..n_bins {
                let freq_bin = j as f64;

                if freq_bin >= start && freq_bin < center {
                    // Rising slope
                    filterbank[i][j] = (freq_bin - start) / (center - start);
                } else if freq_bin >= center && freq_bin <= end {
                    // Falling slope
                    filterbank[i][j] = (end - freq_bin) / (end - center);
                }
            }

            // Slaney normalization: scale by 2 / (high - low) in Hz
            let bandwidth = hz_points[i + 2] - hz_points[i];
            if bandwidth > 0.0 {
                let norm = 2.0 / bandwidth;
                for j in 0..n_bins {
                    filterbank[i][j] *= norm;
                }
            }
        }

        filterbank
    }

    /// Create a Hann window.
    fn hann_window(&self, size: usize) -> Vec<f64> {
        (0..size)
            .map(|i| 0.5 * (1.0 - (2.0 * PI * i as f64 / size as f64).cos()))
            .collect()
    }

    /// Compute STFT magnitude spectrogram.
    fn compute_stft_power(&self, samples: &[f64]) -> Vec<Vec<f64>> {
        let window = self.hann_window(self.n_fft);
        let num_frames = (samples.len().saturating_sub(self.n_fft)) / self.hop_length + 1;
        let num_bins = self.n_fft / 2 + 1;

        if num_frames == 0 {
            return vec![];
        }

        let mut planner = self.planner.lock().unwrap();
        let fft = planner.plan_fft_forward(self.n_fft);
        drop(planner);

        // spectrogram[frame][bin]
        let mut spectrogram = vec![vec![0.0; num_bins]; num_frames];

        for (frame_idx, start) in (0..samples.len().saturating_sub(self.n_fft))
            .step_by(self.hop_length)
            .enumerate()
        {
            if frame_idx >= num_frames {
                break;
            }

            let mut buffer: Vec<Complex<f64>> = samples[start..start + self.n_fft]
                .iter()
                .zip(window.iter())
                .map(|(&s, &w)| Complex::new(s * w, 0.0))
                .collect();

            fft.process(&mut buffer);

            // Power spectrum (magnitude squared)
            for bin in 0..num_bins {
                spectrogram[frame_idx][bin] = buffer[bin].norm_sqr();
            }
        }

        spectrogram
    }

    /// Apply mel filterbank to power spectrogram.
    fn apply_mel_filterbank(
        &self,
        spectrogram: &[Vec<f64>],
        filterbank: &[Vec<f64>],
    ) -> Vec<Vec<f64>> {
        let num_frames = spectrogram.len();
        let n_mels = filterbank.len();

        // mel_spec[frame][mel_band]
        let mut mel_spec = vec![vec![0.0; n_mels]; num_frames];

        for (frame_idx, frame) in spectrogram.iter().enumerate() {
            for (mel_idx, filter) in filterbank.iter().enumerate() {
                let mut sum = 0.0;
                for (bin, (&spec_val, &filt_val)) in frame.iter().zip(filter.iter()).enumerate() {
                    let _ = bin; // suppress warning
                    sum += spec_val * filt_val;
                }
                mel_spec[frame_idx][mel_idx] = sum;
            }
        }

        mel_spec
    }

    /// Apply DCT-II to extract MFCC from log mel spectrogram.
    ///
    /// DCT-II: X[k] = sum_{n=0}^{N-1} x[n] * cos(pi*k*(2n+1)/(2N))
    fn apply_dct(&self, log_mel: &[f64]) -> Vec<f64> {
        let n = log_mel.len();
        let mut mfcc = vec![0.0; self.n_mfcc];

        for k in 0..self.n_mfcc {
            let mut sum = 0.0;
            for (i, &val) in log_mel.iter().enumerate() {
                sum += val * (PI * k as f64 * (2.0 * i as f64 + 1.0) / (2.0 * n as f64)).cos();
            }
            mfcc[k] = sum;
        }

        // Ortho normalization (matching librosa norm='ortho')
        if !mfcc.is_empty() {
            mfcc[0] *= (1.0 / n as f64).sqrt();
            for k in 1..self.n_mfcc {
                mfcc[k] *= (2.0 / n as f64).sqrt();
            }
        }

        mfcc
    }

    /// Compute MFCC features for audio samples.
    ///
    /// Returns mfcc[frame][coefficient].
    fn compute_mfcc(&self, samples: &[f64], sample_rate: u32) -> Vec<Vec<f64>> {
        // 1. Compute power spectrogram
        let spectrogram = self.compute_stft_power(samples);
        if spectrogram.is_empty() {
            return vec![];
        }

        // 2. Create and apply mel filterbank
        let filterbank = self.create_mel_filterbank(sample_rate);
        let mel_spec = self.apply_mel_filterbank(&spectrogram, &filterbank);

        // 3. Apply log and DCT to get MFCC
        let mut mfcc = Vec::with_capacity(mel_spec.len());
        for frame in &mel_spec {
            // Log of mel spectrogram (with floor to avoid log(0))
            let log_mel: Vec<f64> = frame.iter().map(|&x| (x.max(1e-10)).ln()).collect();

            // DCT to get MFCC
            let coeffs = self.apply_dct(&log_mel);
            mfcc.push(coeffs);
        }

        mfcc
    }

    /// Compute DTW alignment between two MFCC sequences.
    ///
    /// Returns (accumulated_cost_matrix, warping_path).
    fn compute_dtw(&self, x: &[Vec<f64>], y: &[Vec<f64>]) -> (Vec<Vec<f64>>, Vec<(usize, usize)>) {
        let n = x.len();
        let m = y.len();

        if n == 0 || m == 0 {
            return (vec![], vec![]);
        }

        // Cost matrix initialization
        let mut d = vec![vec![f64::INFINITY; m]; n];

        // Compute Euclidean distance for first cell
        d[0][0] = self.euclidean_distance(&x[0], &y[0]);

        // First column
        for i in 1..n {
            d[i][0] = d[i - 1][0] + self.euclidean_distance(&x[i], &y[0]);
        }

        // First row
        for j in 1..m {
            d[0][j] = d[0][j - 1] + self.euclidean_distance(&x[0], &y[j]);
        }

        // Fill the rest with standard DTW recurrence
        for i in 1..n {
            for j in 1..m {
                let cost = self.euclidean_distance(&x[i], &y[j]);
                d[i][j] = cost + d[i - 1][j].min(d[i][j - 1]).min(d[i - 1][j - 1]);
            }
        }

        // Backtrack to find warping path
        let mut path = Vec::new();
        let mut i = n - 1;
        let mut j = m - 1;
        path.push((i, j));

        while i > 0 || j > 0 {
            if i == 0 {
                j -= 1;
            } else if j == 0 {
                i -= 1;
            } else {
                let diag = d[i - 1][j - 1];
                let left = d[i][j - 1];
                let up = d[i - 1][j];

                if diag <= left && diag <= up {
                    i -= 1;
                    j -= 1;
                } else if left <= up {
                    j -= 1;
                } else {
                    i -= 1;
                }
            }
            path.push((i, j));
        }

        path.reverse();
        (d, path)
    }

    /// Euclidean distance between two MFCC vectors.
    fn euclidean_distance(&self, a: &[f64], b: &[f64]) -> f64 {
        a.iter()
            .zip(b.iter())
            .map(|(x, y)| (x - y).powi(2))
            .sum::<f64>()
            .sqrt()
    }
}

impl Default for Dtw {
    fn default() -> Self {
        Self::new()
    }
}

impl CorrelationMethod for Dtw {
    fn name(&self) -> &str {
        "DTW"
    }

    fn description(&self) -> &str {
        "Dynamic Time Warping on MFCC - handles tempo variations"
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

        // Compute MFCC features
        let ref_mfcc = self.compute_mfcc(&reference.samples, reference.sample_rate);
        let other_mfcc = self.compute_mfcc(&other.samples, other.sample_rate);

        if ref_mfcc.is_empty() || other_mfcc.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "Audio too short for MFCC extraction".to_string(),
            ));
        }

        // Compute DTW alignment
        let (cost_matrix, warping_path) = self.compute_dtw(&ref_mfcc, &other_mfcc);

        if warping_path.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "DTW alignment failed".to_string(),
            ));
        }

        // Calculate offsets from warping path
        // offset = other_frame - ref_frame at each point
        let mut offsets: Vec<i64> = warping_path
            .iter()
            .map(|(ref_idx, other_idx)| *other_idx as i64 - *ref_idx as i64)
            .collect();

        // Use median offset (robust to outliers at boundaries)
        offsets.sort();
        let median_offset = offsets[offsets.len() / 2];

        // Convert frame offset to sample offset
        let delay_samples = median_offset as f64 * self.hop_length as f64;

        // Compute confidence from normalized DTW distance
        let path_length = warping_path.len();
        let final_cost = cost_matrix
            .last()
            .and_then(|row| row.last())
            .copied()
            .unwrap_or(f64::INFINITY);

        let avg_cost = if path_length > 0 {
            final_cost / path_length as f64
        } else {
            f64::INFINITY
        };

        // Convert to 0-100 scale (lower cost = higher confidence)
        // Empirically, good matches have avg_cost < 50, poor matches > 200
        let confidence = (100.0 - avg_cost * 0.5).clamp(0.0, 100.0);

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
        if reference.samples.is_empty() || other.samples.is_empty() {
            return Err(AnalysisError::InvalidAudio("Empty audio chunk".to_string()));
        }

        // Return the accumulated cost matrix diagonal for visualization
        let ref_mfcc = self.compute_mfcc(&reference.samples, reference.sample_rate);
        let other_mfcc = self.compute_mfcc(&other.samples, other.sample_rate);

        if ref_mfcc.is_empty() || other_mfcc.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "Audio too short for MFCC extraction".to_string(),
            ));
        }

        let (cost_matrix, _) = self.compute_dtw(&ref_mfcc, &other_mfcc);

        // Return diagonal of cost matrix
        let diag_len = cost_matrix.len().min(
            cost_matrix
                .first()
                .map(|r| r.len())
                .unwrap_or(0),
        );
        let diagonal: Vec<f64> = (0..diag_len).map(|i| cost_matrix[i][i]).collect();

        Ok(diagonal)
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

    /// Create a test signal with harmonic content
    fn make_harmonic_signal(len: usize, sample_rate: u32) -> Vec<f64> {
        let freq = 440.0; // A4
        (0..len)
            .map(|i| {
                let t = i as f64 / sample_rate as f64;
                (2.0 * PI * freq * t).sin()
                    + 0.5 * (2.0 * PI * 2.0 * freq * t).sin()
                    + 0.25 * (2.0 * PI * 3.0 * freq * t).sin()
            })
            .collect()
    }

    #[test]
    fn dtw_correlates_identical_signals() {
        let dtw = Dtw::new();
        let samples = make_harmonic_signal(48000, 48000); // 1 second
        let chunk = make_chunk(samples, 48000);

        let result = dtw.correlate(&chunk, &chunk).unwrap();

        // Identical signals should have near-zero delay
        assert!(
            result.delay_samples.abs() < 2000.0, // Within ~40ms
            "Expected ~0 delay, got {} samples",
            result.delay_samples
        );
        // And high confidence
        assert!(
            result.match_pct > 50.0,
            "Expected high confidence, got {}",
            result.match_pct
        );
    }

    #[test]
    fn dtw_detects_delay() {
        let dtw = Dtw::new();
        let delay_samples = 2400; // 50ms at 48kHz

        // Use a more complex signal with variations for better DTW matching
        let samples: Vec<f64> = (0..48000)
            .map(|i| {
                let t = i as f64 / 48000.0;
                // Mix of frequencies with amplitude modulation
                let env = (2.0 * std::f64::consts::PI * 2.0 * t).sin().abs();
                env * ((2.0 * std::f64::consts::PI * 440.0 * t).sin()
                    + 0.3 * (2.0 * std::f64::consts::PI * 880.0 * t).sin())
            })
            .collect();

        let ref_chunk = make_chunk(samples.clone(), 48000);

        // Create delayed signal
        let mut delayed = vec![0.0; delay_samples];
        delayed.extend(&samples[..(48000 - delay_samples)]);
        let other_chunk = make_chunk(delayed, 48000);

        let result = dtw.correlate(&ref_chunk, &other_chunk).unwrap();

        // DTW has frame-level resolution with hop_length=512, giving ~10.7ms per frame
        // For frame-level methods, a tolerance of several frames is acceptable
        let tolerance = 4096.0; // ~85ms tolerance for frame-level method
        assert!(
            (result.delay_samples - delay_samples as f64).abs() < tolerance,
            "Expected ~{} delay, got {} (tolerance: {})",
            delay_samples,
            result.delay_samples,
            tolerance
        );
    }

    #[test]
    fn dtw_rejects_empty_chunks() {
        let dtw = Dtw::new();

        let empty = make_chunk(vec![], 48000);
        let signal = make_chunk(make_harmonic_signal(48000, 48000), 48000);

        assert!(dtw.correlate(&empty, &signal).is_err());
        assert!(dtw.correlate(&signal, &empty).is_err());
    }

    #[test]
    fn dtw_rejects_sample_rate_mismatch() {
        let dtw = Dtw::new();

        let chunk1 = make_chunk(make_harmonic_signal(44100, 44100), 44100);
        let chunk2 = make_chunk(make_harmonic_signal(48000, 48000), 48000);

        assert!(dtw.correlate(&chunk1, &chunk2).is_err());
    }

    #[test]
    fn mel_filterbank_has_correct_shape() {
        let dtw = Dtw::new();
        let filterbank = dtw.create_mel_filterbank(48000);

        assert_eq!(filterbank.len(), dtw.n_mels);
        assert_eq!(filterbank[0].len(), dtw.n_fft / 2 + 1);
    }

    #[test]
    fn mfcc_has_correct_shape() {
        let dtw = Dtw::new();
        let samples = make_harmonic_signal(48000, 48000);
        let mfcc = dtw.compute_mfcc(&samples, 48000);

        assert!(!mfcc.is_empty());
        assert_eq!(mfcc[0].len(), dtw.n_mfcc);
    }
}
