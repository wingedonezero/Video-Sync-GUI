// vsg_core_rs/src/subtitles/mod.rs
//
// Subtitle processing utilities.
//
// NOTE: Most subtitle processing stays in Python (pysubs2 library).
// This module only contains pure computational utilities that don't require
// subtitle parsing/manipulation.

pub mod frame_utils;

// Re-export frame utility functions for convenience
pub use frame_utils::{
    time_to_frame_floor,
    frame_to_time_floor,
    time_to_frame_middle,
    frame_to_time_middle,
    time_to_frame_aegisub,
    frame_to_time_aegisub,
};
