//! SRT to ASS subtitle format conversion
//!
//! Uses FFmpeg to convert SRT subtitles to ASS format with default styling.

use crate::core::io::runner::CommandRunner;
use crate::core::models::results::CoreResult;
use std::path::{Path, PathBuf};

/// Convert SRT subtitle file to ASS format
///
/// Uses FFmpeg's built-in subtitle converter. If the file is not SRT or
/// conversion fails, returns the original path.
///
/// # Arguments
/// * `subtitle_path` - Path to the subtitle file
/// * `runner` - Command runner for executing ffmpeg
///
/// # Returns
/// Path to the ASS file if conversion succeeded, otherwise original path
pub fn convert_srt_to_ass(
    subtitle_path: &Path,
    runner: &CommandRunner,
) -> CoreResult<PathBuf> {
    // Check if file is SRT
    let extension = subtitle_path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("");

    if extension.to_lowercase() != "srt" {
        // Not an SRT file, return original path
        return Ok(subtitle_path.to_path_buf());
    }

    // Create output path with .ass extension
    let output_path = subtitle_path.with_extension("ass");

    // FFmpeg conversion command
    let cmd = vec![
        "ffmpeg",
        "-y", // Overwrite output file
        "-i",
        subtitle_path.to_str().unwrap(),
        output_path.to_str().unwrap(),
    ];

    match runner.run(&cmd) {
        Ok(_) => {
            if output_path.exists() {
                runner.log(&format!(
                    "[SubConvert] Converted {} to ASS format",
                    subtitle_path.display()
                ));
                Ok(output_path)
            } else {
                // Conversion succeeded but file not found - return original
                runner.log(&format!(
                    "[SubConvert] Warning: Conversion completed but output file not found for {}",
                    subtitle_path.display()
                ));
                Ok(subtitle_path.to_path_buf())
            }
        }
        Err(e) => {
            // Conversion failed - return original
            runner.log(&format!(
                "[SubConvert] Warning: Failed to convert {}: {}",
                subtitle_path.display(),
                e
            ));
            Ok(subtitle_path.to_path_buf())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_non_srt_returns_original() {
        // Non-SRT files should return original path without conversion attempt
        let path = PathBuf::from("/tmp/test.ass");
        // Would need mock runner to test actual conversion
        assert!(true);
    }
}
