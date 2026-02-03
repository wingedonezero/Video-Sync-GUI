//! Track extraction utilities.
//!
//! Provides higher-level track extraction functionality built on
//! top of the mkvextract wrapper.

use std::path::{Path, PathBuf};

use super::mkvextract::{
    extension_for_codec, extract_audio_with_ffmpeg, extract_track, extract_tracks,
    requires_ffmpeg_extraction,
};
use super::probe::probe_file;
use super::types::{ExtractedTrack, ExtractionError, ExtractionResult, ProbeResult, TrackInfo, TrackType};

/// Extract a track to a file with automatic extension detection.
///
/// Probes the file to determine the codec and generates an appropriate
/// output filename with the correct extension.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `track_id` - Track ID to extract
/// * `output_dir` - Directory where the track will be written
/// * `base_name` - Base name for the output file (extension added automatically)
///
/// # Returns
/// Information about the extracted track including the output path.
pub fn extract_track_auto(
    input_path: &Path,
    track_id: usize,
    output_dir: &Path,
    base_name: &str,
) -> ExtractionResult<ExtractedTrack> {
    // Probe to get codec info
    let probe = probe_file(input_path)?;

    let track_info = probe
        .track_by_id(track_id)
        .ok_or_else(|| ExtractionError::TrackNotFound(track_id))?;

    let extension = extension_for_codec(&track_info.codec_id);
    let output_path = output_dir.join(format!("{}.{}", base_name, extension));

    // Create output directory if needed
    std::fs::create_dir_all(output_dir)?;

    extract_track(input_path, track_id, &output_path)?;

    Ok(ExtractedTrack {
        track_id,
        track_type: track_info.track_type,
        output_path,
    })
}

/// Specification for extracting a track.
#[derive(Debug, Clone)]
pub struct TrackExtractSpec {
    /// Track ID to extract.
    pub track_id: usize,
    /// Base name for output file.
    pub base_name: String,
    /// Optional custom extension (overrides auto-detection).
    pub extension: Option<String>,
}

impl TrackExtractSpec {
    /// Create a new track extraction spec.
    pub fn new(track_id: usize, base_name: impl Into<String>) -> Self {
        Self {
            track_id,
            base_name: base_name.into(),
            extension: None,
        }
    }

    /// Set a custom extension.
    pub fn with_extension(mut self, ext: impl Into<String>) -> Self {
        self.extension = Some(ext.into());
        self
    }
}

/// Extract multiple tracks in one pass.
///
/// More efficient than individual extractions for multiple tracks.
pub fn extract_tracks_batch(
    input_path: &Path,
    output_dir: &Path,
    specs: &[TrackExtractSpec],
) -> ExtractionResult<Vec<ExtractedTrack>> {
    if specs.is_empty() {
        return Ok(Vec::new());
    }

    // Create output directory
    std::fs::create_dir_all(output_dir)?;

    // Probe to get codec info
    let probe = probe_file(input_path)?;

    // Build extraction specs with paths
    let mut track_specs: Vec<(usize, PathBuf)> = Vec::new();
    let mut results: Vec<ExtractedTrack> = Vec::new();

    for spec in specs {
        let track_info = probe
            .track_by_id(spec.track_id)
            .ok_or_else(|| ExtractionError::TrackNotFound(spec.track_id))?;

        let extension = spec
            .extension
            .as_deref()
            .unwrap_or_else(|| extension_for_codec(&track_info.codec_id));

        let output_path = output_dir.join(format!("{}.{}", spec.base_name, extension));

        track_specs.push((spec.track_id, output_path.clone()));
        results.push(ExtractedTrack {
            track_id: spec.track_id,
            track_type: track_info.track_type,
            output_path,
        });
    }

    // Convert to the format expected by mkvextract wrapper
    let spec_refs: Vec<(usize, &Path)> = track_specs
        .iter()
        .map(|(id, path)| (*id, path.as_path()))
        .collect();

    extract_tracks(input_path, &spec_refs)?;

    Ok(results)
}

