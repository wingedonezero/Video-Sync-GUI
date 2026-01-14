//! Track extraction from media files using mkvmerge and mkvextract

use crate::core::io::runner::CommandRunner;
use crate::core::models::converters::get_extension_for_codec;
use crate::core::models::media::{StreamProps, Track};
use crate::core::models::results::{CoreError, CoreResult};
use crate::core::models::enums::TrackType;
use serde_json::Value;
use std::path::{Path, PathBuf};

/// Parse mkvmerge JSON output and create Track objects
pub fn parse_mkvmerge_json(
    json_str: &str,
    source_id: &str,
    file_path: &Path,
) -> CoreResult<Vec<Track>> {
    let json: Value = serde_json::from_str(json_str)
        .map_err(|e| CoreError::ParseError(format!("JSON parse error: {}", e)))?;

    let tracks_array = json
        .get("tracks")
        .and_then(|t| t.as_array())
        .ok_or_else(|| CoreError::ParseError("No 'tracks' array in JSON".to_string()))?;

    let mut tracks = Vec::new();

    for track_obj in tracks_array {
        // Get track ID
        let track_id = track_obj
            .get("id")
            .and_then(|v| v.as_i64())
            .ok_or_else(|| CoreError::ParseError("Missing track id".to_string()))?
            as i32;

        // Get track type
        let type_str = track_obj
            .get("type")
            .and_then(|v| v.as_str())
            .ok_or_else(|| CoreError::ParseError("Missing track type".to_string()))?;

        let track_type = TrackType::from_mkvmerge_type(type_str)
            .ok_or_else(|| CoreError::ParseError(format!("Unknown track type: {}", type_str)))?;

        // Get properties
        let props_obj = track_obj
            .get("properties")
            .ok_or_else(|| CoreError::ParseError("Missing track properties".to_string()))?;

        let props = StreamProps::from_mkvmerge_json(props_obj);

        let track = Track::new(source_id.to_string(), track_id, track_type, props);
        tracks.push(track);
    }

    Ok(tracks)
}

/// Extract tracks from a media file
pub struct TrackExtractor {
    runner: CommandRunner,
    temp_dir: PathBuf,
}

impl TrackExtractor {
    /// Create a new track extractor
    pub fn new(runner: CommandRunner, temp_dir: PathBuf) -> Self {
        Self { runner, temp_dir }
    }

    /// Get media info using mkvmerge -J
    pub fn get_media_info(&self, file_path: &Path) -> CoreResult<Vec<Track>> {
        let file_str = file_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", file_path)))?;

        let output = self.runner.run(&["mkvmerge", "-J", file_str])?;

        if !output.success {
            return Err(CoreError::CommandFailed(format!(
                "mkvmerge -J failed: {}",
                output.stderr
            )));
        }

        // Determine source ID from filename
        let source_id = file_path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("UNK");

        parse_mkvmerge_json(&output.stdout, source_id, file_path)
    }

    /// Extract a single track from a file
    pub fn extract_track(
        &self,
        file_path: &Path,
        track: &Track,
    ) -> CoreResult<PathBuf> {
        // Determine output file extension
        let codec_id = track.props.codec_id.as_deref().unwrap_or("unknown");
        let ext = get_extension_for_codec(codec_id, track.track_type);

        // Build output filename
        let base_name = file_path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("track");

        let track_prefix = track.track_type.prefix();
        let output_filename = format!("{}_{}_{}{}", base_name, track_prefix, track.id, ext);
        let output_path = self.temp_dir.join(&output_filename);

        // Handle A_MS/ACM special case (needs to be extracted as WAV)
        let is_a_ms_acm = codec_id.contains("A_MS/ACM");

        let file_str = file_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", file_path)))?;
        let output_str = output_path
            .to_str()
            .ok_or_else(|| CoreError::Other("Invalid output path".to_string()))?;

        // Build mkvextract command
        let track_spec = format!("{}:{}", track.id, output_str);

        let output = self.runner.run(&[
            "mkvextract",
            file_str,
            "tracks",
            &track_spec,
        ])?;

        if !output.success {
            return Err(CoreError::ExtractionError(format!(
                "mkvextract failed: {}",
                output.stderr
            )));
        }

        // Verify output file exists
        if !output_path.exists() {
            return Err(CoreError::ExtractionError(format!(
                "Extracted file not found: {:?}",
                output_path
            )));
        }

        Ok(output_path)
    }

