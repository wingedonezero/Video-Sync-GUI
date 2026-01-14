//! Media track and stream property models

use super::enums::TrackType;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Stream properties extracted from mkvmerge -J output
///
/// This structure mirrors the Python StreamProps and captures all relevant
/// properties from mkvmerge's track information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StreamProps {
    /// Codec ID (e.g., "V_MPEG4/ISO/AVC", "A_EAC3", "S_TEXT/UTF8")
    pub codec_id: Option<String>,

    /// Language code (e.g., "eng", "jpn", "und")
    pub lang: Option<String>,

    /// Track name/title
    pub name: Option<String>,

    /// Default track flag
    pub default: bool,

    /// Forced display flag (subtitles)
    pub forced: bool,

    /// Audio channels (e.g., 2, 6, 8)
    pub audio_channels: Option<u8>,

    /// Audio sampling frequency in Hz (e.g., 48000)
    pub audio_sampling_frequency: Option<u32>,

    /// Audio bits per sample
    pub audio_bits_per_sample: Option<u8>,

    /// Video pixel width
    pub pixel_width: Option<u32>,

    /// Video pixel height
    pub pixel_height: Option<u32>,

    /// Video display width
    pub display_width: Option<u32>,

    /// Video display height
    pub display_height: Option<u32>,

    /// Frame rate (as string, e.g., "23.976", "24000/1001")
    pub frame_rate: Option<String>,

    /// Container delay in nanoseconds
    pub minimum_timestamp: Option<i64>,

    /// Extra properties that might be needed
    pub extra: HashMap<String, serde_json::Value>,
}

impl Default for StreamProps {
    fn default() -> Self {
        Self {
            codec_id: None,
            lang: None,
            name: None,
            default: false,
            forced: false,
            audio_channels: None,
            audio_sampling_frequency: None,
            audio_bits_per_sample: None,
            pixel_width: None,
            pixel_height: None,
            display_width: None,
            display_height: None,
            frame_rate: None,
            minimum_timestamp: None,
            extra: HashMap::new(),
        }
    }
}

