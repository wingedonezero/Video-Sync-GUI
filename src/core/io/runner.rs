//! Command runner for external process execution
//!
//! Provides streaming command execution with progress callbacks and compact logging mode.

use crate::core::models::results::{CoreError, CoreResult};
use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::mpsc::{channel, Receiver};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

/// Command output
#[derive(Debug, Clone)]
pub struct CommandOutput {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub success: bool,
}

/// Log callback type
pub type LogCallback = Arc<dyn Fn(&str) + Send + Sync>;

/// Progress callback type (progress: 0.0 to 1.0)
pub type ProgressCallback = Arc<dyn Fn(f64) + Send + Sync>;

/// Stream message from background thread
#[derive(Debug, Clone)]
enum StreamMessage {
    Stdout(String),
    Stderr(String),
    ExitCode(i32),
}

/// Command runner with logging and progress support
pub struct CommandRunner {
    /// Log callback for output
    log_callback: Option<LogCallback>,

    /// Progress callback (0.0 to 1.0)
    progress_callback: Option<ProgressCallback>,

    /// Compact mode: throttle progress lines
    compact_mode: bool,

    /// Progress step percentage (e.g., 20 = log every 20%)
    progress_step: u32,

    /// Error tail lines to capture
    error_tail_lines: usize,

    /// Tool paths override
    tool_paths: HashMap<String, PathBuf>,
}

impl CommandRunner {
    /// Create a new command runner
    pub fn new() -> Self {
        Self {
            log_callback: None,
            progress_callback: None,
            compact_mode: false,
            progress_step: 20,
            error_tail_lines: 20,
            tool_paths: HashMap::new(),
        }
    }

    /// Set log callback
    pub fn with_log_callback(mut self, callback: LogCallback) -> Self {
        self.log_callback = Some(callback);
        self
    }

    /// Set progress callback
    pub fn with_progress_callback(mut self, callback: ProgressCallback) -> Self {
        self.progress_callback = Some(callback);
        self
    }

    /// Enable compact mode (throttle progress lines)
    pub fn with_compact_mode(mut self, enabled: bool) -> Self {
        self.compact_mode = enabled;
        self
    }

    /// Set progress step percentage
    pub fn with_progress_step(mut self, step: u32) -> Self {
        self.progress_step = step;
        self
    }

    /// Set error tail lines
    pub fn with_error_tail_lines(mut self, lines: usize) -> Self {
        self.error_tail_lines = lines;
        self
    }

    /// Set tool paths
    pub fn with_tool_paths(mut self, paths: HashMap<String, PathBuf>) -> Self {
        self.tool_paths = paths;
        self
    }

    /// Log a message with timestamp
    pub fn log(&self, message: &str) {
        if let Some(callback) = &self.log_callback {
            let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
            callback(&format!("[{}] {}", timestamp, message));
        }
    }

    /// Update progress
    fn update_progress(&self, progress: f64) {
        if let Some(callback) = &self.progress_callback {
            callback(progress);
        }
    }

