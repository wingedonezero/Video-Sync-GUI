//! Analysis engines for delay detection

pub mod audio_corr;
pub mod videodiff;
pub mod drift_detection;
pub mod source_separation;

pub use audio_corr::{AudioCorrelator, CorrelationMethod, CorrelationResult};
