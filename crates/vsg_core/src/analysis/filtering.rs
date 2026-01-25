//! Audio filtering for correlation preprocessing.
//!
//! Provides band-pass, low-pass, and high-pass filters to isolate
//! frequency ranges of interest (e.g., dialogue frequencies).

use std::f64::consts::PI;

/// Filtering method to apply before correlation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FilterType {
    /// No filtering.
    #[default]
    None,
    /// Low-pass filter (removes high frequencies).
    LowPass,
    /// Band-pass filter (isolates a frequency range).
    BandPass,
    /// High-pass filter (removes low frequencies).
    HighPass,
}

/// Configuration for audio filtering.
#[derive(Debug, Clone)]
pub struct FilterConfig {
    /// Type of filter to apply.
    pub filter_type: FilterType,
    /// Sample rate of the audio.
    pub sample_rate: u32,
    /// Low cutoff frequency (Hz) for band-pass/high-pass.
    pub low_cutoff_hz: f64,
    /// High cutoff frequency (Hz) for band-pass/low-pass.
    pub high_cutoff_hz: f64,
    /// Filter order (higher = steeper rolloff, more latency).
    pub order: usize,
}

impl Default for FilterConfig {
    fn default() -> Self {
        Self {
            filter_type: FilterType::None,
            sample_rate: 48000,
            low_cutoff_hz: 300.0,   // Dialogue low cutoff
            high_cutoff_hz: 3400.0, // Dialogue high cutoff
            order: 5,
        }
    }
}

impl FilterConfig {
    /// Create a dialogue band-pass filter config.
    pub fn dialogue_bandpass(sample_rate: u32) -> Self {
        Self {
            filter_type: FilterType::BandPass,
            sample_rate,
            low_cutoff_hz: 300.0,
            high_cutoff_hz: 3400.0,
            order: 5,
        }
    }

    /// Create a low-pass filter config.
    pub fn low_pass(sample_rate: u32, cutoff_hz: f64) -> Self {
        Self {
            filter_type: FilterType::LowPass,
            sample_rate,
            low_cutoff_hz: 0.0,
            high_cutoff_hz: cutoff_hz,
            order: 5,
        }
    }

    /// Create a high-pass filter config.
    pub fn high_pass(sample_rate: u32, cutoff_hz: f64) -> Self {
        Self {
            filter_type: FilterType::HighPass,
            sample_rate,
            low_cutoff_hz: cutoff_hz,
            high_cutoff_hz: 0.0,
            order: 5,
        }
    }
}

/// Apply the configured filter to audio samples.
pub fn apply_filter(samples: &[f64], config: &FilterConfig) -> Vec<f64> {
    match config.filter_type {
        FilterType::None => samples.to_vec(),
        FilterType::LowPass => apply_lowpass(samples, config.sample_rate, config.high_cutoff_hz),
        FilterType::HighPass => apply_highpass(samples, config.sample_rate, config.low_cutoff_hz),
        FilterType::BandPass => apply_bandpass(
            samples,
            config.sample_rate,
            config.low_cutoff_hz,
            config.high_cutoff_hz,
        ),
    }
}

/// Apply a simple FIR low-pass filter.
fn apply_lowpass(samples: &[f64], sample_rate: u32, cutoff_hz: f64) -> Vec<f64> {
    let num_taps = 101; // Filter length
    let nyquist = sample_rate as f64 / 2.0;
    let normalized_cutoff = (cutoff_hz / nyquist).min(0.99);

    // Design FIR low-pass filter using windowed sinc
    let coeffs = design_lowpass_fir(num_taps, normalized_cutoff);

    // Apply filter using convolution
    apply_fir_filter(samples, &coeffs)
}

/// Apply a simple FIR high-pass filter.
fn apply_highpass(samples: &[f64], sample_rate: u32, cutoff_hz: f64) -> Vec<f64> {
    let num_taps = 101;
    let nyquist = sample_rate as f64 / 2.0;
    let normalized_cutoff = (cutoff_hz / nyquist).min(0.99);

    // Design high-pass by spectral inversion of low-pass
    let mut coeffs = design_lowpass_fir(num_taps, normalized_cutoff);

    // Spectral inversion: negate all coefficients and add 1 to center
    for coeff in &mut coeffs {
        *coeff = -*coeff;
    }
    coeffs[num_taps / 2] += 1.0;

    apply_fir_filter(samples, &coeffs)
}

