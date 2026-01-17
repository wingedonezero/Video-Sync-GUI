//! Output writer component core.
//!
//! Rust-first placeholder for output path handling and mkvmerge option file writing.

use std::path::{Path, PathBuf};

use serde_json;

pub struct OutputWriter;

impl OutputWriter {
    pub fn write_mkvmerge_options(tokens: &[String], temp_dir: &Path) -> std::io::Result<PathBuf> {
        let options_path = temp_dir.join("mkvmerge_options.json");
        let json = serde_json::json!({ "tokens": tokens });
        std::fs::write(&options_path, serde_json::to_string_pretty(&json).unwrap_or_default())?;
        Ok(options_path)
    }

    pub fn prepare_output_path(output_dir: &Path, source1_filename: &str) -> PathBuf {
        output_dir.join(format!("{source1_filename}_synced.mkv"))
    }
}
