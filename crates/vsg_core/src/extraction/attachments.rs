//! Attachment extraction utilities.
//!
//! Provides functionality for extracting attachments (fonts, covers, etc.)
//! from Matroska files.

use std::path::{Path, PathBuf};

use super::mkvextract::extract_attachments as mkvextract_attachments;
use super::probe::probe_file;
use super::types::{AttachmentInfo, ExtractedAttachments, ExtractionResult};

/// Extract all attachments from an MKV file.
///
/// Creates a subdirectory for attachments and extracts them with their
/// original filenames.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `output_dir` - Directory where attachments will be written
///
/// # Returns
/// Information about extracted attachments including output paths.
pub fn extract_all_attachments(
    input_path: &Path,
    output_dir: &Path,
) -> ExtractionResult<ExtractedAttachments> {
    // Probe to get attachment info
    let probe = probe_file(input_path)?;

    if probe.attachments.is_empty() {
        tracing::debug!("No attachments found in {}", input_path.display());
        return Ok(ExtractedAttachments {
            output_dir: output_dir.to_path_buf(),
            files: Vec::new(),
        });
    }

    // Create output directory
    std::fs::create_dir_all(output_dir)?;

    // Build extraction specs
    let mut specs: Vec<(usize, PathBuf)> = Vec::new();
    let mut output_paths: Vec<PathBuf> = Vec::new();

    for attachment in &probe.attachments {
        let output_path = output_dir.join(&attachment.name);
        specs.push((attachment.id, output_path.clone()));
        output_paths.push(output_path);
    }

    // Convert to the format expected by mkvextract
    let spec_refs: Vec<(usize, &Path)> = specs
        .iter()
        .map(|(id, path)| (*id, path.as_path()))
        .collect();

    mkvextract_attachments(input_path, &spec_refs)?;

    tracing::info!(
        "Extracted {} attachments from {} to {}",
        output_paths.len(),
        input_path.display(),
        output_dir.display()
    );

    Ok(ExtractedAttachments {
        output_dir: output_dir.to_path_buf(),
        files: output_paths,
    })
}

/// Extract only font attachments from an MKV file.
///
/// Filters attachments to only include font files (TTF, OTF, etc.).
pub fn extract_font_attachments(
    input_path: &Path,
    output_dir: &Path,
) -> ExtractionResult<ExtractedAttachments> {
    let probe = probe_file(input_path)?;

    let fonts: Vec<&AttachmentInfo> = probe
        .attachments
        .iter()
        .filter(|a| a.is_font())
        .collect();

    if fonts.is_empty() {
        tracing::debug!("No font attachments found in {}", input_path.display());
        return Ok(ExtractedAttachments {
            output_dir: output_dir.to_path_buf(),
            files: Vec::new(),
        });
    }

    // Create output directory
    std::fs::create_dir_all(output_dir)?;

    // Build extraction specs
    let mut specs: Vec<(usize, PathBuf)> = Vec::new();
    let mut output_paths: Vec<PathBuf> = Vec::new();

    for font in &fonts {
        let output_path = output_dir.join(&font.name);
        specs.push((font.id, output_path.clone()));
        output_paths.push(output_path);
    }

    let spec_refs: Vec<(usize, &Path)> = specs
        .iter()
        .map(|(id, path)| (*id, path.as_path()))
        .collect();

    mkvextract_attachments(input_path, &spec_refs)?;

    tracing::info!(
        "Extracted {} fonts from {} to {}",
        output_paths.len(),
        input_path.display(),
        output_dir.display()
    );

    Ok(ExtractedAttachments {
        output_dir: output_dir.to_path_buf(),
        files: output_paths,
    })
}

/// Extract attachments by ID.
///
/// Extracts specific attachments by their IDs.
pub fn extract_attachments_by_id(
    input_path: &Path,
    output_dir: &Path,
    attachment_ids: &[usize],
) -> ExtractionResult<ExtractedAttachments> {
    if attachment_ids.is_empty() {
        return Ok(ExtractedAttachments {
            output_dir: output_dir.to_path_buf(),
            files: Vec::new(),
        });
    }

    let probe = probe_file(input_path)?;

    // Create output directory
    std::fs::create_dir_all(output_dir)?;

    // Build extraction specs for requested IDs
    let mut specs: Vec<(usize, PathBuf)> = Vec::new();
    let mut output_paths: Vec<PathBuf> = Vec::new();

    for &id in attachment_ids {
        if let Some(attachment) = probe.attachments.iter().find(|a| a.id == id) {
            let output_path = output_dir.join(&attachment.name);
            specs.push((id, output_path.clone()));
            output_paths.push(output_path);
        } else {
            tracing::warn!("Attachment {} not found in {}", id, input_path.display());
        }
    }

    if specs.is_empty() {
        return Ok(ExtractedAttachments {
            output_dir: output_dir.to_path_buf(),
            files: Vec::new(),
        });
    }

    let spec_refs: Vec<(usize, &Path)> = specs
        .iter()
        .map(|(id, path)| (*id, path.as_path()))
        .collect();

    mkvextract_attachments(input_path, &spec_refs)?;

    Ok(ExtractedAttachments {
        output_dir: output_dir.to_path_buf(),
        files: output_paths,
    })
}

/// Check if a file has any attachments.
pub fn has_attachments(input_path: &Path) -> ExtractionResult<bool> {
    let probe = probe_file(input_path)?;
    Ok(!probe.attachments.is_empty())
}

/// Check if a file has font attachments.
pub fn has_font_attachments(input_path: &Path) -> ExtractionResult<bool> {
    let probe = probe_file(input_path)?;
    Ok(probe.attachments.iter().any(|a| a.is_font()))
}

/// Get a list of all attachment info without extracting.
pub fn list_attachments(input_path: &Path) -> ExtractionResult<Vec<AttachmentInfo>> {
    let probe = probe_file(input_path)?;
    Ok(probe.attachments)
}

/// Calculate the total size of all attachments.
pub fn total_attachment_size(input_path: &Path) -> ExtractionResult<u64> {
    let probe = probe_file(input_path)?;
    let total = probe.attachments.iter().map(|a| a.size).sum();
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_ids_returns_empty() {
        // This should succeed without touching the filesystem
        let result = extract_attachments_by_id(
            &Path::new("/some/file.mkv"),
            &Path::new("/tmp/out"),
            &[],
        );
        // Will succeed because we short-circuit on empty IDs
        assert!(result.is_ok());
        assert!(result.unwrap().files.is_empty());
    }
}
