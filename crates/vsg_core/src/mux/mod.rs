//! Muxing module for mkvmerge integration.
//!
//! This module handles building and executing mkvmerge commands
//! to merge tracks into output files.
//!
//! # Key Components
//!
//! - **delay_calculator**: Centralized delay calculation logic (SINGLE SOURCE OF TRUTH)
//! - **plan_builder**: Build MergePlan from ManualLayout and analysis results
//! - **options_builder**: Build mkvmerge command line options
//!
//! # Delay Calculation
//!
//! All delay math is centralized in the `delay_calculator` module. See that
//! module's documentation for the complete delay calculation rules.
//!
//! # Building a Merge Plan
//!
//! Use `plan_builder::build_merge_plan()` to create a `MergePlan` from:
//! - User-configured `ManualLayout`
//! - Calculated `Delays` from analysis
//! - `ContainerInfo` from extraction
//!
//! The plan builder handles all the delay calculations automatically.

pub mod delay_calculator;
pub mod plan_builder;
mod options_builder;

pub use delay_calculator::{
    calculate_effective_delay, calculate_global_shift, finalize_delays,
    format_delay, log_delay_calculation, DelayContext, DelayInput,
};
pub use plan_builder::{build_merge_plan, build_remux_plan, PlanBuildInput, PlanError};
pub use options_builder::{format_tokens_pretty, MkvmergeOptionsBuilder};
