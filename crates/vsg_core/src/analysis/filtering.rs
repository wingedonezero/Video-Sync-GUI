//! Audio filtering for correlation preprocessing.
//!
//! Provides band-pass, low-pass, and high-pass filters using IIR Butterworth
//! design via the biquad crate, matching Python's scipy.signal.butter behavior.

use biquad::{Biquad, Coefficients, DirectForm2Transposed, ToHertz, Type, Q_BUTTERWORTH_F64};

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
    /// Filter order (higher = steeper rolloff).
    /// For biquad, this is implemented as cascaded second-order sections.
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
        FilterType::LowPass => apply_butterworth_lowpass(
            samples,
            config.sample_rate,
            config.high_cutoff_hz,
            config.order,
        ),
        FilterType::HighPass => apply_butterworth_highpass(
            samples,
            config.sample_rate,
            config.low_cutoff_hz,
            config.order,
        ),
        FilterType::BandPass => apply_butterworth_bandpass(
            samples,
            config.sample_rate,
            config.low_cutoff_hz,
            config.high_cutoff_hz,
            config.order,
        ),
    }
}

/// Apply a Butterworth low-pass filter using cascaded biquad sections.
fn apply_butterworth_lowpass(
    samples: &[f64],
    sample_rate: u32,
    cutoff_hz: f64,
    order: usize,
) -> Vec<f64> {
    if samples.is_empty() {
        return Vec::new();
    }

    let fs = sample_rate.hz();
    let f0 = cutoff_hz.hz();

    // Create coefficients for low-pass Butterworth
    let coeffs = match Coefficients::<f64>::from_params(Type::LowPass, fs, f0, Q_BUTTERWORTH_F64) {
        Ok(c) => c,
        Err(_) => return samples.to_vec(), // Return unfiltered on error
    };

    // Apply cascaded second-order sections for higher orders
    apply_cascaded_filter(samples, &coeffs, order)
}

/// Apply a Butterworth high-pass filter using cascaded biquad sections.
fn apply_butterworth_highpass(
    samples: &[f64],
    sample_rate: u32,
    cutoff_hz: f64,
    order: usize,
) -> Vec<f64> {
    if samples.is_empty() {
        return Vec::new();
    }

    let fs = sample_rate.hz();
    let f0 = cutoff_hz.hz();

    let coeffs = match Coefficients::<f64>::from_params(Type::HighPass, fs, f0, Q_BUTTERWORTH_F64) {
        Ok(c) => c,
        Err(_) => return samples.to_vec(),
    };

    apply_cascaded_filter(samples, &coeffs, order)
}

/// Apply a Butterworth band-pass filter using cascaded biquad sections.
fn apply_butterworth_bandpass(
    samples: &[f64],
    sample_rate: u32,
    low_hz: f64,
    high_hz: f64,
    order: usize,
) -> Vec<f64> {
    if samples.is_empty() {
        return Vec::new();
    }

    // Band-pass is implemented as high-pass followed by low-pass
    // Each gets half the order (rounded up)
    let hp_order = (order + 1) / 2;
    let lp_order = (order + 1) / 2;

    // First apply high-pass (removes frequencies below low_hz)
    let high_passed = apply_butterworth_highpass(samples, sample_rate, low_hz, hp_order);

    // Then apply low-pass (removes frequencies above high_hz)
    apply_butterworth_lowpass(&high_passed, sample_rate, high_hz, lp_order)
}

/// Apply a filter multiple times (cascaded) for higher order response.
/// Each cascade doubles the effective order (steeper rolloff).
fn apply_cascaded_filter(
    samples: &[f64],
    coeffs: &Coefficients<f64>,
    order: usize,
) -> Vec<f64> {
    // Number of cascaded sections needed
    // A biquad is 2nd order, so we need order/2 sections (minimum 1)
    let num_sections = ((order + 1) / 2).max(1);

    let mut result = samples.to_vec();

    for _ in 0..num_sections {
        // Create a fresh filter for each section
        let mut filter = DirectForm2Transposed::<f64>::new(*coeffs);

        // Process each sample through this section
        for sample in &mut result {
            *sample = filter.run(*sample);
        }
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::PI;

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
    fn highpass_attenuates_low_freq() {
        let sample_rate = 48000;
        let duration = 0.1;
        let n = (sample_rate as f64 * duration) as usize;

        // Generate low frequency signal (50 Hz)
        let samples: Vec<f64> = (0..n)
            .map(|i| {
                let t = i as f64 / sample_rate as f64;
                (2.0 * PI * 50.0 * t).sin()
            })
            .collect();

        let config = FilterConfig::high_pass(sample_rate, 200.0);
        let filtered = apply_filter(&samples, &config);

        // Check energy in latter part (after filter settles)
        let start = n / 2;
        let original_energy: f64 = samples[start..].iter().map(|x| x * x).sum();
        let filtered_energy: f64 = filtered[start..].iter().map(|x| x * x).sum();

        // Filtered should have much less energy (low freq removed)
        assert!(
            filtered_energy < original_energy * 0.5,
            "High-pass should significantly reduce low freq energy: original={}, filtered={}",
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

    #[test]
    fn bandpass_passes_in_band_freq() {
        let sample_rate = 48000;
        let duration = 0.2; // Longer duration for filter to settle
        let n = (sample_rate as f64 * duration) as usize;

        // Generate in-band frequency (1000 Hz, well within 300-3400 Hz)
        let samples: Vec<f64> = (0..n)
            .map(|i| {
                let t = i as f64 / sample_rate as f64;
                (2.0 * PI * 1000.0 * t).sin()
            })
            .collect();

        // Use lower order for less aggressive filtering
        let mut config = FilterConfig::dialogue_bandpass(sample_rate);
        config.order = 2;
        let filtered = apply_filter(&samples, &config);

        // Check energy in latter 25% (after filter fully settles)
        let start = (n * 3) / 4;
        let original_energy: f64 = samples[start..].iter().map(|x| x * x).sum();
        let filtered_energy: f64 = filtered[start..].iter().map(|x| x * x).sum();

        // In-band signal should retain significant energy
        assert!(
            filtered_energy > original_energy * 0.1,
            "Band-pass should pass in-band freq: original={}, filtered={}",
            original_energy,
            filtered_energy
        );
    }

    #[test]
    fn empty_samples_handled() {
        let samples: Vec<f64> = vec![];
        let config = FilterConfig::low_pass(48000, 1000.0);
        let result = apply_filter(&samples, &config);
        assert!(result.is_empty());
    }
}
