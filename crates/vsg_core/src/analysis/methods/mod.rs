//! Correlation methods for audio sync analysis.
//!
//! This module defines the `CorrelationMethod` trait and implementations
//! for different correlation algorithms. Each method can be used
//! independently or combined with peak fitting for sub-sample accuracy.

mod gcc_phat;
mod gcc_scot;
mod scc;
mod whitened;

pub use gcc_phat::GccPhat;
pub use gcc_scot::GccScot;
pub use scc::Scc;
pub use whitened::Whitened;

use crate::analysis::types::{AnalysisResult, AudioChunk, CorrelationResult};

/// Trait for audio correlation methods.
///
/// Implementations calculate the time offset between two audio chunks
/// using cross-correlation or similar techniques.
pub trait CorrelationMethod: Send + Sync {
    /// Name of this correlation method.
    fn name(&self) -> &str;

    /// Short description of the method.
    fn description(&self) -> &str;

    /// Correlate two audio chunks and find the delay.
    ///
    /// Returns the correlation result with delay and confidence.
    /// The delay is measured as: how much to shift `other` to align with `reference`.
    /// Positive delay means `other` is ahead of `reference`.
    fn correlate(
        &self,
        reference: &AudioChunk,
        other: &AudioChunk,
    ) -> AnalysisResult<CorrelationResult>;

    /// Get the raw correlation values (for debugging/visualization).
    ///
    /// Returns the full cross-correlation array.
    fn raw_correlation(&self, reference: &AudioChunk, other: &AudioChunk)
        -> AnalysisResult<Vec<f64>>;
}

/// Factory for creating correlation methods by name.
pub fn create_method(name: &str) -> Option<Box<dyn CorrelationMethod>> {
    match name.to_lowercase().as_str() {
        "scc" | "standard" | "cross-correlation" | "standard correlation (scc)" => {
            Some(Box::new(Scc::new()))
        }
        "gcc-phat" | "phat" | "phase" | "phase correlation (gcc-phat)" => {
            Some(Box::new(GccPhat::new()))
        }
        "gcc-scot" | "scot" => Some(Box::new(GccScot::new())),
        "whitened" | "whitened cross-correlation" => Some(Box::new(Whitened::new())),
        _ => None,
    }
}

/// Get a list of available correlation method names.
pub fn available_methods() -> Vec<&'static str> {
    vec!["scc", "gcc-phat", "gcc-scot", "whitened"]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn factory_creates_scc() {
        let method = create_method("scc").unwrap();
        assert_eq!(method.name(), "SCC");
    }

    #[test]
    fn factory_creates_scc_aliases() {
        assert!(create_method("standard").is_some());
        assert!(create_method("cross-correlation").is_some());
    }

    #[test]
    fn factory_creates_gcc_phat() {
        let method = create_method("gcc-phat").unwrap();
        assert_eq!(method.name(), "GCC-PHAT");
    }

    #[test]
    fn factory_creates_gcc_scot() {
        let method = create_method("gcc-scot").unwrap();
        assert_eq!(method.name(), "GCC-SCOT");
    }

    #[test]
    fn factory_creates_whitened() {
        let method = create_method("whitened").unwrap();
        assert_eq!(method.name(), "Whitened");
    }

    #[test]
    fn factory_returns_none_for_unknown() {
        assert!(create_method("unknown").is_none());
    }
}
