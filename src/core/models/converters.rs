//! Type converters and utilities

use super::enums::TrackType;

/// Normalize language code to 3-letter ISO 639-2 format
///
/// Converts common 2-letter codes to 3-letter equivalents used by mkvmerge.
pub fn normalize_language_code(code: &str) -> String {
    let code_lower = code.to_lowercase();

    match code_lower.as_str() {
        "en" => "eng".to_string(),
        "ja" | "jp" => "jpn".to_string(),
        "zh" | "cn" => "zho".to_string(),
        "ko" | "kr" => "kor".to_string(),
        "fr" => "fra".to_string(),
        "de" => "deu".to_string(),
        "es" => "spa".to_string(),
        "it" => "ita".to_string(),
        "pt" => "por".to_string(),
        "ru" => "rus".to_string(),
        "ar" => "ara".to_string(),
        // If already 3 letters or unknown, pass through
        _ if code_lower.len() == 3 => code_lower,
        _ => code.to_string(),
    }
}

/// Get file extension for a track based on codec ID
///
/// Maps codec IDs to appropriate file extensions for extraction.
pub fn get_extension_for_codec(codec_id: &str, track_type: TrackType) -> &'static str {
    let codec_lower = codec_id.to_lowercase();

    match track_type {
        TrackType::Video => {
            if codec_lower.contains("hevc") || codec_lower.contains("h265") {
                ".h265"
            } else if codec_lower.contains("avc") || codec_lower.contains("h264") {
                ".h264"
            } else if codec_lower.contains("mpeg1") || codec_lower.contains("mpeg2") {
                ".mpg"
            } else if codec_lower.contains("vp9") {
                ".vp9"
            } else if codec_lower.contains("av1") {
                ".av1"
            } else {
                ".bin"
            }
        }
        TrackType::Audio => {
            if codec_lower.contains("truehd") {
                ".thd"
            } else if codec_lower.contains("eac3") || codec_lower.contains("e-ac3") {
                ".eac3"
            } else if codec_lower.contains("ac3") {
                ".ac3"
            } else if codec_lower.contains("dts") {
                ".dts"
            } else if codec_lower.contains("aac") {
                ".aac"
            } else if codec_lower.contains("flac") {
                ".flac"
            } else if codec_lower.contains("opus") {
                ".opus"
            } else if codec_lower.contains("vorbis") {
                ".ogg"
            } else if codec_lower.contains("pcm") {
                ".wav"
            } else {
                ".bin"
            }
        }
        TrackType::Subtitles => {
            if codec_lower.contains("ass") {
                ".ass"
            } else if codec_lower.contains("ssa") {
                ".ssa"
            } else if codec_lower.contains("utf8") || codec_lower.contains("srt") {
                ".srt"
            } else if codec_lower.contains("pgs") || codec_lower.contains("hdmv") {
                ".sup"
            } else if codec_lower.contains("vobsub") {
                ".sub"
            } else {
                ".sub"
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_language_normalization() {
        assert_eq!(normalize_language_code("en"), "eng");
        assert_eq!(normalize_language_code("ja"), "jpn");
        assert_eq!(normalize_language_code("jp"), "jpn");
        assert_eq!(normalize_language_code("eng"), "eng");
        assert_eq!(normalize_language_code("und"), "und");
    }

    #[test]
    fn test_extension_mapping() {
        assert_eq!(
            get_extension_for_codec("V_MPEG4/ISO/AVC", TrackType::Video),
            ".h264"
        );
        assert_eq!(
            get_extension_for_codec("V_MPEGH/ISO/HEVC", TrackType::Video),
            ".h265"
        );
        assert_eq!(
            get_extension_for_codec("A_EAC3", TrackType::Audio),
            ".eac3"
        );
        assert_eq!(get_extension_for_codec("A_AC3", TrackType::Audio), ".ac3");
        assert_eq!(
            get_extension_for_codec("S_TEXT/UTF8", TrackType::Subtitles),
            ".srt"
        );
        assert_eq!(
            get_extension_for_codec("S_TEXT/ASS", TrackType::Subtitles),
            ".ass"
        );
    }
}
