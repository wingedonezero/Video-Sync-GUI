//! Attachment extraction via mkvextract.
//!
//! This module handles extracting attachments (primarily fonts) from MKV files.
//! Fonts are essential for proper subtitle rendering.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Deserialize;

use super::types::{ExtractedAttachment, ExtractionError};

/// MIME types that indicate font files.
const FONT_MIME_TYPES: &[&str] = &[
    "application/x-truetype-font",
    "application/vnd.ms-opentype",
    "application/x-font-ttf",
    "application/x-font-otf",
    "application/x-font",
    "font/ttf",
    "font/otf",
    "font/sfnt",
    "font/collection",
    "font/woff",
    "font/woff2",
];

/// File extensions that indicate font files.
const FONT_EXTENSIONS: &[&str] = &[
    "ttf", "otf", "ttc", "woff", "woff2", "pfb", "pfm", "fon",
];

/// Parsed attachment info from mkvmerge -J.
#[derive(Debug, Deserialize)]
struct MkvmergeJson {
    attachments: Option<Vec<MkvAttachment>>,
}

#[derive(Debug, Deserialize)]
struct MkvAttachment {
    id: i64,
    file_name: Option<String>,
    content_type: Option<String>,
    size: Option<i64>,
}

/// Check if an attachment is a font based on MIME type or extension.
fn is_font(mime_type: &str, file_name: &str) -> bool {
    // Check MIME type
    let mime_lower = mime_type.to_lowercase();
    if FONT_MIME_TYPES.iter().any(|t| mime_lower.contains(t)) {
        return true;
    }

    // Check file extension
    if let Some(ext) = Path::new(file_name).extension() {
        let ext_lower = ext.to_string_lossy().to_lowercase();
        if FONT_EXTENSIONS.contains(&ext_lower.as_str()) {
            return true;
        }
    }

    false
}

/// Get list of attachments from a media file.
///
/// Returns attachment metadata without extracting the files.
pub fn list_attachments(
    source_path: &Path,
) -> Result<Vec<(usize, String, String, i64)>, ExtractionError> {
    // Verify file exists
    if !source_path.exists() {
        return Err(ExtractionError::FileNotFound(source_path.to_path_buf()));
    }

    // Run mkvmerge -J
    let output = Command::new("mkvmerge")
        .arg("-J")
        .arg(source_path)
        .output()
        .map_err(|e| ExtractionError::ToolExecutionFailed {
            tool: "mkvmerge".to_string(),
            message: format!("Failed to execute: {}", e),
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::ToolExecutionFailed {
            tool: "mkvmerge".to_string(),
            message: format!("Exit code {}: {}", output.status, stderr),
        });
    }

    // Parse JSON output
    let json_str = String::from_utf8_lossy(&output.stdout);
    let mkv_info: MkvmergeJson = serde_json::from_str(&json_str).map_err(|e| {
        ExtractionError::ParseError {
            tool: "mkvmerge".to_string(),
            message: format!("JSON parse error: {}", e),
        }
    })?;

    // Extract attachment info
    let attachments = mkv_info.attachments.unwrap_or_default();
    Ok(attachments
        .into_iter()
        .map(|a| {
            (
                a.id as usize,
                a.file_name.unwrap_or_default(),
                a.content_type.unwrap_or_default(),
                a.size.unwrap_or(0),
            )
        })
        .collect())
}

