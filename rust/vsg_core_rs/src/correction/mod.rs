// src/correction/mod.rs

pub mod edl;
pub mod linear;
pub mod pal;
pub mod utils;

// Re-export commonly used types
pub use edl::{
    AudioSegment,
    generate_edl_from_correlation,
};

pub use linear::{
    LinearCorrectionEngine,
    calculate_tempo_ratio,
};

pub use pal::{
    PAL_TEMPO_RATIO,
};

pub use utils::{
    align_buffer,
    is_silence,
    calculate_std_i32,
    calculate_std_f64,
};
