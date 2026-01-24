//! Pipeline runner that executes steps in sequence.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use super::errors::{PipelineError, PipelineResult};
use super::step::PipelineStep;
use super::types::{Context, JobState, StepOutcome};

/// Pipeline that runs a sequence of steps.
///
/// The pipeline executes steps in order, running validation before
/// and after each step. It handles cancellation and tracks which
/// steps were executed.
pub struct Pipeline {
    /// Steps to execute in order.
    steps: Vec<Box<dyn PipelineStep>>,
    /// Cancellation flag.
    cancelled: Arc<AtomicBool>,
}

impl Pipeline {
    /// Create a new empty pipeline.
    pub fn new() -> Self {
        Self {
            steps: Vec::new(),
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Add a step to the pipeline.
    pub fn add_step<S: PipelineStep + 'static>(&mut self, step: S) -> &mut Self {
        self.steps.push(Box::new(step));
        self
    }

    /// Add a step (builder pattern).
    pub fn with_step<S: PipelineStep + 'static>(mut self, step: S) -> Self {
        self.add_step(step);
        self
    }

    /// Get a cancellation handle.
    ///
    /// Call `cancel()` on the returned handle to stop the pipeline
    /// at the next step boundary.
    pub fn cancel_handle(&self) -> CancelHandle {
        CancelHandle {
            flag: Arc::clone(&self.cancelled),
        }
    }

    /// Check if pipeline has been cancelled.
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }

    /// Run the pipeline with the given context and state.
    ///
    /// Executes each step in order:
    /// 1. Check for cancellation
    /// 2. Run `validate_input`
    /// 3. Run `execute`
    /// 4. Run `validate_output` (if execute returned Success)
    ///
    /// Returns the final job state on success, or a `PipelineError` on failure.
    pub fn run(&self, ctx: &Context, state: &mut JobState) -> PipelineResult<PipelineRunResult> {
        let mut result = PipelineRunResult {
            steps_completed: Vec::new(),
            steps_skipped: Vec::new(),
        };

        let total_steps = self.steps.len();

        for (i, step) in self.steps.iter().enumerate() {
            // Check for cancellation
            if self.is_cancelled() {
                ctx.logger.warn(&format!(
                    "Pipeline cancelled before step '{}'",
                    step.name()
                ));
                return Err(PipelineError::cancelled(&ctx.job_name));
            }

            let step_name = step.name();
            ctx.logger.phase(step_name);

            // Report progress
            let percent = ((i as f64 / total_steps as f64) * 100.0) as u32;
            ctx.report_progress(step_name, percent, &format!("Starting {}", step_name));

            // Validate input
            ctx.logger.debug(&format!("Validating input for '{}'", step_name));
            if let Err(e) = step.validate_input(ctx) {
                ctx.logger.error(&format!("Input validation failed: {}", e));
                return Err(PipelineError::step_failed(&ctx.job_name, step_name, e));
            }

            // Execute
            ctx.logger.debug(&format!("Executing '{}'", step_name));
            let outcome = step.execute(ctx, state).map_err(|e| {
                ctx.logger.error(&format!("Execution failed: {}", e));
                PipelineError::step_failed(&ctx.job_name, step_name, e)
            })?;

            match outcome {
                StepOutcome::Success => {
                    // Validate output
                    ctx.logger
                        .debug(&format!("Validating output for '{}'", step_name));
                    if let Err(e) = step.validate_output(ctx, state) {
                        ctx.logger.error(&format!("Output validation failed: {}", e));
                        return Err(PipelineError::step_failed(&ctx.job_name, step_name, e));
                    }

                    ctx.logger.success(&format!("{} completed", step_name));
                    result.steps_completed.push(step_name.to_string());
                }
                StepOutcome::Skipped(reason) => {
                    ctx.logger
                        .info(&format!("{} skipped: {}", step_name, reason));
                    result.steps_skipped.push(step_name.to_string());
                }
            }
        }

        // Final progress
        ctx.report_progress("Complete", 100, "Pipeline finished");
        ctx.logger.success("Pipeline completed successfully");

        Ok(result)
    }

    /// Get the number of steps in the pipeline.
    pub fn step_count(&self) -> usize {
        self.steps.len()
    }

    /// Get step names in order.
    pub fn step_names(&self) -> Vec<&str> {
        self.steps.iter().map(|s| s.name()).collect()
    }
}

impl Default for Pipeline {
    fn default() -> Self {
        Self::new()
    }
}

/// Handle for cancelling a running pipeline.
#[derive(Clone)]
pub struct CancelHandle {
    flag: Arc<AtomicBool>,
}

impl CancelHandle {
    /// Cancel the pipeline.
    ///
    /// The pipeline will stop at the next step boundary.
    pub fn cancel(&self) {
        self.flag.store(true, Ordering::SeqCst);
    }

    /// Check if cancellation has been requested.
    pub fn is_cancelled(&self) -> bool {
        self.flag.load(Ordering::SeqCst)
    }
}

/// Result of a pipeline run.
#[derive(Debug, Clone)]
pub struct PipelineRunResult {
    /// Steps that completed successfully.
    pub steps_completed: Vec<String>,
    /// Steps that were skipped.
    pub steps_skipped: Vec<String>,
}

impl PipelineRunResult {
    /// Check if all steps completed (none skipped).
    pub fn all_completed(&self) -> bool {
        self.steps_skipped.is_empty()
    }

    /// Total number of steps that ran.
    pub fn total_steps(&self) -> usize {
        self.steps_completed.len() + self.steps_skipped.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::orchestrator::errors::StepError;
    use std::sync::atomic::AtomicUsize;

    // Mock step for testing
    struct CountingStep {
        name: &'static str,
        execute_count: Arc<AtomicUsize>,
    }

    impl PipelineStep for CountingStep {
        fn name(&self) -> &str {
            self.name
        }

        fn validate_input(&self, _ctx: &Context) -> Result<(), StepError> {
            Ok(())
        }

        fn execute(&self, _ctx: &Context, _state: &mut JobState) -> Result<StepOutcome, StepError> {
            self.execute_count.fetch_add(1, Ordering::SeqCst);
            Ok(StepOutcome::Success)
        }

        fn validate_output(&self, _ctx: &Context, _state: &JobState) -> Result<(), StepError> {
            Ok(())
        }
    }

    #[test]
    fn pipeline_builds_correctly() {
        let pipeline = Pipeline::new()
            .with_step(CountingStep {
                name: "Step1",
                execute_count: Arc::new(AtomicUsize::new(0)),
            })
            .with_step(CountingStep {
                name: "Step2",
                execute_count: Arc::new(AtomicUsize::new(0)),
            });

        assert_eq!(pipeline.step_count(), 2);
        assert_eq!(pipeline.step_names(), vec!["Step1", "Step2"]);
    }

    #[test]
    fn cancel_handle_works() {
        let pipeline = Pipeline::new();
        let handle = pipeline.cancel_handle();

        assert!(!pipeline.is_cancelled());
        assert!(!handle.is_cancelled());

        handle.cancel();

        assert!(pipeline.is_cancelled());
        assert!(handle.is_cancelled());
    }
}