/// Extract all tracks of a specific type.
pub fn extract_all_of_type(
    input_path: &Path,
    output_dir: &Path,
    track_type: TrackType,
    base_name: &str,
) -> ExtractionResult<Vec<ExtractedTrack>> {
    let probe = probe_file(input_path)?;

    let tracks: Vec<&TrackInfo> = probe
        .tracks
        .iter()
        .filter(|t| t.track_type == track_type)
        .collect();

    if tracks.is_empty() {
        return Ok(Vec::new());
    }

    let specs: Vec<TrackExtractSpec> = tracks
        .iter()
        .enumerate()
        .map(|(idx, t)| {
            let name = if tracks.len() == 1 {
                base_name.to_string()
            } else {
                format!("{}_{}", base_name, idx)
            };
            TrackExtractSpec::new(t.id, name)
        })
        .collect();

    extract_tracks_batch(input_path, output_dir, &specs)
}

/// Extract a track by language preference.
///
/// Searches for a track of the specified type with the preferred language.
/// Falls back to the default track or first available track if not found.
pub fn extract_by_language(
    input_path: &Path,
    output_dir: &Path,
    track_type: TrackType,
    preferred_lang: &str,
    base_name: &str,
) -> ExtractionResult<Option<ExtractedTrack>> {
    let probe = probe_file(input_path)?;

    let type_tracks: Vec<&TrackInfo> = probe
        .tracks
        .iter()
        .filter(|t| t.track_type == track_type)
        .collect();

    if type_tracks.is_empty() {
        return Ok(None);
    }

    // Try to find by language
    let track = type_tracks
        .iter()
        .find(|t| t.language.as_deref() == Some(preferred_lang))
        // Fall back to default track
        .or_else(|| type_tracks.iter().find(|t| t.is_default))
        // Fall back to first track
        .or_else(|| type_tracks.first());

    if let Some(track) = track {
        let result = extract_track_auto(input_path, track.id, output_dir, base_name)?;
        Ok(Some(result))
    } else {
        Ok(None)
    }
}

/// Find the video track to use as the reference (usually track 0).
pub fn get_reference_video_track(input_path: &Path) -> ExtractionResult<Option<TrackInfo>> {
    let probe = probe_file(input_path)?;
    Ok(probe.default_video().cloned())
}

/// Get all audio tracks sorted by preference (default first, then by language).
pub fn get_audio_tracks_sorted(input_path: &Path) -> ExtractionResult<Vec<TrackInfo>> {
    let probe = probe_file(input_path)?;
    let mut tracks: Vec<TrackInfo> = probe.audio_tracks().cloned().collect();

    // Sort: default tracks first, then by track ID
    tracks.sort_by(|a, b| match (a.is_default, b.is_default) {
        (true, false) => std::cmp::Ordering::Less,
        (false, true) => std::cmp::Ordering::Greater,
        _ => a.id.cmp(&b.id),
    });

    Ok(tracks)
}

/// Build the output path for an extracted track.
///
/// Creates a standardized filename format: `{source_key}_{source_stem}_track{id}.{ext}`
///
/// # Arguments
/// * `source_path` - Path to the source file (used for stem)
/// * `track_id` - Track ID being extracted
/// * `codec_id` - Codec identifier for determining extension
/// * `work_dir` - Working directory for output
/// * `source_key` - Source key identifier (e.g., "Source 1")
pub fn build_track_output_path(
    source_path: &Path,
    track_id: usize,
    codec_id: &str,
    work_dir: &Path,
    source_key: &str,
) -> PathBuf {
    let source_stem = source_path
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "track".to_string());

    let extension = extension_for_codec(codec_id);

    work_dir.join(format!(
        "{}_{}_track{}.{}",
        source_key.replace(' ', "_").to_lowercase(),
        source_stem,
        track_id,
        extension
    ))
}

