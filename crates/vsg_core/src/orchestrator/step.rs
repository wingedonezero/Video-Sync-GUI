//! Pipeline step trait definition.
//!
//! All pipeline steps implement this trait, providing a consistent
//! interface for validation and execution.

use super::errors::StepResult;
use super::types::{Context, JobState, StepOutcome};

/// Trait for pipeline steps.
///
/// Each step in the pipeline implements this trait. The pipeline runner
/// calls these methods in order:
///
/// 1. `validate_input` - Check preconditions before execution
/// 2. `execute` - Perform the step's work
/// 3. `validate_output` - Verify the step produced valid output
///
/// # Example
///
/// ```ignore
/// struct AnalyzeStep;
///
/// impl PipelineStep for AnalyzeStep {
///     fn name(&self) -> &str { "Analyze" }
///
///     fn validate_input(&self, ctx: &Context) -> StepResult<()> {
///         // Check that source files exist
///         if ctx.primary_source().is_none() {
///             return Err(StepError::invalid_input("No primary source"));
///         }
///         Ok(())
///     }
///
///     fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
///         // Perform analysis...
///         state.analysis = Some(AnalysisOutput { ... });
///         Ok(StepOutcome::Success)
///     }
///
///     fn validate_output(&self, _ctx: &Context, state: &JobState) -> StepResult<()> {
///         if !state.has_analysis() {
///             return Err(StepError::invalid_output("Analysis not recorded"));
///         }
///         Ok(())
///     }
/// }
/// ```
pub trait PipelineStep: Send + Sync {
    /// Get the step name (for logging and error context).
    fn name(&self) -> &str;

    /// Validate inputs before execution.
    ///
    /// Called before `execute`. Should check that all required
    /// preconditions are met (files exist, previous steps completed, etc.).
    ///
    /// Return `Ok(())` if validation passes, or `Err(StepError)` if not.
    fn validate_input(&self, ctx: &Context) -> StepResult<()>;

    /// Execute the step's main work.
    ///
    /// Should perform the step's processing and record results in `state`.
    /// Use `ctx.logger` for logging and `ctx.report_progress()` for progress.
    ///
    /// Returns `StepOutcome::Success` on completion, or `StepOutcome::Skipped`
    /// if the step determined it should be skipped (not an error).
    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome>;

    /// Validate outputs after execution.
    ///
    /// Called after `execute` returns `Success`. Should verify that
    /// the step produced valid output (files exist, state populated, etc.).
    ///
    /// Return `Ok(())` if validation passes, or `Err(StepError)` if not.
    fn validate_output(&self, ctx: &Context, state: &JobState) -> StepResult<()>;

    /// Whether this step can be skipped.
    ///
    /// Some steps are optional based on job configuration.
    /// Default is `false` (step is required).
    fn is_optional(&self) -> bool {
        false
    }

    /// Human-readable description of what this step does.
    fn description(&self) -> &str {
        self.name()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockStep {
        name: &'static str,
        should_skip: bool,
    }

    impl PipelineStep for MockStep {
        fn name(&self) -> &str {
            self.name
        }

        fn validate_input(&self, _ctx: &Context) -> StepResult<()> {
            Ok(())
        }

        fn execute(&self, _ctx: &Context, _state: &mut JobState) -> StepResult<StepOutcome> {
            if self.should_skip {
                Ok(StepOutcome::Skipped("Test skip".to_string()))
            } else {
                Ok(StepOutcome::Success)
            }
        }

        fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
            Ok(())
        }
    }

    #[test]
    fn step_trait_object_works() {
        let step: Box<dyn PipelineStep> = Box::new(MockStep {
            name: "TestStep",
            should_skip: false,
        });

        assert_eq!(step.name(), "TestStep");
        assert!(!step.is_optional());
    }
}
