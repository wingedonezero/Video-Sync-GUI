//! Per-job logger with file and callback output.
//!
//! Each job gets its own logger that:
//! - Writes to a dedicated log file
//! - Sends messages to GUI callback (if provided)
//! - Supports compact mode with progress filtering
//! - Maintains a tail buffer for error diagnosis

use std::collections::VecDeque;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use chrono::Local;
use parking_lot::Mutex;

use super::types::{GuiLogCallback, LogConfig, LogLevel, MessagePrefix};

/// Per-job logger with dual output (file + GUI).
pub struct JobLogger {
    /// Job name for identification.
    job_name: String,
    /// Path to log file.
    log_path: PathBuf,
    /// File writer (buffered).
    file_writer: Arc<Mutex<Option<BufWriter<File>>>>,
    /// GUI callback for sending messages.
    gui_callback: Arc<Mutex<Option<GuiLogCallback>>>,
    /// Logging configuration.
    config: LogConfig,
    /// Tail buffer for recent lines (used for error diagnosis).
    tail_buffer: Arc<Mutex<VecDeque<String>>>,
    /// Last progress value logged (for compact mode filtering).
    last_progress: Arc<Mutex<u32>>,
}

impl JobLogger {
    /// Create a new job logger.
    ///
    /// # Arguments
    /// * `job_name` - Name of the job (used in log filename)
    /// * `log_dir` - Directory to write log file to
    /// * `config` - Logging configuration
    /// * `gui_callback` - Optional callback for GUI output
    pub fn new(
        job_name: impl Into<String>,
        log_dir: impl AsRef<Path>,
        config: LogConfig,
        gui_callback: Option<GuiLogCallback>,
    ) -> std::io::Result<Self> {
        let job_name = job_name.into();
        let log_dir = log_dir.as_ref();

        // Ensure log directory exists
        fs::create_dir_all(log_dir)?;

        // Create log file path
        let log_path = log_dir.join(format!("{}.log", sanitize_filename(&job_name)));

        // Open log file
        let file = File::create(&log_path)?;
        let file_writer = BufWriter::new(file);

        Ok(Self {
            job_name,
            log_path,
            file_writer: Arc::new(Mutex::new(Some(file_writer))),
            gui_callback: Arc::new(Mutex::new(gui_callback)),
            config,
            tail_buffer: Arc::new(Mutex::new(VecDeque::with_capacity(100))),
            last_progress: Arc::new(Mutex::new(0)),
        })
    }

    /// Get the job name.
    pub fn job_name(&self) -> &str {
        &self.job_name
    }

    /// Get the log file path.
    pub fn log_path(&self) -> &Path {
        &self.log_path
    }

    /// Log a message at the specified level.
    pub fn log(&self, level: LogLevel, message: &str) {
        if level < self.config.level {
            return;
        }

        let formatted = self.format_message(message);
        self.output(&formatted);
    }

    /// Log an info message.
    pub fn info(&self, message: &str) {
        self.log(LogLevel::Info, message);
    }

    /// Log a debug message.
    pub fn debug(&self, message: &str) {
        self.log(LogLevel::Debug, message);
    }

    /// Log a warning message.
    pub fn warn(&self, message: &str) {
        let msg = MessagePrefix::Warning.format(message);
        self.log(LogLevel::Warn, &msg);
    }

    /// Log an error message.
    pub fn error(&self, message: &str) {
        let msg = MessagePrefix::Error.format(message);
        self.log(LogLevel::Error, &msg);
    }

    /// Log a command being executed.
    pub fn command(&self, command: &str) {
        let msg = MessagePrefix::Command.format(command);
        self.log(LogLevel::Info, &msg);
    }

    /// Log a phase marker.
    pub fn phase(&self, phase_name: &str) {
        let msg = MessagePrefix::Phase.format(phase_name);
        self.log(LogLevel::Info, &msg);
    }

    /// Log a section marker.
    pub fn section(&self, section_name: &str) {
        let msg = MessagePrefix::Section.format(section_name);
        self.log(LogLevel::Info, &msg);
    }

    /// Log a success message.
    pub fn success(&self, message: &str) {
        let msg = MessagePrefix::Success.format(message);
        self.log(LogLevel::Info, &msg);
    }

