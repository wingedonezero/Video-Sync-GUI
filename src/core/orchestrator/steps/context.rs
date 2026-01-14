//! Pipeline context
//!
//! The Context struct carries all state between pipeline steps.

use crate::core::models::jobs::{Delays, PlanItem};
use crate::core::models::settings::AppSettings;
use serde_json::Value;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

/// Log callback type
pub type LogCallback = Arc<dyn Fn(&str) + Send + Sync>;

/// Progress callback type (0.0 to 1.0)
pub type ProgressCallback = Arc<dyn Fn(f64) + Send + Sync>;

/// Audio segment for stepping correction EDL
#[derive(Debug, Clone)]
pub struct AudioSegment {
    pub start_ms: i64,
    pub end_ms: i64,
    pub source_start_ms: i64,
}

/// Pipeline context - carries all state between steps
pub struct Context {
    // Configuration
    pub settings: AppSettings,
    pub settings_dict: HashMap<String, Value>,
    pub tool_paths: HashMap<String, Option<PathBuf>>,

    // Callbacks
    pub log: LogCallback,
    pub progress: ProgressCallback,

    // Paths
    pub output_dir: PathBuf,
    pub temp_dir: PathBuf,

    // Input specification
    pub sources: HashMap<String, PathBuf>,
    pub and_merge: bool,
    pub manual_layout: Vec<HashMap<String, Value>>,
    pub attachment_sources: Vec<String>,

    // Results from analysis step
    pub delays: Option<Delays>,

    // Results from extraction step
    pub extracted_items: Option<Vec<PlanItem>>,
    pub chapters_xml: Option<PathBuf>,
    pub attachments: Option<Vec<PathBuf>>,

    // Correction flags
    pub segment_flags: HashMap<String, HashMap<String, Value>>,
    pub pal_drift_flags: HashMap<String, HashMap<String, Value>>,
    pub linear_drift_flags: HashMap<String, HashMap<String, Value>>,

    // Container delays
    pub source1_audio_container_delay_ms: i64,
    pub container_delays: HashMap<String, HashMap<i32, i64>>,

    // Global shift
    pub global_shift_is_required: bool,

    // Sync configuration
    pub sync_mode: String,

    // Stepping correction
    pub stepping_sources: Vec<String>,
    pub stepping_detected_disabled: Vec<String>,
    pub stepping_edls: HashMap<String, Vec<AudioSegment>>,

    // Correlation settings
    pub correlation_snap_no_scenes_fallback: bool,

    // Output
    pub out_file: Option<PathBuf>,
    pub tokens: Option<Vec<String>>,
}

impl Context {
    /// Create a new context with minimal required fields
    pub fn new(
        settings: AppSettings,
        output_dir: PathBuf,
        temp_dir: PathBuf,
        sources: HashMap<String, PathBuf>,
        log: LogCallback,
        progress: ProgressCallback,
    ) -> Self {
        Self {
            settings_dict: HashMap::new(),
            tool_paths: HashMap::new(),
            settings,
            log,
            progress,
            output_dir,
            temp_dir,
            sources,
            and_merge: false,
            manual_layout: Vec::new(),
            attachment_sources: Vec::new(),
            delays: None,
            extracted_items: None,
            chapters_xml: None,
            attachments: None,
            segment_flags: HashMap::new(),
            pal_drift_flags: HashMap::new(),
            linear_drift_flags: HashMap::new(),
            source1_audio_container_delay_ms: 0,
            container_delays: HashMap::new(),
            global_shift_is_required: false,
            sync_mode: "time_based".to_string(),
            stepping_sources: Vec::new(),
            stepping_detected_disabled: Vec::new(),
            stepping_edls: HashMap::new(),
            correlation_snap_no_scenes_fallback: false,
            out_file: None,
            tokens: None,
        }
    }

    /// Log a message
    pub fn log(&self, message: &str) {
        (self.log)(message);
    }

    /// Update progress (0.0 to 1.0)
    pub fn update_progress(&self, progress: f64) {
        (self.progress)(progress);
    }
}
