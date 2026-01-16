// src/analysis/mod.rs

pub mod correlation;
pub mod delay_selection;

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