    /// Log a validation message.
    pub fn validation(&self, message: &str) {
        let msg = MessagePrefix::Validation.format(message);
        self.log(LogLevel::Info, &msg);
    }

    /// Log progress update (filtered in compact mode).
    ///
    /// Returns true if the progress was logged, false if filtered.
    pub fn progress(&self, percent: u32) -> bool {
        if self.config.compact {
            let mut last = self.last_progress.lock();
            let step = self.config.progress_step;

            // Only log at step intervals (e.g., 0%, 20%, 40%, ...)
            let current_step = (percent / step) * step;
            let last_step = (*last / step) * step;

            if current_step <= last_step && percent < 100 {
                return false;
            }
            *last = percent;
        }

        let msg = format!("Progress: {}%", percent);
        self.log(LogLevel::Info, &msg);
        true
    }

    /// Log command output line (for stdout/stderr from external tools).
    ///
    /// In compact mode, these are only added to tail buffer.
    pub fn output_line(&self, line: &str, is_stderr: bool) {
        // Always add to tail buffer
        {
            let mut buffer = self.tail_buffer.lock();
            if buffer.len() >= self.config.error_tail {
                buffer.pop_front();
            }
            buffer.push_back(line.to_string());
        }

        // In compact mode, don't output every line
        if self.config.compact {
            return;
        }

        let prefix = if is_stderr { "[stderr] " } else { "" };
        let msg = format!("{}{}", prefix, line);
        self.output(&self.format_message(&msg));
    }

    /// Show the tail buffer (typically after an error).
    pub fn show_tail(&self, header: &str) {
        let buffer = self.tail_buffer.lock();
        if buffer.is_empty() {
            return;
        }

        self.output(&self.format_message(&format!("[{}/tail]", header)));
        for line in buffer.iter() {
            self.output(&self.format_message(line));
        }
    }

    /// Clear the tail buffer.
    pub fn clear_tail(&self) {
        self.tail_buffer.lock().clear();
    }

    /// Get the current tail buffer contents.
    pub fn get_tail(&self) -> Vec<String> {
        self.tail_buffer.lock().iter().cloned().collect()
    }

    /// Format mkvmerge options in pretty format.
    pub fn log_mkvmerge_options_pretty(&self, tokens: &[String]) {
        self.info("--- mkvmerge options (pretty) ---");
        let formatted = tokens.join(" \\\n  ");
        self.info(&formatted);
        self.info("---------------------------------");
    }

    /// Format mkvmerge options as JSON.
    pub fn log_mkvmerge_options_json(&self, tokens: &[String]) {
        self.info("--- mkvmerge options (json) ---");
        if let Ok(json) = serde_json::to_string_pretty(tokens) {
            self.info(&json);
        }
        self.info("-------------------------------");
    }

    /// Flush the log file.
    pub fn flush(&self) {
        if let Some(ref mut writer) = *self.file_writer.lock() {
            let _ = writer.flush();
        }
    }

    /// Close the logger and release resources.
    pub fn close(&self) {
        self.flush();
        *self.file_writer.lock() = None;
    }

    /// Format a message with timestamp (if enabled).
    fn format_message(&self, message: &str) -> String {
        if self.config.show_timestamps {
            let timestamp = Local::now().format("%H:%M:%S");
            format!("[{}] {}", timestamp, message)
        } else {
            message.to_string()
        }
    }

    /// Output a formatted message to file and GUI.
    fn output(&self, formatted: &str) {
        // Write to file
        if let Some(ref mut writer) = *self.file_writer.lock() {
            let _ = writeln!(writer, "{}", formatted);
        }

        // Send to GUI callback
        if let Some(ref callback) = *self.gui_callback.lock() {
            callback(formatted);
        }
    }
}

impl Drop for JobLogger {
    fn drop(&mut self) {
        self.close();
    }
}

/// Sanitize a string to be safe for use as a filename.
fn sanitize_filename(name: &str) -> String {
    name.chars()
        .map(|c| match c {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            _ => c,
        })
        .collect()
}

