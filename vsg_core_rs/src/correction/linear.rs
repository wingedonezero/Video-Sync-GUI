// src/correction/linear.rs
// Linear drift correction via tempo adjustment

/// Linear correction engine types
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinearCorrectionEngine {
    /// High-quality pitch-preserving time stretch using rubberband
    /// Requires FFmpeg with librubberband support
    Rubberband,

    /// High-quality resampling via rate change
    /// Uses FFmpeg's asetrate + aresample
    Aresample,

    /// Fast time stretch using FFmpeg's atempo filter
    /// Lower quality but faster processing
    Atempo,
}

impl LinearCorrectionEngine {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "rubberband" => LinearCorrectionEngine::Rubberband,
            "aresample" => LinearCorrectionEngine::Aresample,
            "atempo" => LinearCorrectionEngine::Atempo,
            _ => LinearCorrectionEngine::Aresample, // Default
        }
    }

    pub fn to_str(&self) -> &'static str {
        match self {
            LinearCorrectionEngine::Rubberband => "rubberband",
            LinearCorrectionEngine::Aresample => "aresample",
            LinearCorrectionEngine::Atempo => "atempo",
        }
    }
}

/// Configuration for rubberband engine
#[derive(Debug, Clone)]
pub struct RubberbandConfig {
    /// Apply pitch correction (default: false, pitch follows tempo)
    pub pitch_correct: bool,

    /// Transients mode: "crisp", "mixed", "smooth"
    pub transients: String,

    /// Enable smoother option
    pub smoother: bool,

    /// Enable high-quality pitch mode
    pub pitchq: bool,
}

impl Default for RubberbandConfig {
    fn default() -> Self {
        RubberbandConfig {
            pitch_correct: false,
            transients: "crisp".to_string(),
            smoother: true,
            pitchq: true,
        }
    }
}

/// Calculate tempo ratio from drift rate
///
/// CRITICAL PRESERVATION:
/// Formula: tempo_ratio = 1000.0 / (1000.0 + drift_rate_ms_s)
///
/// Examples:
/// - drift_rate_ms_s = 5.0 → tempo_ratio = 1000/1005 = 0.9950...
/// - drift_rate_ms_s = -5.0 → tempo_ratio = 1000/995 = 1.0050...
pub fn calculate_tempo_ratio(drift_rate_ms_s: f64) -> f64 {
    1000.0 / (1000.0 + drift_rate_ms_s)
}

/// Build FFmpeg filter chain for linear correction
pub fn build_filter_chain(
    engine: LinearCorrectionEngine,
    tempo_ratio: f64,
    sample_rate: u32,
    rubberband_config: &RubberbandConfig,
) -> String {
    match engine {
        LinearCorrectionEngine::Rubberband => {
            let mut opts = vec![format!("tempo={}", tempo_ratio)];

            // If not pitch correcting, pitch follows tempo
            if !rubberband_config.pitch_correct {
                opts.push(format!("pitch={}", tempo_ratio));
            }

            opts.push(format!("transients={}", rubberband_config.transients));

            if rubberband_config.smoother {
                opts.push("smoother=on".to_string());
            }

            if rubberband_config.pitchq {
                opts.push("pitchq=on".to_string());
            }

            format!("rubberband={}", opts.join(":"))
        }
        LinearCorrectionEngine::Aresample => {
            // Calculate new sample rate then resample back
            let new_sample_rate = sample_rate as f64 * tempo_ratio;
            format!("asetrate={},aresample={}", new_sample_rate, sample_rate)
        }
        LinearCorrectionEngine::Atempo => {
            format!("atempo={}", tempo_ratio)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calculate_tempo_ratio() {
        // Positive drift (audio is lagging) - need to speed up
        let ratio = calculate_tempo_ratio(5.0);
        assert!((ratio - 0.9950).abs() < 0.0001);

        // Negative drift (audio is leading) - need to slow down
        let ratio = calculate_tempo_ratio(-5.0);
        assert!((ratio - 1.0050).abs() < 0.0001);

        // No drift
        let ratio = calculate_tempo_ratio(0.0);
        assert!((ratio - 1.0).abs() < 0.0001);
    }

    #[test]
    fn test_engine_from_str() {
        assert_eq!(LinearCorrectionEngine::from_str("rubberband"), LinearCorrectionEngine::Rubberband);
        assert_eq!(LinearCorrectionEngine::from_str("aresample"), LinearCorrectionEngine::Aresample);
        assert_eq!(LinearCorrectionEngine::from_str("atempo"), LinearCorrectionEngine::Atempo);
        assert_eq!(LinearCorrectionEngine::from_str("unknown"), LinearCorrectionEngine::Aresample);
    }

    #[test]
    fn test_build_filter_chain_rubberband() {
        let config = RubberbandConfig::default();
        let filter = build_filter_chain(
            LinearCorrectionEngine::Rubberband,
            0.995,
            48000,
            &config,
        );
        assert!(filter.starts_with("rubberband="));
        assert!(filter.contains("tempo=0.995"));
        assert!(filter.contains("pitch=0.995")); // pitch_correct=false
        assert!(filter.contains("transients=crisp"));
        assert!(filter.contains("smoother=on"));
        assert!(filter.contains("pitchq=on"));
    }

    #[test]
    fn test_build_filter_chain_rubberband_pitch_correct() {
        let config = RubberbandConfig {
            pitch_correct: true,
            ..Default::default()
        };
        let filter = build_filter_chain(
            LinearCorrectionEngine::Rubberband,
            0.995,
            48000,
            &config,
        );
        // Should NOT contain pitch option when pitch_correct=true
        assert!(!filter.contains("pitch="));
    }

    #[test]
    fn test_build_filter_chain_aresample() {
        let filter = build_filter_chain(
            LinearCorrectionEngine::Aresample,
            0.995,
            48000,
            &RubberbandConfig::default(),
        );
        // New rate = 48000 * 0.995 = 47760
        assert!(filter.contains("asetrate=47760"));
        assert!(filter.contains("aresample=48000"));
    }

    #[test]
    fn test_build_filter_chain_atempo() {
        let filter = build_filter_chain(
            LinearCorrectionEngine::Atempo,
            0.995,
            48000,
            &RubberbandConfig::default(),
        );
        assert_eq!(filter, "atempo=0.995");
    }
}
