//! Track and structure signature generation for layout compatibility.
//!
//! Signatures are used to determine if a layout from one job can be
//! safely copied to another job with the same file structure.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::models::SourceIndex;

/// Track information for signature generation.
/// This is a simplified view of track data used for comparison.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrackSignatureInfo {
    pub id: usize,
    pub track_type: String, // "video", "audio", "subtitles"
    pub codec_id: String,
    pub language: String,
    pub channels: Option<u8>,
    pub sample_rate: Option<u32>,
}

/// Track signature for comparing track configurations.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrackSignature {
    /// Count of tracks by source and type (e.g., "Source 1_audio" -> 2)
    pub signature: HashMap<String, usize>,
    /// Whether this is a strict signature (includes codec/lang/position)
    pub strict: bool,
    /// Total number of tracks
    pub total_tracks: usize,
}

/// Per-source structure information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceStructure {
    pub video: Vec<TrackStructureEntry>,
    pub audio: Vec<TrackStructureEntry>,
    pub subtitles: Vec<TrackStructureEntry>,
}

/// Single track entry in structure signature.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrackStructureEntry {
    pub id: usize,
    pub codec_id: String,
    pub lang: String,
}

/// Structure signature for exact compatibility checking.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureSignature {
    /// Detailed structure per source
    pub structure: HashMap<SourceIndex, SourceStructure>,
    /// SHA256 hash of the structure for quick comparison
    pub hash: String,
}

/// Generator for track and structure signatures.
#[derive(Debug, Default)]
pub struct SignatureGenerator;

impl SignatureGenerator {
    pub fn new() -> Self {
        Self
    }

    /// Generate a track signature from track info.
    ///
    /// # Arguments
    /// * `track_info` - Map of source index to list of tracks
    /// * `strict` - If true, includes codec/lang/position for stricter matching
    pub fn generate_track_signature(
        &self,
        track_info: &HashMap<SourceIndex, Vec<TrackSignatureInfo>>,
        strict: bool,
    ) -> TrackSignature {
        let mut signature: HashMap<String, usize> = HashMap::new();

        if !strict {
            // Non-strict: count tracks by source and type
            for (_source, tracks) in track_info {
                for track in tracks {
                    let key = format!("{}_{}", track.track_type, track.track_type);
                    *signature.entry(key).or_insert(0) += 1;
                }
            }
        } else {
            // Strict: include codec, language, and position
            let mut type_counters: HashMap<String, usize> = HashMap::new();

            for (source, tracks) in track_info {
                for track in tracks {
                    let position = *type_counters.get(&track.track_type).unwrap_or(&0);
                    type_counters.insert(track.track_type.clone(), position + 1);

                    let key = format!(
                        "{}_{}_{}_{}_{}",
                        source.display_name(),
                        track.track_type,
                        track.codec_id.to_lowercase(),
                        track.language.to_lowercase(),
                        position
                    );
                    *signature.entry(key).or_insert(0) += 1;
                }
            }
        }

        let total_tracks = signature.values().sum();

        TrackSignature {
            signature,
            strict,
            total_tracks,
        }
    }

    /// Generate a structure signature for exact compatibility checking.
    ///
    /// CRITICAL: Includes track IDs to prevent layouts from being applied
    /// to files where tracks are in different orders.
    pub fn generate_structure_signature(
        &self,
        track_info: &HashMap<SourceIndex, Vec<TrackSignatureInfo>>,
    ) -> StructureSignature {
        let mut structure: HashMap<SourceIndex, SourceStructure> = HashMap::new();

        // Process sources in sorted order for consistent hashing
        let mut sorted_sources: Vec<_> = track_info.iter().collect();
        sorted_sources.sort_by_key(|(k, _)| k.index());

        for (source, tracks) in sorted_sources {
            let mut source_structure = SourceStructure {
                video: Vec::new(),
                audio: Vec::new(),
                subtitles: Vec::new(),
            };

            for track in tracks {
                let entry = TrackStructureEntry {
                    id: track.id,
                    codec_id: track.codec_id.clone(),
                    lang: track.language.clone(),
                };

                match track.track_type.as_str() {
                    "video" => source_structure.video.push(entry),
                    "audio" => source_structure.audio.push(entry),
                    "subtitles" => source_structure.subtitles.push(entry),
                    _ => {}
                }
            }

            structure.insert(*source, source_structure);
        }

        // Generate SHA256 hash of the structure
        let structure_json = serde_json::to_string(&structure).unwrap_or_default();
        let mut hasher = Sha256::new();
        hasher.update(structure_json.as_bytes());
        let hash = format!("{:x}", hasher.finalize());

        StructureSignature { structure, hash }
    }

    /// Check if two structure signatures are compatible.
    /// Structures are compatible if their hashes match exactly.
    pub fn structures_are_compatible(
        &self,
        struct1: &StructureSignature,
        struct2: &StructureSignature,
    ) -> bool {
        !struct1.hash.is_empty() && struct1.hash == struct2.hash
    }
}

/// Convert probe result tracks to signature info format.
pub fn tracks_to_signature_info(
    _source: SourceIndex,
    tracks: &[crate::extraction::TrackInfo],
) -> Vec<TrackSignatureInfo> {
    tracks
        .iter()
        .map(|t| TrackSignatureInfo {
            id: t.id,
            track_type: match t.track_type {
                crate::extraction::TrackType::Video => "video".to_string(),
                crate::extraction::TrackType::Audio => "audio".to_string(),
                crate::extraction::TrackType::Subtitles => "subtitles".to_string(),
            },
            codec_id: t.codec_id.clone(),
            language: t.language.clone().unwrap_or_else(|| "und".to_string()),
            channels: t.properties.channels,
            sample_rate: t.properties.sample_rate,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn structure_signature_hash_matches() {
        let gen = SignatureGenerator::new();

        let mut track_info1: HashMap<SourceIndex, Vec<TrackSignatureInfo>> = HashMap::new();
        track_info1.insert(
            SourceIndex::source1(),
            vec![
                TrackSignatureInfo {
                    id: 0,
                    track_type: "video".to_string(),
                    codec_id: "V_MPEG4/ISO/AVC".to_string(),
                    language: "und".to_string(),
                    channels: None,
                    sample_rate: None,
                },
                TrackSignatureInfo {
                    id: 1,
                    track_type: "audio".to_string(),
                    codec_id: "A_FLAC".to_string(),
                    language: "jpn".to_string(),
                    channels: Some(2u8),
                    sample_rate: Some(48000),
                },
            ],
        );

        // Same structure
        let mut track_info2 = track_info1.clone();

        let sig1 = gen.generate_structure_signature(&track_info1);
        let sig2 = gen.generate_structure_signature(&track_info2);

        assert!(gen.structures_are_compatible(&sig1, &sig2));

        // Different structure (different track ID)
        track_info2.get_mut(&SourceIndex::source1()).unwrap()[1].id = 2;
        let sig3 = gen.generate_structure_signature(&track_info2);

        assert!(!gen.structures_are_compatible(&sig1, &sig3));
    }
}
