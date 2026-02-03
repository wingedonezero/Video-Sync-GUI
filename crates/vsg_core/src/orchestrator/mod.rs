//! Pipeline orchestrator for coordinating job execution.
//!
//! This module provides the infrastructure for running multi-step
//! processing pipelines. Each job consists of a sequence of steps
//! that validate, execute, and record their results.
//!
//! # Architecture
//!
//! ```text
//! Pipeline
//!     ├── Step: Analyze
//!     ├── Step: Extract
//!     ├── Step: Correct
//!     ├── Step: Subtitles
//!     ├── Step: Chapters
//!     └── Step: Mux
//! ```
//!
//! # Example
//!
//! ```ignore
//! use vsg_core::orchestrator::{Pipeline, Context, JobState, PipelineStep};
//!
//! // Create pipeline with steps
//! let pipeline = Pipeline::new()
//!     .with_step(AnalyzeStep::new())
//!     .with_step(ExtractStep::new())
//!     .with_step(MuxStep::new());
//!
//! // Create context and state
//! let ctx = Context::new(job_spec, settings, "my_job", work_dir, output_dir, logger);
//! let mut state = JobState::new("job-123");
//!
//! // Run pipeline
//! let result = pipeline.run(&ctx, &mut state)?;
//! println!("Completed: {:?}", result.steps_completed);
//! ```

mod errors;
mod pipeline;
mod step;
pub mod steps;
mod types;

pub use errors::{PipelineError, PipelineResult, StepError, StepResult};
pub use pipeline::{CancelHandle, Pipeline, PipelineRunResult};
pub use step::PipelineStep;
pub use steps::{
    AnalyzeStep, AttachmentsStep, AudioCorrectionStep, ChaptersStep, ExtractStep, MuxStep,
    SubtitlesStep,
};
pub use types::{
    AnalysisOutput, ChaptersOutput, Context, CorrectionOutput, ExtractOutput, JobState, MuxOutput,
    ProgressCallback, StepOutcome, SubtitlesOutput,
};

/// Create a standard pipeline with all steps in the correct order.
///
/// The standard pipeline executes these steps:
/// 1. Analyze - correlate audio to calculate sync delays
/// 2. Extract - extract selected tracks from sources
/// 3. Attachments - extract fonts/attachments
/// 4. Chapters - extract and shift chapters
/// 5. Subtitles - process subtitle tracks (stub)
/// 6. AudioCorrection - apply audio timing adjustments (stub)
/// 7. Mux - merge everything with mkvmerge
pub fn create_standard_pipeline() -> Pipeline {
    Pipeline::new()
        .with_step(AnalyzeStep::new())
        .with_step(ExtractStep::new())
        .with_step(AttachmentsStep::new())
        .with_step(ChaptersStep::new())
        .with_step(SubtitlesStep::new())
        .with_step(AudioCorrectionStep::new())
        .with_step(MuxStep::new())
}
