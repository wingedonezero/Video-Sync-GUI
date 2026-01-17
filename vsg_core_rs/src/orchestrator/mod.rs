//! Orchestrator module (core shell).
//!
//! Mirrors `python/vsg_core/orchestrator/` and defines the Rust-side
//! orchestration shell. Implementations will embed Python until
//! individual steps are ported.

pub mod pipeline;
pub mod validation;
pub mod steps;
