// src/correction/pal.rs
// PAL speed-up correction (25fps → 23.976fps)

use super::linear::RubberbandConfig;

/// CRITICAL: Exact PAL tempo ratio
/// Converts 25fps PAL to 23.976fps (24000/1001) NTSC film rate
/// Formula: (24000/1001) / 25.0 = 0.95904...
pub const PAL_TEMPO_RATIO: f64 = (24000.0 / 1001.0) / 25.0;

/// Expected PAL drift rate in ms/s
/// Formula: (25/23.976 - 1) * 1000 ≈ 40.9 ms/s
pub const PAL_DRIFT_RATE_MS_S: f64 = 40.9;

/// Build FFmpeg filter chain for PAL correction
/// Always uses rubberband with pitch correction (preserves original pitch)
pub fn build_pal_filter_chain() -> String {
    format!("rubberband=tempo={}", PAL_TEMPO_RATIO)
}

/// Build FFmpeg filter chain for PAL correction with custom config
pub fn build_pal_filter_chain_with_config(config: &RubberbandConfig) -> String {
    let mut opts = vec![format!("tempo={}", PAL_TEMPO_RATIO)];

    // For PAL, typically we want pitch correction ON (preserve original pitch)
    // so we DON'T add the pitch parameter

    opts.push(format!("transients={}", config.transients));

    if config.smoother {
        opts.push("smoother=on".to_string());
    }

    if config.pitchq {
        opts.push("pitchq=on".to_string());
    }

    format!("rubberband={}", opts.join(":"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pal_tempo_ratio() {
        // Verify the exact PAL tempo ratio
        let expected = (24000.0 / 1001.0) / 25.0;
        assert_eq!(PAL_TEMPO_RATIO, expected);

        // Should be approximately 0.95904
        assert!((PAL_TEMPO_RATIO - 0.95904).abs() < 0.00001);
    }

    #[test]
    fn test_pal_drift_rate() {
        // Verify PAL drift rate matches expected value
        // PAL speedup: 23.976fps → 25fps causes audio to drift
        // Drift rate = (1 - 23.976/25) * 1000 ≈ 40.96 ms/s
        let actual_drift = (1.0 - (24000.0 / 1001.0) / 25.0) * 1000.0;
        // The constant is 40.9 for readability, actual is ~40.96
        // This matches the Python code and migration plan
        assert!((actual_drift - 40.96_f64).abs() < 0.1);
        // Our constant should be close (within tolerance used in detection)
        assert!((PAL_DRIFT_RATE_MS_S - actual_drift).abs() < 1.0);
    }

    #[test]
    fn test_build_pal_filter_chain() {
        let filter = build_pal_filter_chain();
        assert!(filter.starts_with("rubberband=tempo="));
        assert!(filter.contains(&format!("{}", PAL_TEMPO_RATIO)));
    }

    #[test]
    fn test_build_pal_filter_chain_with_config() {
        let config = RubberbandConfig {
            pitch_correct: true, // For PAL, we want pitch correction
            transients: "smooth".to_string(),
            smoother: false,
            pitchq: true,
        };
        let filter = build_pal_filter_chain_with_config(&config);

        assert!(filter.contains(&format!("tempo={}", PAL_TEMPO_RATIO)));
        assert!(filter.contains("transients=smooth"));
        assert!(!filter.contains("smoother")); // smoother=false
        assert!(filter.contains("pitchq=on"));
        // Should NOT contain pitch parameter (pitch_correct defaults to ON for PAL)
    }
}