/// Extract all font attachments from a media file.
///
/// # Arguments
///
/// * `source_key` - The source identifier (e.g., "Source 1")
/// * `source_path` - Path to the media file
/// * `output_dir` - Directory to extract fonts to
///
/// # Returns
///
/// List of extracted font attachments.
pub fn extract_fonts(
    source_key: &str,
    source_path: &Path,
    output_dir: &Path,
) -> Result<Vec<ExtractedAttachment>, ExtractionError> {
    // List all attachments
    let attachments = list_attachments(source_path)?;

    // Filter to fonts only
    let fonts: Vec<_> = attachments
        .iter()
        .filter(|(_, name, mime, _)| is_font(mime, name))
        .collect();

    if fonts.is_empty() {
        return Ok(Vec::new());
    }

    // Create output directory
    std::fs::create_dir_all(output_dir).map_err(|e| {
        ExtractionError::IoError(format!("Failed to create output directory: {}", e))
    })?;

    // Build mkvextract command
    // Format: mkvextract attachments source.mkv id1:output1 id2:output2 ...
    let mut cmd = Command::new("mkvextract");
    cmd.arg("attachments").arg(source_path);

    let mut expected_outputs: Vec<(usize, String, String, PathBuf)> = Vec::new();

    for (id, file_name, mime_type, _) in &fonts {
        // Use original filename, ensuring it's unique by prefixing with ID if needed
        let output_filename = if expected_outputs.iter().any(|(_, n, _, _)| n == file_name) {
            format!("{}_{}", id, file_name)
        } else {
            file_name.clone()
        };
        let output_path = output_dir.join(&output_filename);

        cmd.arg(format!("{}:{}", id, output_path.display()));
        expected_outputs.push((*id, file_name.clone(), mime_type.clone(), output_path));
    }

    // Execute extraction
    let output = cmd.output().map_err(|e| ExtractionError::ToolExecutionFailed {
        tool: "mkvextract".to_string(),
        message: format!("Failed to execute: {}", e),
    })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        // mkvextract may return warnings but still succeed
        if output.status.code() != Some(1) {
            return Err(ExtractionError::ToolExecutionFailed {
                tool: "mkvextract".to_string(),
                message: format!("Exit code {}: {}", output.status, stderr),
            });
        }
    }

    // Build results from successfully extracted files
    let mut results = Vec::new();
    for (id, file_name, mime_type, output_path) in expected_outputs {
        if output_path.exists() && output_path.metadata().map(|m| m.len()).unwrap_or(0) > 0 {
            results.push(ExtractedAttachment {
                source_key: source_key.to_string(),
                attachment_id: id,
                file_name,
                mime_type,
                extracted_path: output_path,
            });
        } else {
            tracing::warn!(
                "Font extraction may have failed for attachment {} ({})",
                id,
                file_name
            );
        }
    }

    Ok(results)
}

/// Extract all attachments (not just fonts) from a media file.
///
/// Use this when you need all attachments, not just fonts.
pub fn extract_all_attachments(
    source_key: &str,
    source_path: &Path,
    output_dir: &Path,
) -> Result<Vec<ExtractedAttachment>, ExtractionError> {
    // List all attachments
    let attachments = list_attachments(source_path)?;

    if attachments.is_empty() {
        return Ok(Vec::new());
    }

    // Create output directory
    std::fs::create_dir_all(output_dir).map_err(|e| {
        ExtractionError::IoError(format!("Failed to create output directory: {}", e))
    })?;

    // Build mkvextract command
    let mut cmd = Command::new("mkvextract");
    cmd.arg("attachments").arg(source_path);

    let mut expected_outputs: Vec<(usize, String, String, PathBuf)> = Vec::new();

    for (id, file_name, mime_type, _) in &attachments {
        // Ensure unique filenames
        let output_filename = if expected_outputs.iter().any(|(_, n, _, _)| n == file_name) {
            format!("{}_{}", id, file_name)
        } else {
            file_name.clone()
        };
        let output_path = output_dir.join(&output_filename);

        cmd.arg(format!("{}:{}", id, output_path.display()));
        expected_outputs.push((*id, file_name.clone(), mime_type.clone(), output_path));
    }

    // Execute extraction
    let output = cmd.output().map_err(|e| ExtractionError::ToolExecutionFailed {
        tool: "mkvextract".to_string(),
        message: format!("Failed to execute: {}", e),
    })?;

    if !output.status.success() && output.status.code() != Some(1) {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::ToolExecutionFailed {
            tool: "mkvextract".to_string(),
            message: format!("Exit code {}: {}", output.status, stderr),
        });
    }

    // Build results
    let mut results = Vec::new();
    for (id, file_name, mime_type, output_path) in expected_outputs {
        if output_path.exists() && output_path.metadata().map(|m| m.len()).unwrap_or(0) > 0 {
            results.push(ExtractedAttachment {
                source_key: source_key.to_string(),
                attachment_id: id,
                file_name,
                mime_type,
                extracted_path: output_path,
            });
        }
    }

    Ok(results)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_font() {
        // MIME type detection
        assert!(is_font("application/x-truetype-font", "font.ttf"));
        assert!(is_font("font/otf", "font.otf"));
        assert!(is_font("application/vnd.ms-opentype", "font.otf"));

        // Extension detection
        assert!(is_font("application/octet-stream", "arial.ttf"));
        assert!(is_font("application/octet-stream", "times.otf"));
        assert!(is_font("", "font.woff"));

        // Non-fonts
        assert!(!is_font("image/png", "cover.png"));
        assert!(!is_font("application/octet-stream", "data.bin"));
    }

    #[test]
    fn test_nonexistent_file() {
        let result = list_attachments(Path::new("/nonexistent/file.mkv"));
        assert!(matches!(result, Err(ExtractionError::FileNotFound(_))));
    }
}
