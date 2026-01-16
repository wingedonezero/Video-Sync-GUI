// vsg_core_rs/src/mux/mod.rs
//
// Mux options builder for mkvmerge command generation.

pub mod delay_calculator;

// Re-export main functions
pub use delay_calculator::{
    TrackType,
    calculate_track_delay,
    build_sync_token,
};
