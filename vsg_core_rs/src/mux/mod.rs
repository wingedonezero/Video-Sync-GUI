// vsg_core_rs/src/mux/mod.rs
//
// Mux options builder for mkvmerge command generation.

pub mod delay_calculator;
pub mod options_builder;

// Re-export main functions
pub use delay_calculator::{
    TrackType,
    calculate_track_delay,
    build_sync_token,
};

pub use options_builder::{
    build_mkvmerge_options,
    write_options_file,
};
