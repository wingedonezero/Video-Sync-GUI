//! Peak fitting for sub-sample accuracy.
//!
//! Uses quadratic (parabolic) interpolation to find the true peak
//! position with sub-sample precision.

use crate::analysis::types::CorrelationResult;

/// Apply quadratic peak fitting to refine the delay estimate.
///
/// Uses the peak and its two neighbors to fit a parabola and find
/// the true maximum. This provides sub-sample accuracy.
///
/// # Arguments
/// * `correlation` - The cross-correlation array
/// * `peak_index` - Index of the discrete peak in the correlation array
/// * `sample_rate` - Sample rate for converting to milliseconds
///
/// # Returns
/// Refined CorrelationResult with sub-sample delay.
pub fn fit_peak(correlation: &[f64], peak_index: usize, sample_rate: u32) -> CorrelationResult {
    let center = correlation.len() / 2;
    let peak_val = correlation[peak_index];

    // Need neighbors for interpolation
    if peak_index == 0 || peak_index >= correlation.len() - 1 {
        // Can't interpolate at edges, return discrete result
        let offset = peak_index as f64 - center as f64;
        return CorrelationResult::new(offset, sample_rate, peak_val * 100.0);
    }

    let y0 = correlation[peak_index - 1];
    let y1 = correlation[peak_index]; // peak
    let y2 = correlation[peak_index + 1];

    // Quadratic interpolation: y = ax^2 + bx + c
    // At x=-1: y0 = a - b + c
    // At x=0:  y1 = c
    // At x=1:  y2 = a + b + c
    //
    // Solving: c = y1
    //          a = (y0 + y2)/2 - y1
    //          b = (y2 - y0)/2
    //
    // Peak of parabola: x_peak = -b/(2a)

    let a = (y0 + y2) / 2.0 - y1;
    let b = (y2 - y0) / 2.0;

    // Interpolated peak offset (in samples, relative to peak_index)
    let delta = if a.abs() > 1e-10 {
        -b / (2.0 * a)
    } else {
        0.0
    };

    // Clamp delta to [-1, 1] for sanity
    let delta = delta.clamp(-1.0, 1.0);

    // Interpolated peak value: y_peak = c - b^2/(4a)
    let refined_peak = if a.abs() > 1e-10 {
        y1 - (b * b) / (4.0 * a)
    } else {
        y1
    };

    // Calculate refined offset from center
    let discrete_offset = peak_index as f64 - center as f64;
    let refined_offset = discrete_offset + delta;

    CorrelationResult::new(refined_offset, sample_rate, refined_peak * 100.0).with_peak_fitting()
}

/// Find peak index in correlation array and apply peak fitting.
///
/// This is a convenience function that combines peak finding and fitting.
pub fn find_and_fit_peak(correlation: &[f64], sample_rate: u32) -> CorrelationResult {
    // Find the discrete peak
    let (peak_index, _peak_val) = correlation
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(i, &v)| (i, v))
        .unwrap_or((correlation.len() / 2, 0.0));

    fit_peak(correlation, peak_index, sample_rate)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn peak_fit_on_perfect_parabola() {
        // Create a parabola with peak at x=0.3 (between indices 5 and 6)
        // y = -x^2 + 0.6x + 0.91 has peak at x=0.3, y=1.0
        let center_idx = 5;
        let mut correlation = vec![0.0; 11];

        for i in 0..11 {
            let x = (i as f64) - (center_idx as f64) - 0.3;
            correlation[i] = 1.0 - x * x; // Peak at 0.3 offset from center
        }

        // Discrete peak should be at index 5 or 6
        let (peak_idx, _) = correlation
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
            .unwrap();

        let result = fit_peak(&correlation, peak_idx, 1000);

        // Should find the true peak around 0.3 offset from center
        // The fitted result should be close to 0.3
        assert!(
            (result.delay_samples - 0.3).abs() < 0.1,
            "Expected delay ~0.3, got {}",
            result.delay_samples
        );
        assert!(result.peak_fitted);
    }

    #[test]
    fn peak_fit_symmetric_peak() {
        // Symmetric peak at center - should return 0 offset
        let correlation = vec![0.5, 0.8, 1.0, 0.8, 0.5];
        let result = fit_peak(&correlation, 2, 1000);

        assert!(
            result.delay_samples.abs() < 0.01,
            "Expected delay ~0, got {}",
            result.delay_samples
        );
    }

    #[test]
    fn peak_fit_asymmetric_peak() {
        // Asymmetric peak - y0=0.6, y1=1.0, y2=0.8
        // a = (0.6 + 0.8)/2 - 1.0 = -0.3
        // b = (0.8 - 0.6)/2 = 0.1
        // delta = -0.1 / (2 * -0.3) = 0.1/0.6 = 0.167
        let correlation = vec![0.3, 0.6, 1.0, 0.8, 0.4];
        let result = fit_peak(&correlation, 2, 1000);

        // Peak should shift slightly right (positive delta)
        assert!(
            result.delay_samples > 0.0,
            "Expected positive offset, got {}",
            result.delay_samples
        );
        assert!(
            result.delay_samples < 0.5,
            "Expected small offset, got {}",
            result.delay_samples
        );
    }

    #[test]
    fn peak_fit_at_edge_returns_discrete() {
        let correlation = vec![1.0, 0.8, 0.5, 0.3];
        let result = fit_peak(&correlation, 0, 1000);

        // At edge, can't interpolate - should return discrete offset
        let center = correlation.len() / 2;
        let expected_offset = 0.0 - center as f64;
        assert!(
            (result.delay_samples - expected_offset).abs() < 0.01,
            "Expected discrete offset, got {}",
            result.delay_samples
        );
    }

    #[test]
    fn peak_fit_calculates_ms() {
        // At 48000 Hz, 0.5 samples = ~0.01ms
        let correlation = vec![0.5, 0.8, 1.0, 0.9, 0.6];
        let result = fit_peak(&correlation, 2, 48000);

        // Result should have delay_ms_raw calculated correctly
        let expected_ms = (result.delay_samples / 48000.0) * 1000.0;
        assert!(
            (result.delay_ms_raw - expected_ms).abs() < 0.001,
            "delay_ms_raw calculation wrong"
        );
    }

    #[test]
    fn find_and_fit_peak_works() {
        let correlation = vec![0.2, 0.5, 0.9, 1.0, 0.85, 0.4];
        let result = find_and_fit_peak(&correlation, 1000);

        // Should find peak around index 3
        assert!(result.peak_fitted);
        assert!(result.match_pct > 90.0);
    }
}
