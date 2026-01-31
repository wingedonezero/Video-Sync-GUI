//! Muxing module for mkvmerge integration.
//!
//! This module handles building and executing mkvmerge commands
//! to merge tracks into output files.

mod options_builder;

pub use options_builder::{format_tokens_pretty, MkvmergeOptionsBuilder};