    /// Extract multiple tracks
    pub fn extract_tracks(
        &self,
        file_path: &Path,
        tracks: &[&Track],
    ) -> CoreResult<Vec<PathBuf>> {
        let mut output_paths = Vec::new();

        for track in tracks {
            let path = self.extract_track(file_path, track)?;
            output_paths.push(path);
        }

        Ok(output_paths)
    }

    /// Extract attachments from a file
    pub fn extract_attachments(&self, file_path: &Path) -> CoreResult<Vec<PathBuf>> {
        let file_str = file_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", file_path)))?;

        // List attachments first
        let output = self.runner.run(&["mkvmerge", "-J", file_str])?;

        if !output.success {
            return Err(CoreError::CommandFailed(format!(
                "mkvmerge -J failed: {}",
                output.stderr
            )));
        }

        let json: Value = serde_json::from_str(&output.stdout)
            .map_err(|e| CoreError::ParseError(format!("JSON parse error: {}", e)))?;

        let attachments = json
            .get("attachments")
            .and_then(|a| a.as_array())
            .map(|a| a.to_vec())
            .unwrap_or_default();

        if attachments.is_empty() {
            return Ok(Vec::new());
        }

        // Extract all attachments
        let output = self.runner.run(&[
            "mkvextract",
            file_str,
            "attachments",
            "all",
        ])?;

        if !output.success {
            return Err(CoreError::ExtractionError(format!(
                "Attachment extraction failed: {}",
                output.stderr
            )));
        }

        // Attachments are extracted to current directory by default
        // Return empty vec for now (would need to track extracted files)
        Ok(Vec::new())
    }

    /// Check if file has chapters
    pub fn has_chapters(&self, file_path: &Path) -> CoreResult<bool> {
        let file_str = file_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", file_path)))?;

        let output = self.runner.run(&["mkvmerge", "-J", file_str])?;

        if !output.success {
            return Ok(false);
        }

        let json: Value = serde_json::from_str(&output.stdout)
            .map_err(|e| CoreError::ParseError(format!("JSON parse error: {}", e)))?;

        Ok(json.get("chapters").is_some())
    }

    /// Extract chapters as XML
    pub fn extract_chapters(&self, file_path: &Path) -> CoreResult<PathBuf> {
        let base_name = file_path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("chapters");

        let output_path = self.temp_dir.join(format!("{}_chapters.xml", base_name));

        let file_str = file_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", file_path)))?;
        let output_str = output_path
            .to_str()
            .ok_or_else(|| CoreError::Other("Invalid output path".to_string()))?;

        let output = self.runner.run(&[
            "mkvextract",
            file_str,
            "chapters",
            output_str,
        ])?;

        if !output.success {
            return Err(CoreError::ExtractionError(format!(
                "Chapter extraction failed: {}",
                output.stderr
            )));
        }

        Ok(output_path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_mkvmerge_json() {
        let json = r#"{
            "tracks": [
                {
                    "id": 0,
                    "type": "video",
                    "properties": {
                        "codec_id": "V_MPEG4/ISO/AVC",
                        "language": "und",
                        "pixel_dimensions": "1920x1080"
                    }
                },
                {
                    "id": 1,
                    "type": "audio",
                    "properties": {
                        "codec_id": "A_EAC3",
                        "language": "eng",
                        "audio_channels": 6,
                        "audio_sampling_frequency": 48000
                    }
                }
            ]
        }"#;

        let tracks = parse_mkvmerge_json(json, "TEST", Path::new("test.mkv")).unwrap();

        assert_eq!(tracks.len(), 2);
        assert_eq!(tracks[0].track_type, TrackType::Video);
        assert_eq!(tracks[1].track_type, TrackType::Audio);
        assert_eq!(tracks[1].props.audio_channels, Some(6));
    }
}
