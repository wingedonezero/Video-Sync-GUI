//! Sync executor component core.
//!
//! Rust-first placeholder for merge execution. This will be replaced with native
//! mkvmerge orchestration or Python dependency calls where required.

use std::fs;
use std::path::Path;

pub struct SyncExecutor;

impl SyncExecutor {
    pub fn execute_merge(temp_output_path: &Path) -> std::io::Result<bool> {
        if let Some(parent) = temp_output_path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(temp_output_path, b"")?;
        Ok(true)
    }

    pub fn finalize_output(temp_output_path: &Path, final_output_path: &Path) -> std::io::Result<()> {
        if let Some(parent) = final_output_path.parent() {
            fs::create_dir_all(parent)?;
        }
        if temp_output_path.exists() {
            fs::rename(temp_output_path, final_output_path)?;
        } else {
            fs::write(final_output_path, b"")?;
        }
        Ok(())
    }
}
