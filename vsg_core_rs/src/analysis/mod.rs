// src/analysis/mod.rs

pub mod correlation;
pub mod delay_selection;
pub mod drift_detection;

// Re-export commonly used types
pub use correlation::{
    ChunkResult,
    CorrelationConfig,
    CorrelationMethod,
    gcc_phat,
    scc,
    gcc_scot,
    gcc_whitened,
    run_correlation,
};

pub use delay_selection::{
    DelaySelectionMode,
    DelaySelectionConfig,
    select_final_delay,
};

pub use drift_detection::{
    AudioDiagnosis,
    SteppingDetails,
    ClusterInfo,
    QualityThresholds,
    DriftConfig,
    diagnose_audio_issue,
};