/// Verify that an extraction produced a valid output file.
///
/// Checks that the file exists and is non-empty.
///
/// # Returns
/// The file size in bytes on success, or an error describing the problem.
pub fn verify_extraction_result(output_path: &Path, track_id: usize) -> ExtractionResult<u64> {
    if !output_path.exists() {
        return Err(ExtractionError::ExtractionFailed(format!(
            "Track {} extraction produced no output file",
            track_id
        )));
    }

    let metadata = std::fs::metadata(output_path).map_err(|e| {
        ExtractionError::ExtractionFailed(format!(
            "Cannot read metadata for track {} output: {}",
            track_id, e
        ))
    })?;

    if metadata.len() == 0 {
        return Err(ExtractionError::ExtractionFailed(format!(
            "Track {} extraction produced empty file (0 bytes)",
            track_id
        )));
    }

    Ok(metadata.len())
}

/// Result of a smart track extraction.
#[derive(Debug, Clone)]
pub struct SmartExtractResult {
    /// The extraction method used.
    pub method: ExtractionMethod,
    /// Size of the extracted file in bytes.
    pub size_bytes: u64,
}

/// Method used for extraction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExtractionMethod {
    /// Standard mkvextract.
    Mkvextract,
    /// Ffmpeg (for A_MS/ACM and similar codecs).
    Ffmpeg,
}

/// Extract a track with automatic method selection.
///
/// Handles the decision of whether to use mkvextract or ffmpeg based on
/// the codec type. For A_MS/ACM and similar codecs that mkvextract can't
/// handle directly, ffmpeg is used instead.
///
/// # Arguments
/// * `source_path` - Path to the source MKV file
/// * `track_id` - Track ID to extract
/// * `output_path` - Path where the track will be written
/// * `probe_result` - Probe result for the source file (needed to determine method)
pub fn extract_track_smart(
    source_path: &Path,
    track_id: usize,
    output_path: &Path,
    probe_result: &ProbeResult,
) -> ExtractionResult<SmartExtractResult> {
    let track_info = probe_result.track_by_id(track_id);
    let codec_id = track_info.map(|t| t.codec_id.as_str()).unwrap_or("");

    // Check if this codec needs ffmpeg extraction
    if requires_ffmpeg_extraction(codec_id) {
        // Find the audio stream index for ffmpeg (0-based within audio streams)
        let audio_stream_index = probe_result
            .audio_tracks()
            .position(|t| t.id == track_id)
            .unwrap_or(0);

        let bit_depth = track_info.and_then(|t| t.properties.bits_per_sample);

        extract_audio_with_ffmpeg(source_path, audio_stream_index, output_path, bit_depth)?;

        let size = verify_extraction_result(output_path, track_id)?;
        return Ok(SmartExtractResult {
            method: ExtractionMethod::Ffmpeg,
            size_bytes: size,
        });
    }

    // Standard mkvextract
    extract_track(source_path, track_id, output_path)?;

    let size = verify_extraction_result(output_path, track_id)?;
    Ok(SmartExtractResult {
        method: ExtractionMethod::Mkvextract,
        size_bytes: size,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn track_extract_spec_builder() {
        let spec = TrackExtractSpec::new(1, "audio").with_extension("aac");

        assert_eq!(spec.track_id, 1);
        assert_eq!(spec.base_name, "audio");
        assert_eq!(spec.extension, Some("aac".to_string()));
    }

    #[test]
    fn build_output_path_format() {
        let path = build_track_output_path(
            Path::new("/videos/movie.mkv"),
            2,
            "A_AAC",
            Path::new("/tmp/work"),
            "Source 1",
        );
        assert_eq!(
            path,
            PathBuf::from("/tmp/work/source_1_movie_track2.aac")
        );
    }

    #[test]
    fn build_output_path_handles_spaces_in_source_key() {
        let path = build_track_output_path(
            Path::new("/videos/test.mkv"),
            0,
            "V_MPEG4/ISO/AVC",
            Path::new("/tmp"),
            "Source 2",
        );
        assert_eq!(path, PathBuf::from("/tmp/source_2_test_track0.h264"));
    }
}
