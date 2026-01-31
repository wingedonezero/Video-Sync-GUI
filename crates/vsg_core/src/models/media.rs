//! Media-related data structures (tracks, streams, attachments).

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use super::enums::TrackType;

/// Properties of a media stream (codec, language, name).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StreamProps {
    /// Codec identifier (e.g., "A_AAC", "V_MPEG4/ISO/AVC").
    pub codec_id: String,
    /// Language code (ISO 639-2, e.g., "eng", "jpn", "und").
    #[serde(default = "default_lang")]
    pub lang: String,
    /// Track name/title.
    #[serde(default)]
    pub name: String,
}

fn default_lang() -> String {
    "und".to_string()
}

impl StreamProps {
    /// Create new stream properties with required codec.
    pub fn new(codec_id: impl Into<String>) -> Self {
        Self {
            codec_id: codec_id.into(),
            lang: default_lang(),
            name: String::new(),
        }
    }

    /// Set the language code.
    pub fn with_lang(mut self, lang: impl Into<String>) -> Self {
        self.lang = lang.into();
        self
    }

    /// Set the track name.
    pub fn with_name(mut self, name: impl Into<String>) -> Self {
        self.name = name.into();
        self
    }
}

/// A single track within a media container.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Track {
    /// Source identifier (e.g., "Source 1", "Source 2").
    pub source: String,
    /// Track ID within the container (mkvmerge numbering).
    pub id: u32,
    /// Type of track (video, audio, subtitles).
    #[serde(rename = "type")]
    pub track_type: TrackType,
    /// Stream properties.
    pub props: StreamProps,
}

impl Track {
    /// Create a new track.
    pub fn new(
        source: impl Into<String>,
        id: u32,
        track_type: TrackType,
        props: StreamProps,
    ) -> Self {
        Self {
            source: source.into(),
            id,
            track_type,
            props,
        }
    }

    /// Get a display string for this track.
    pub fn display_name(&self) -> String {
        let name_part = if self.props.name.is_empty() {
            String::new()
        } else {
            format!(" - {}", self.props.name)
        };
        format!(
            "{} Track {} ({}){}",
            self.track_type, self.id, self.props.lang, name_part
        )
    }
}

/// An attachment within a media container (fonts, images, etc.).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Attachment {
    /// Attachment ID within the container.
    pub id: u32,
    /// Original filename.
    pub file_name: String,
    /// Path where attachment was extracted (if extracted).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub out_path: Option<PathBuf>,
}

impl Attachment {
    /// Create a new attachment.
    pub fn new(id: u32, file_name: impl Into<String>) -> Self {
        Self {
            id,
            file_name: file_name.into(),
            out_path: None,
        }
    }

    /// Set the output path.
    pub fn with_out_path(mut self, path: PathBuf) -> Self {
        self.out_path = Some(path);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn track_display_name_without_name() {
        let track = Track::new(
            "Source 1",
            0,
            TrackType::Video,
            StreamProps::new("V_MPEG4/ISO/AVC").with_lang("und"),
        );
        assert_eq!(track.display_name(), "video Track 0 (und)");
    }

    #[test]
    fn track_display_name_with_name() {
        let track = Track::new(
            "Source 1",
            1,
            TrackType::Audio,
            StreamProps::new("A_AAC")
                .with_lang("jpn")
                .with_name("Japanese 2.0"),
        );
        assert_eq!(track.display_name(), "audio Track 1 (jpn) - Japanese 2.0");
    }

    #[test]
    fn stream_props_serializes() {
        let props = StreamProps::new("A_AC3").with_lang("eng");
        let json = serde_json::to_string(&props).unwrap();
        assert!(json.contains("\"codec_id\":\"A_AC3\""));
        assert!(json.contains("\"lang\":\"eng\""));
    }
}
