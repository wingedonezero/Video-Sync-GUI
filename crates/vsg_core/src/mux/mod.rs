//! Muxing module for mkvmerge integration.
//!
//! This module handles building and executing mkvmerge commands
//! to merge tracks into output files.
//!
//! # Architecture
//!
//! - **plan_builder**: Builds a `MergePlan` from job inputs (layout, sources, delays)
//! - **options_builder**: Converts a `MergePlan` into mkvmerge command tokens

mod options_builder;
mod plan_builder;

pub use options_builder::{format_tokens_pretty, MkvmergeOptionsBuilder};
pub use plan_builder::{build_merge_plan, MergePlanInput, MuxError};
