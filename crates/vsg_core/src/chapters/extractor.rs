//! Chapter extraction using mkvextract.
//!
//! Extracts Matroska chapter data from video files.

use std::path::Path;
use std::process::Command;

use super::types::{ChapterError, ChapterResult};

/// Extract chapters from an MKV file to XML format.
///
/// Uses mkvextract to extract chapters in Matroska XML format.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `output_path` - Path where the chapter XML will be written
///
/// # Returns
/// * `Ok(true)` - Chapters were extracted successfully
/// * `Ok(false)` - No chapters found in source
/// * `Err(ChapterError)` - Extraction failed
pub fn extract_chapters(input_path: &Path, output_path: &Path) -> ChapterResult<bool> {
    tracing::debug!(
        "Extracting chapters from {} to {}",
        input_path.display(),
        output_path.display()
    );

    // mkvextract chapters <input> --simple
    // We use the non-simple format (XML) for full chapter data
    let output = Command::new("mkvextract")
        .arg("chapters")
        .arg(input_path)
        .arg("--output-charset")
        .arg("UTF-8")
        .output()
        .map_err(|e| ChapterError::ExtractionError(format!("Failed to run mkvextract: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        // mkvextract returns success but empty output if no chapters
        if stderr.contains("No chapters found") || output.stdout.is_empty() {
            tracing::debug!("No chapters found in {}", input_path.display());
            return Ok(false);
        }
        return Err(ChapterError::CommandFailed {
            tool: "mkvextract".to_string(),
            exit_code: output.status.code().unwrap_or(-1),
            message: stderr.to_string(),
        });
    }

    // Check if any chapter data was returned
    let chapter_xml = String::from_utf8_lossy(&output.stdout);
    if chapter_xml.trim().is_empty() {
        tracing::debug!("No chapters found in {}", input_path.display());
        return Ok(false);
    }

    // Write the chapter XML to the output file
    std::fs::write(output_path, &*chapter_xml)?;

    tracing::info!(
        "Extracted chapters from {} to {}",
        input_path.display(),
        output_path.display()
    );

    Ok(true)
}

/// Extract chapters to a string (for in-memory processing).
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
///
/// # Returns
/// * `Ok(Some(xml))` - Chapter XML content
/// * `Ok(None)` - No chapters found
/// * `Err(ChapterError)` - Extraction failed
pub fn extract_chapters_to_string(input_path: &Path) -> ChapterResult<Option<String>> {
    tracing::debug!("Extracting chapters from {}", input_path.display());

    let output = Command::new("mkvextract")
        .arg("chapters")
        .arg(input_path)
        .arg("--output-charset")
        .arg("UTF-8")
        .output()
        .map_err(|e| ChapterError::ExtractionError(format!("Failed to run mkvextract: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if stderr.contains("No chapters found") || output.stdout.is_empty() {
            return Ok(None);
        }
        return Err(ChapterError::CommandFailed {
            tool: "mkvextract".to_string(),
            exit_code: output.status.code().unwrap_or(-1),
            message: stderr.to_string(),
        });
    }

    let chapter_xml = String::from_utf8_lossy(&output.stdout).to_string();
    if chapter_xml.trim().is_empty() {
        return Ok(None);
    }

    Ok(Some(chapter_xml))
}

/// Check if an MKV file has chapters.
///
/// This is a lightweight check using mkvmerge -J to probe the file.
pub fn has_chapters(input_path: &Path) -> ChapterResult<bool> {
    let output = Command::new("mkvmerge")
        .arg("-J")
        .arg(input_path)
        .output()
        .map_err(|e| ChapterError::ExtractionError(format!("Failed to run mkvmerge: {}", e)))?;

    if !output.status.success() {
        return Err(ChapterError::CommandFailed {
            tool: "mkvmerge".to_string(),
            exit_code: output.status.code().unwrap_or(-1),
            message: String::from_utf8_lossy(&output.stderr).to_string(),
        });
    }

    let json: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| ChapterError::ParseError(format!("Invalid JSON from mkvmerge: {}", e)))?;

    // Check if chapters array exists and is non-empty
    let has = json
        .get("chapters")
        .and_then(|c| c.as_array())
        .map(|arr| !arr.is_empty())
        .unwrap_or(false);

    Ok(has)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn extract_from_nonexistent_file_fails() {
        let result = extract_chapters_to_string(&PathBuf::from("/nonexistent/file.mkv"));
        assert!(result.is_err());
    }
}
