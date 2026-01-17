// vsg_core_rs/src/chapters/mod.rs
//
// Chapter processing with nanosecond-precision timestamps.

pub mod timestamps;

// Re-export main functions
pub use timestamps::{
    ms_to_ns,
    ns_to_ms,
    shift_timestamp_ns,
    format_ns,
    parse_ns,
};
