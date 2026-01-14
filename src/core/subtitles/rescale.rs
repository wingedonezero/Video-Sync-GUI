//! Subtitle resolution rescaling
//!
//! Adjusts PlayResX and PlayResY in ASS/SSA subtitles to match target video resolution

use crate::core::io::runner::CommandRunner;
use crate::core::models::results::CoreResult;
use serde_json::Value;
use std::path::Path;

/// Get video resolution using ffprobe
///
/// Returns (width, height) in pixels
pub fn get_video_resolution(
    video_path: &Path,
    runner: &CommandRunner,
) -> CoreResult<(u32, u32)> {
    let cmd = vec![
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        video_path.to_str().unwrap(),
    ];

    let output = runner.run(&cmd)?;
    let json: Value = serde_json::from_str(&output.stdout)?;

    let width = json["streams"][0]["width"]
        .as_u64()
        .ok_or("Failed to parse video width")? as u32;
    let height = json["streams"][0]["height"]
        .as_u64()
        .ok_or("Failed to parse video height")? as u32;

    Ok((width, height))
}

/// Rescale PlayRes in ASS/SSA subtitle file to match video resolution
///
/// Reads the subtitle file, updates PlayResX and PlayResY values in the
/// [Script Info] section, and writes the file back.
///
/// # Arguments
/// * `subtitle_path` - Path to the ASS/SSA file
/// * `target_width` - Target video width in pixels
/// * `target_height` - Target video height in pixels
///
/// # Returns
/// True if rescaling was performed, false if PlayRes tags not found
pub fn rescale_playres(
    subtitle_path: &Path,
    target_width: u32,
    target_height: u32,
) -> CoreResult<bool> {
    // Read the file
    let content = std::fs::read_to_string(subtitle_path)?;

    let mut modified = false;
    let mut new_lines = Vec::new();
    let mut in_script_info = false;
    let mut found_playres_x = false;
    let mut found_playres_y = false;

    for line in content.lines() {
        let trimmed = line.trim();

        // Track section
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            in_script_info = trimmed.to_lowercase().contains("script info");
        }

        // Update PlayRes values in Script Info section
        if in_script_info {
            if trimmed.to_lowercase().starts_with("playresx:") {
                new_lines.push(format!("PlayResX: {}", target_width));
                found_playres_x = true;
                modified = true;
                continue;
            } else if trimmed.to_lowercase().starts_with("playresy:") {
                new_lines.push(format!("PlayResY: {}", target_height));
                found_playres_y = true;
                modified = true;
                continue;
            }
        }

        // Keep line unchanged
        new_lines.push(line.to_string());
    }

    // Only write back if we actually found and modified PlayRes values
    if modified && found_playres_x && found_playres_y {
        std::fs::write(subtitle_path, new_lines.join("\n"))?;
        Ok(true)
    } else {
        Ok(false)
    }
}

/// Rescale subtitle to match video resolution
///
/// This is a convenience function that probes the video resolution and
/// rescales the subtitle in one call.
///
/// # Arguments
/// * `subtitle_path` - Path to the ASS/SSA file
/// * `video_path` - Path to the reference video file
/// * `runner` - Command runner for ffprobe
///
/// # Returns
/// True if rescaling was performed
pub fn rescale_to_video(
    subtitle_path: &Path,
    video_path: &Path,
    runner: &CommandRunner,
) -> CoreResult<bool> {
    let (width, height) = get_video_resolution(video_path, runner)?;
    rescale_playres(subtitle_path, width, height)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_rescale_playres() -> CoreResult<()> {
        // Create a temporary ASS file
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "[Script Info]").unwrap();
        writeln!(temp_file, "Title: Test").unwrap();
        writeln!(temp_file, "PlayResX: 1280").unwrap();
        writeln!(temp_file, "PlayResY: 720").unwrap();
        writeln!(temp_file, "").unwrap();
        writeln!(temp_file, "[V4+ Styles]").unwrap();
        writeln!(temp_file, "Format: Name, Fontname, Fontsize").unwrap();
        temp_file.flush().unwrap();

        let path = temp_file.path();

        // Rescale to 1920x1080
        let rescaled = rescale_playres(path, 1920, 1080)?;
        assert!(rescaled);

        // Read back and verify
        let content = std::fs::read_to_string(path)?;
        assert!(content.contains("PlayResX: 1920"));
        assert!(content.contains("PlayResY: 1080"));
        assert!(!content.contains("PlayResX: 1280"));
        assert!(!content.contains("PlayResY: 720"));

        Ok(())
    }

    #[test]
    fn test_rescale_no_playres() -> CoreResult<()> {
        // File without PlayRes tags should return false
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "[Script Info]").unwrap();
        writeln!(temp_file, "Title: Test").unwrap();
        writeln!(temp_file, "").unwrap();
        writeln!(temp_file, "[V4+ Styles]").unwrap();
        temp_file.flush().unwrap();

        let path = temp_file.path();
        let rescaled = rescale_playres(path, 1920, 1080)?;
        assert!(!rescaled);

        Ok(())
    }
}
