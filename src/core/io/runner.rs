//! Command runner for external process execution

use crate::core::models::results::{CoreError, CoreResult};
use std::collections::HashMap;
use std::path::PathBuf;
use std::process::{Command, Stdio};

/// Command output
pub struct CommandOutput {
    pub stdout: String,
    pub stderr: String,
    pub success: bool,
}

/// Command runner
pub struct CommandRunner {
    // TODO: Add log callback and configuration
}

impl CommandRunner {
    pub fn new() -> Self {
        Self {}
    }

    /// Run a command and return output
    pub fn run(
        &self,
        cmd: &[&str],
        _tool_paths: &HashMap<String, Option<PathBuf>>,
    ) -> CoreResult<CommandOutput> {
        if cmd.is_empty() {
            return Err(CoreError::CommandFailed("Empty command".to_string()));
        }

        let output = Command::new(cmd[0])
            .args(&cmd[1..])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()?;

        Ok(CommandOutput {
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
            success: output.status.success(),
        })
    }
}

impl Default for CommandRunner {
    fn default() -> Self {
        Self::new()
    }
}