/// Builder for creating JobLogger with fluent API.
pub struct JobLoggerBuilder {
    job_name: String,
    log_dir: PathBuf,
    config: LogConfig,
    gui_callback: Option<GuiLogCallback>,
}

impl JobLoggerBuilder {
    /// Create a new builder.
    pub fn new(job_name: impl Into<String>, log_dir: impl Into<PathBuf>) -> Self {
        Self {
            job_name: job_name.into(),
            log_dir: log_dir.into(),
            config: LogConfig::default(),
            gui_callback: None,
        }
    }

    /// Set the logging configuration.
    pub fn config(mut self, config: LogConfig) -> Self {
        self.config = config;
        self
    }

    /// Set the log level.
    pub fn level(mut self, level: LogLevel) -> Self {
        self.config.level = level;
        self
    }

    /// Enable or disable compact mode.
    pub fn compact(mut self, compact: bool) -> Self {
        self.config.compact = compact;
        self
    }

    /// Set the progress step percentage.
    pub fn progress_step(mut self, step: u32) -> Self {
        self.config.progress_step = step;
        self
    }

    /// Set the GUI callback.
    pub fn gui_callback(mut self, callback: GuiLogCallback) -> Self {
        self.gui_callback = Some(callback);
        self
    }

    /// Build the JobLogger.
    pub fn build(self) -> std::io::Result<JobLogger> {
        JobLogger::new(self.job_name, self.log_dir, self.config, self.gui_callback)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tempfile::tempdir;

    #[test]
    fn creates_log_file() {
        let dir = tempdir().unwrap();
        let logger = JobLogger::new("test_job", dir.path(), LogConfig::default(), None).unwrap();

        assert!(logger.log_path().exists());
        assert!(logger.log_path().to_string_lossy().contains("test_job.log"));
    }

    #[test]
    fn writes_to_file() {
        let dir = tempdir().unwrap();
        let logger = JobLogger::new("test_job", dir.path(), LogConfig::default(), None).unwrap();

        logger.info("Test message");
        logger.flush();

        let content = fs::read_to_string(logger.log_path()).unwrap();
        assert!(content.contains("Test message"));
    }

    #[test]
    fn calls_gui_callback() {
        let dir = tempdir().unwrap();
        let call_count = Arc::new(AtomicUsize::new(0));
        let count_clone = call_count.clone();

        let callback: GuiLogCallback = Box::new(move |_msg| {
            count_clone.fetch_add(1, Ordering::SeqCst);
        });

        let logger =
            JobLogger::new("test_job", dir.path(), LogConfig::default(), Some(callback)).unwrap();

        logger.info("Message 1");
        logger.info("Message 2");

        assert_eq!(call_count.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn compact_mode_filters_progress() {
        let dir = tempdir().unwrap();
        let mut config = LogConfig::default();
        config.compact = true;
        config.progress_step = 20;

        let logger = JobLogger::new("test_job", dir.path(), config, None).unwrap();

        // These should be filtered (not at 20% intervals)
        assert!(!logger.progress(5));
        assert!(!logger.progress(10));
        assert!(!logger.progress(15));

        // This should pass (at 20% interval)
        assert!(logger.progress(20));

        // This should be filtered
        assert!(!logger.progress(25));

        // This should pass
        assert!(logger.progress(40));
    }

    #[test]
    fn tail_buffer_maintains_limit() {
        let dir = tempdir().unwrap();
        let mut config = LogConfig::default();
        config.compact = true;
        config.error_tail = 5;

        let logger = JobLogger::new("test_job", dir.path(), config, None).unwrap();

        for i in 0..10 {
            logger.output_line(&format!("Line {}", i), false);
        }

        let tail = logger.get_tail();
        assert_eq!(tail.len(), 5);
        assert_eq!(tail[0], "Line 5");
        assert_eq!(tail[4], "Line 9");
    }

    #[test]
    fn sanitizes_filename() {
        assert_eq!(sanitize_filename("normal_name"), "normal_name");
        assert_eq!(sanitize_filename("has/slash"), "has_slash");
        assert_eq!(sanitize_filename("has:colon"), "has_colon");
        assert_eq!(sanitize_filename("a<b>c"), "a_b_c");
    }
}
