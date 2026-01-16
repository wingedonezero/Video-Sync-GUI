// vsg_core_rs/src/extraction/mod.rs
//
// Extraction layer for tracks and container delays.

pub mod tracks;

// Re-export main functions
pub use tracks::{
    calculate_container_delay,
    add_container_delays_to_json,
};