    /// Resolve tool path
    fn resolve_tool(&self, tool: &str) -> String {
        self.tool_paths
            .get(tool)
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| tool.to_string())
    }

    /// Run a command and return output (blocking)
    pub fn run(&self, cmd: &[&str]) -> CoreResult<CommandOutput> {
        if cmd.is_empty() {
            return Err(CoreError::CommandFailed("Empty command".to_string()));
        }

        let tool = self.resolve_tool(cmd[0]);
        self.log(&format!("Running: {} {}", tool, cmd[1..].join(" ")));

        let output = Command::new(&tool)
            .args(&cmd[1..])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .map_err(|e| {
                CoreError::CommandFailed(format!("Failed to execute {}: {}", tool, e))
            })?;

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let exit_code = output.status.code().unwrap_or(-1);
        let success = output.status.success();

        if !success {
            let error_tail = Self::get_error_tail(&stderr, self.error_tail_lines);
            self.log(&format!("Command failed with exit code {}", exit_code));
            if !error_tail.is_empty() {
                self.log(&format!("Error tail:\n{}", error_tail));
            }
        }

        Ok(CommandOutput {
            stdout,
            stderr,
            exit_code,
            success,
        })
    }

    /// Run a command with streaming output
    pub fn run_streaming(&self, cmd: &[&str]) -> CoreResult<CommandOutput> {
        if cmd.is_empty() {
            return Err(CoreError::CommandFailed("Empty command".to_string()));
        }

        let tool = self.resolve_tool(cmd[0]);
        self.log(&format!("Running: {} {}", tool, cmd[1..].join(" ")));

        let mut child = Command::new(&tool)
            .args(&cmd[1..])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| {
                CoreError::CommandFailed(format!("Failed to execute {}: {}", tool, e))
            })?;

        // Capture stdout and stderr in background threads
        let (tx, rx) = channel();

        // Spawn stdout reader
        let stdout_handle = child.stdout.take();
        let tx_stdout = tx.clone();
        let stdout_thread = thread::spawn(move || {
            if let Some(stdout) = stdout_handle {
                let reader = BufReader::new(stdout);
                for line in reader.lines() {
                    if let Ok(line) = line {
                        let _ = tx_stdout.send(StreamMessage::Stdout(line));
                    }
                }
            }
        });

        // Spawn stderr reader
        let stderr_handle = child.stderr.take();
        let tx_stderr = tx.clone();
        let stderr_thread = thread::spawn(move || {
            if let Some(stderr) = stderr_handle {
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    if let Ok(line) = line {
                        let _ = tx_stderr.send(StreamMessage::Stderr(line));
                    }
                }
            }
        });

        drop(tx); // Close sender so receiver can finish

        // Collect output with progress tracking
        let (stdout, stderr) = self.collect_streaming_output(rx);

        // Wait for child to finish
        let status = child
            .wait()
            .map_err(|e| CoreError::CommandFailed(format!("Wait failed: {}", e)))?;

        let exit_code = status.code().unwrap_or(-1);
        let success = status.success();

        // Wait for reader threads
        let _ = stdout_thread.join();
        let _ = stderr_thread.join();

        if !success {
            let error_tail = Self::get_error_tail(&stderr, self.error_tail_lines);
            self.log(&format!("Command failed with exit code {}", exit_code));
            if !error_tail.is_empty() {
                self.log(&format!("Error tail:\n{}", error_tail));
            }
        }

        Ok(CommandOutput {
            stdout,
            stderr,
            exit_code,
            success,
        })
    }

    /// Collect streaming output with compact mode throttling
    fn collect_streaming_output(&self, rx: Receiver<StreamMessage>) -> (String, String) {
        let mut stdout_lines = Vec::new();
        let mut stderr_lines = Vec::new();

        let mut last_log_time = Instant::now();
        let mut last_progress = 0;

        for msg in rx {
            match msg {
                StreamMessage::Stdout(line) => {
                    stdout_lines.push(line.clone());

                    // Try to extract progress from line
                    if let Some(progress) = Self::extract_progress(&line) {
                        self.update_progress(progress);

                        // Log progress in compact mode
                        if self.compact_mode {
                            let progress_pct = (progress * 100.0) as u32;
                            let step = self.progress_step;

                            // Log at progress steps
                            if progress_pct >= last_progress + step {
                                self.log(&format!("Progress: {}%", progress_pct));
                                last_progress = progress_pct;
                                last_log_time = Instant::now();
                            }
                        } else {
                            // Non-compact: log all progress lines
                            self.log(&line);
                        }
                    } else if !self.compact_mode {
                        // Non-compact: log everything
                        self.log(&line);
                    } else {
                        // Compact mode: throttle non-progress lines (max 1 per second)
                        if last_log_time.elapsed() > Duration::from_secs(1) {
                            self.log(&line);
                            last_log_time = Instant::now();
                        }
                    }
                }
                StreamMessage::Stderr(line) => {
                    stderr_lines.push(line.clone());
                    // Always log stderr
                    self.log(&format!("STDERR: {}", line));
                }
                StreamMessage::ExitCode(_) => {}
            }
        }

        (stdout_lines.join("\n"), stderr_lines.join("\n"))
    }

    /// Extract progress from output line (0.0 to 1.0)
    fn extract_progress(line: &str) -> Option<f64> {
        // Common progress patterns:
        // "Progress: 45%"
        // "frame= 1234 fps= 30 ..."
        // "[45.2%]"

        // Try percentage pattern
        if let Some(pos) = line.find('%') {
            let before = &line[..pos];
            if let Some(num_start) = before.rfind(|c: char| !c.is_ascii_digit() && c != '.') {
                let num_str = &before[num_start + 1..];
                if let Ok(pct) = num_str.parse::<f64>() {
                    return Some((pct / 100.0).clamp(0.0, 1.0));
                }
            }
        }

        // Try ffmpeg frame pattern
        if line.contains("frame=") && line.contains("fps=") {
            // Would need total frames to calculate percentage
            // For now, return None
        }

        None
    }

    /// Get last N lines from error output
    fn get_error_tail(stderr: &str, lines: usize) -> String {
        if lines == 0 {
            return String::new();
        }

        let all_lines: Vec<&str> = stderr.lines().collect();
        let start = all_lines.len().saturating_sub(lines);
        all_lines[start..].join("\n")
    }

    /// Check if a tool is available
    pub fn check_tool(&self, tool: &str) -> bool {
        let tool_path = self.resolve_tool(tool);
        Command::new(&tool_path)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok()
    }

    /// Get tool version
    pub fn get_tool_version(&self, tool: &str) -> CoreResult<String> {
        let output = self.run(&[tool, "--version"])?;
        if output.success {
            Ok(output.stdout.lines().next().unwrap_or("").to_string())
        } else {
            Err(CoreError::ToolNotFound(tool.to_string()))
        }
    }
}

impl Default for CommandRunner {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_progress() {
        assert_eq!(CommandRunner::extract_progress("Progress: 45%"), Some(0.45));
        assert_eq!(
            CommandRunner::extract_progress("[23.5%]"),
            Some(0.235)
        );
        assert_eq!(
            CommandRunner::extract_progress("Completed: 100%"),
            Some(1.0)
        );
        assert_eq!(CommandRunner::extract_progress("No progress here"), None);
    }

    #[test]
    fn test_get_error_tail() {
        let stderr = "line1\nline2\nline3\nline4\nline5";
        assert_eq!(
            CommandRunner::get_error_tail(stderr, 2),
            "line4\nline5"
        );
        assert_eq!(
            CommandRunner::get_error_tail(stderr, 10),
            stderr
        );
        assert_eq!(CommandRunner::get_error_tail(stderr, 0), "");
    }

    #[test]
    fn test_check_tool() {
        let runner = CommandRunner::new();
        // Most systems have 'echo'
        assert!(runner.check_tool("echo"));
    }
}