/// Apply a simple FIR band-pass filter.
fn apply_bandpass(samples: &[f64], sample_rate: u32, low_hz: f64, high_hz: f64) -> Vec<f64> {
    let num_taps = 101;
    let nyquist = sample_rate as f64 / 2.0;
    let low_normalized = (low_hz / nyquist).min(0.99);
    let high_normalized = (high_hz / nyquist).min(0.99);

    // Band-pass = low-pass(high) - low-pass(low)
    let low_coeffs = design_lowpass_fir(num_taps, low_normalized);
    let high_coeffs = design_lowpass_fir(num_taps, high_normalized);

    // Subtract to get band-pass
    let coeffs: Vec<f64> = high_coeffs
        .iter()
        .zip(low_coeffs.iter())
        .map(|(h, l)| h - l)
        .collect();

    apply_fir_filter(samples, &coeffs)
}

/// Design a low-pass FIR filter using windowed sinc method.
fn design_lowpass_fir(num_taps: usize, normalized_cutoff: f64) -> Vec<f64> {
    let mut coeffs = vec![0.0; num_taps];
    let m = num_taps as f64 - 1.0;

    for i in 0..num_taps {
        let n = i as f64;

        // Ideal sinc response
        let sinc = if (n - m / 2.0).abs() < 1e-10 {
            2.0 * normalized_cutoff
        } else {
            let x = 2.0 * PI * normalized_cutoff * (n - m / 2.0);
            x.sin() / (PI * (n - m / 2.0))
        };

        // Hamming window
        let window = 0.54 - 0.46 * (2.0 * PI * n / m).cos();

        coeffs[i] = sinc * window;
    }

    // Normalize for unity gain at DC
    let sum: f64 = coeffs.iter().sum();
    if sum.abs() > 1e-10 {
        for coeff in &mut coeffs {
            *coeff /= sum;
        }
    }

    coeffs
}

/// Apply FIR filter using direct convolution.
fn apply_fir_filter(samples: &[f64], coeffs: &[f64]) -> Vec<f64> {
    let n = samples.len();
    let m = coeffs.len();

    if n == 0 || m == 0 {
        return samples.to_vec();
    }

    let mut output = vec![0.0; n];

    for i in 0..n {
        let mut sum = 0.0;
        for j in 0..m {
            if i >= j {
                sum += samples[i - j] * coeffs[j];
            }
        }
        output[i] = sum;
    }

    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_filter_returns_same() {
        let samples = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let config = FilterConfig::default();
        let result = apply_filter(&samples, &config);
        assert_eq!(result, samples);
    }

    #[test]
    fn lowpass_attenuates_high_freq() {
        // Generate a mix of low (100 Hz) and high (5000 Hz) frequency signals
        let sample_rate = 48000;
        let duration = 0.1; // 100ms
        let n = (sample_rate as f64 * duration) as usize;

        let samples: Vec<f64> = (0..n)
            .map(|i| {
                let t = i as f64 / sample_rate as f64;
                let low_freq = (2.0 * PI * 100.0 * t).sin(); // 100 Hz
                let high_freq = (2.0 * PI * 5000.0 * t).sin(); // 5000 Hz
                low_freq + high_freq
            })
            .collect();

        let config = FilterConfig::low_pass(sample_rate, 500.0);
        let filtered = apply_filter(&samples, &config);

        // High frequency should be attenuated
        // Check energy in latter part of signal (after filter settles)
        let start = n / 2;
        let original_energy: f64 = samples[start..].iter().map(|x| x * x).sum();
        let filtered_energy: f64 = filtered[start..].iter().map(|x| x * x).sum();

        // Filtered signal should have less energy (high freq removed)
        assert!(
            filtered_energy < original_energy,
            "Low-pass should reduce energy: original={}, filtered={}",
            original_energy,
            filtered_energy
        );
    }

    #[test]
    fn bandpass_isolates_range() {
        let sample_rate = 48000;
        let config = FilterConfig::dialogue_bandpass(sample_rate);

        // Just verify it doesn't crash and returns same length
        let samples: Vec<f64> = (0..4800).map(|i| (i as f64 * 0.01).sin()).collect();
        let filtered = apply_filter(&samples, &config);
        assert_eq!(filtered.len(), samples.len());
    }
}