impl StreamProps {
    /// Parse from mkvmerge JSON properties object
    pub fn from_mkvmerge_json(props: &serde_json::Value) -> Self {
        let obj = props.as_object();

        Self {
            codec_id: obj
                .and_then(|o| o.get("codec_id"))
                .and_then(|v| v.as_str())
                .map(String::from),
            lang: obj
                .and_then(|o| o.get("language"))
                .and_then(|v| v.as_str())
                .map(String::from),
            name: obj
                .and_then(|o| o.get("track_name"))
                .and_then(|v| v.as_str())
                .map(String::from),
            default: obj
                .and_then(|o| o.get("default_track"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            forced: obj
                .and_then(|o| o.get("forced_track"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            audio_channels: obj
                .and_then(|o| o.get("audio_channels"))
                .and_then(|v| v.as_u64())
                .map(|n| n as u8),
            audio_sampling_frequency: obj
                .and_then(|o| o.get("audio_sampling_frequency"))
                .and_then(|v| v.as_u64())
                .map(|n| n as u32),
            audio_bits_per_sample: obj
                .and_then(|o| o.get("audio_bits_per_sample"))
                .and_then(|v| v.as_u64())
                .map(|n| n as u8),
            pixel_width: obj
                .and_then(|o| o.get("pixel_dimensions"))
                .and_then(|v| v.as_str())
                .and_then(|s| s.split('x').next())
                .and_then(|s| s.parse().ok()),
            pixel_height: obj
                .and_then(|o| o.get("pixel_dimensions"))
                .and_then(|v| v.as_str())
                .and_then(|s| s.split('x').nth(1))
                .and_then(|s| s.parse().ok()),
            display_width: obj
                .and_then(|o| o.get("display_dimensions"))
                .and_then(|v| v.as_str())
                .and_then(|s| s.split('x').next())
                .and_then(|s| s.parse().ok()),
            display_height: obj
                .and_then(|o| o.get("display_dimensions"))
                .and_then(|v| v.as_str())
                .and_then(|s| s.split('x').nth(1))
                .and_then(|s| s.parse().ok()),
            frame_rate: obj
                .and_then(|o| o.get("frame_rate"))
                .and_then(|v| v.as_str())
                .map(String::from),
            minimum_timestamp: obj
                .and_then(|o| o.get("minimum_timestamp"))
                .and_then(|v| v.as_i64()),
            extra: HashMap::new(),
        }
    }

    /// Get display string for codec
    pub fn codec_display(&self) -> String {
        self.codec_id
            .as_ref()
            .map(|c| c.as_str())
            .unwrap_or("unknown")
            .to_string()
    }

    /// Get display string for language
    pub fn lang_display(&self) -> String {
        self.lang
            .as_ref()
            .map(|l| l.as_str())
            .unwrap_or("und")
            .to_string()
    }

    /// Get audio channel description (e.g., "Stereo", "5.1")
    pub fn audio_channels_display(&self) -> Option<String> {
        self.audio_channels.map(|ch| match ch {
            1 => "Mono".to_string(),
            2 => "Stereo".to_string(),
            6 => "5.1".to_string(),
            8 => "7.1".to_string(),
            _ => format!("{} channels", ch),
        })
    }
}

/// Track structure representing a media track from a source file
#[derive(Debug, Clone)]
pub struct Track {
    /// Source identifier (e.g., "REF", "SEC", "TER")
    pub source: String,

    /// Track ID (mkvmerge track id)
    pub id: i32,

    /// Track type
    pub track_type: TrackType,

    /// Stream properties
    pub props: StreamProps,
}

impl Track {
    /// Create a new track
    pub fn new(source: String, id: i32, track_type: TrackType, props: StreamProps) -> Self {
        Self {
            source,
            id,
            track_type,
            props,
        }
    }

    /// Get compact display string for UI
    ///
    /// Format: "[A-2] A_EAC3 (eng) '5.1'"
    pub fn display_compact(&self) -> String {
        let prefix = self.track_type.prefix();
        let codec = self.props.codec_display();
        let lang = self.props.lang_display();
        let name = self
            .props
            .name
            .as_ref()
            .map(|n| format!(" '{}'", n))
            .unwrap_or_default();

        format!("[{}-{}] {} ({}){}", prefix, self.id, codec, lang, name)
    }

    /// Get detailed display string
    pub fn display_detailed(&self) -> String {
        let mut parts = vec![self.display_compact()];

        if self.track_type == TrackType::Audio {
            if let Some(channels) = self.props.audio_channels_display() {
                parts.push(channels);
            }
            if let Some(freq) = self.props.audio_sampling_frequency {
                parts.push(format!("{}Hz", freq));
            }
        } else if self.track_type == TrackType::Video {
            if let (Some(w), Some(h)) = (self.props.pixel_width, self.props.pixel_height) {
                parts.push(format!("{}x{}", w, h));
            }
        }

        parts.join(" • ")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_stream_props_default() {
        let props = StreamProps::default();
        assert_eq!(props.default, false);
        assert_eq!(props.forced, false);
        assert_eq!(props.codec_id, None);
    }

    #[test]
    fn test_audio_channels_display() {
        let mut props = StreamProps::default();
        props.audio_channels = Some(2);
        assert_eq!(props.audio_channels_display(), Some("Stereo".to_string()));

        props.audio_channels = Some(6);
        assert_eq!(props.audio_channels_display(), Some("5.1".to_string()));
    }

    #[test]
    fn test_track_display() {
        let props = StreamProps {
            codec_id: Some("A_EAC3".to_string()),
            lang: Some("eng".to_string()),
            name: Some("5.1".to_string()),
            audio_channels: Some(6),
            ..Default::default()
        };

        let track = Track::new("SEC".to_string(), 2, TrackType::Audio, props);
        let display = track.display_compact();
        assert!(display.contains("[A-2]"));
        assert!(display.contains("A_EAC3"));
        assert!(display.contains("(eng)"));
        assert!(display.contains("'5.1'"));
    }
}
