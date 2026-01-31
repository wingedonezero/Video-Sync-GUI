//! Helper functions for handler modules.

use std::path::PathBuf;

use vsg_core::config::Settings;
use vsg_core::extraction::{
    build_track_description, get_detailed_stream_info, probe_file, TrackType,
};
use vsg_core::jobs::ManualLayout;
use vsg_core::logging::{JobLogger, LogConfig};
use vsg_core::models::{JobSpec, SourceIndex};
use vsg_core::orchestrator::{create_standard_pipeline, AnalyzeStep, Context, JobState, Pipeline};

/// Track info from probing.
pub struct TrackInfo {
    pub track_id: usize,
    pub track_type: String,
    pub codec_id: String,
    pub language: Option<String>,
    pub summary: String,
    pub badges: String,
}

/// Clean up a file URL (from drag-drop) to a regular path.
pub fn clean_file_url(url: &str) -> String {
    let first_uri = url
        .lines()
        .map(|line| line.trim())
        .find(|line| !line.is_empty() && !line.starts_with('#'))
        .unwrap_or("");

    let path = if first_uri.starts_with("file://") {
        let without_prefix = &first_uri[7..];
        percent_decode(without_prefix)
    } else {
        first_uri.to_string()
    };

    path.trim().to_string()
}

/// Simple percent decoding for file paths.
fn percent_decode(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();

    while let Some(c) = chars.next() {
        if c == '%' {
            let hex: String = chars.by_ref().take(2).collect();
            if hex.len() == 2 {
                if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                    result.push(byte as char);
                    continue;
                }
            }
            result.push('%');
            result.push_str(&hex);
        } else {
            result.push(c);
        }
    }

    result
}

/// Probe tracks from a video file using vsg_core extraction module.
///
/// Uses mkvmerge -J for basic info and optionally ffprobe for detailed info
/// (bitrate, profile, HDR, Dolby Vision detection).
pub fn probe_tracks(path: &PathBuf) -> Vec<TrackInfo> {
    // Use core library's probe_file
    let probe_result = match probe_file(path) {
        Ok(result) => result,
        Err(_) => {
            // Fallback for probe failure
            return vec![
                TrackInfo {
                    track_id: 0,
                    track_type: "video".to_string(),
                    codec_id: String::new(),
                    language: None,
                    summary: "[V-0] Video Track (probe failed)".to_string(),
                    badges: String::new(),
                },
                TrackInfo {
                    track_id: 1,
                    track_type: "audio".to_string(),
                    codec_id: String::new(),
                    language: None,
                    summary: "[A-1] Audio Track (probe failed)".to_string(),
                    badges: String::new(),
                },
            ];
        }
    };

    // Get detailed ffprobe info (optional enhancement)
    let ffprobe_info = get_detailed_stream_info(path).ok();

    // Build track info for each track
    let mut tracks = Vec::new();
    let mut video_idx = 0usize;
    let mut audio_idx = 0usize;
    let mut sub_idx = 0usize;

    for track in &probe_result.tracks {
        let (type_prefix, stream_idx) = match track.track_type {
            TrackType::Video => {
                let idx = video_idx;
                video_idx += 1;
                ("V", idx)
            }
            TrackType::Audio => {
                let idx = audio_idx;
                audio_idx += 1;
                ("A", idx)
            }
            TrackType::Subtitles => {
                let idx = sub_idx;
                sub_idx += 1;
                ("S", idx)
            }
        };

        // Get ffprobe info for this stream if available
        // ffprobe indexes streams globally, so we need to find the right one
        let fp_info = ffprobe_info.as_ref().and_then(|info| {
            // Find the matching ffprobe stream by type and relative index
            let codec_type = match track.track_type {
                TrackType::Video => "video",
                TrackType::Audio => "audio",
                TrackType::Subtitles => "subtitle",
            };

            // Sort by index to ensure correct ordering (HashMap iteration is unordered)
            let mut streams_of_type: Vec<_> = info
                .values()
                .filter(|s| s.codec_type == codec_type)
                .collect();
            streams_of_type.sort_by_key(|s| s.index);

            streams_of_type.get(stream_idx).copied()
        });

        // Build rich description using core library
        let description = build_track_description(track, fp_info);

        // Format as [TYPE-ID] description
        let summary = format!("[{}-{}] {}", type_prefix, track.id, description);

        // Build badges
        let mut badges_list = Vec::new();
        if track.is_default {
            badges_list.push("Default");
        }
        if track.is_forced {
            badges_list.push("Forced");
        }
        if track.container_delay_ms != 0 {
            badges_list.push("Has Delay");
        }

        let track_type_str = match track.track_type {
            TrackType::Video => "video",
            TrackType::Audio => "audio",
            TrackType::Subtitles => "subtitles",
        };

        tracks.push(TrackInfo {
            track_id: track.id,
            track_type: track_type_str.to_string(),
            codec_id: track.codec_id.clone(),
            language: track.language.clone(),
            summary,
            badges: badges_list.join(" | "),
        });
    }

    tracks
}

/// Run analysis only pipeline (async wrapper).
pub async fn run_analyze_only(
    job_spec: JobSpec,
    settings: Settings,
) -> Result<(Option<i64>, Option<i64>), String> {
    tokio::task::spawn_blocking(move || {
        let job_name = job_spec
            .sources
            .get(&SourceIndex::source1())
            .map(|p| {
                p.file_stem()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_else(|| "job".to_string())
            })
            .unwrap_or_else(|| "job".to_string());

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let work_dir =
            PathBuf::from(&settings.paths.temp_root).join(format!("orch_{}_{}", job_name, timestamp));
        let output_dir = PathBuf::from(&settings.paths.output_folder);

        let log_config = LogConfig {
            compact: settings.logging.compact,
            progress_step: settings.logging.progress_step,
            error_tail: settings.logging.error_tail as usize,
            ..LogConfig::default()
        };

        let logger = match JobLogger::new(&job_name, &output_dir, log_config, None) {
            Ok(l) => std::sync::Arc::new(l),
            Err(e) => return Err(format!("Failed to create logger: {}", e)),
        };

        let ctx = Context::new(
            job_spec,
            settings,
            &job_name,
            work_dir,
            output_dir,
            logger.clone(),
        );

        let mut state = JobState::new(&job_name);
        let pipeline = Pipeline::new().with_step(AnalyzeStep::new());

        match pipeline.run(&ctx, &mut state) {
            Ok(_) => {
                let (delay2, delay3) = if let Some(ref analysis) = state.analysis {
                    let d2 = analysis.delays.get_delay_ms(SourceIndex::source2());
                    let d3 = analysis.delays.get_delay_ms(SourceIndex::new(2)); // Source 3
                    (d2, d3)
                } else {
                    (None, None)
                };
                Ok((delay2, delay3))
            }
            Err(e) => Err(format!("Pipeline failed: {}", e)),
        }
    })
    .await
    .map_err(|e| format!("Task panicked: {}", e))?
}

/// Run a full job pipeline (async wrapper).
///
/// This runs the complete pipeline: Analyze -> Extract -> Attachments -> Chapters ->
/// Subtitles -> AudioCorrection -> Mux
pub async fn run_job_pipeline(
    job_name: String,
    sources: std::collections::HashMap<SourceIndex, PathBuf>,
    layout: Option<ManualLayout>,
    settings: Settings,
) -> Result<PathBuf, String> {
    tokio::task::spawn_blocking(move || {
        // Build job spec
        let mut job_spec = JobSpec::new(sources);

        // Convert layout to manual_layout format (Vec<HashMap<String, serde_json::Value>>)
        if let Some(layout) = layout {
            let manual_layout: Vec<std::collections::HashMap<String, serde_json::Value>> = layout
                .final_tracks
                .iter()
                .map(|track| {
                    let mut map = std::collections::HashMap::new();
                    map.insert("id".to_string(), serde_json::json!(track.track_id));
                    map.insert("source".to_string(), serde_json::json!(track.source_ref.display_name()));
                    map.insert(
                        "type".to_string(),
                        serde_json::json!(match track.track_type {
                            vsg_core::models::TrackType::Video => "video",
                            vsg_core::models::TrackType::Audio => "audio",
                            vsg_core::models::TrackType::Subtitles => "subtitles",
                        }),
                    );
                    map.insert("is_default".to_string(), serde_json::json!(track.config.is_default));
                    map.insert("is_forced_display".to_string(), serde_json::json!(track.config.is_forced_display));
                    if let Some(ref lang) = track.config.custom_lang {
                        map.insert("custom_lang".to_string(), serde_json::json!(lang));
                    }
                    if let Some(ref name) = track.config.custom_name {
                        map.insert("custom_name".to_string(), serde_json::json!(name));
                    }
                    map
                })
                .collect();
            job_spec.manual_layout = Some(manual_layout);

            // Pass attachment sources from layout to job spec
            job_spec.attachment_sources = layout.attachment_sources.clone();
        }

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let work_dir =
            PathBuf::from(&settings.paths.temp_root).join(format!("job_{}_{}", job_name, timestamp));
        let output_dir = PathBuf::from(&settings.paths.output_folder);

        // Create work directory
        if let Err(e) = std::fs::create_dir_all(&work_dir) {
            return Err(format!("Failed to create work directory: {}", e));
        }

        let log_config = LogConfig {
            compact: settings.logging.compact,
            progress_step: settings.logging.progress_step,
            error_tail: settings.logging.error_tail as usize,
            ..LogConfig::default()
        };

        let logger = match JobLogger::new(&job_name, &output_dir, log_config, None) {
            Ok(l) => std::sync::Arc::new(l),
            Err(e) => return Err(format!("Failed to create logger: {}", e)),
        };

        let ctx = Context::new(
            job_spec,
            settings,
            &job_name,
            work_dir.clone(),
            output_dir.clone(),
            logger.clone(),
        );

        let mut state = JobState::new(&job_name);

        // Create and run the standard pipeline
        let pipeline = create_standard_pipeline();

        match pipeline.run(&ctx, &mut state) {
            Ok(_result) => {
                // Get output path from mux step
                if let Some(ref mux) = state.mux {
                    // Clean up work directory
                    if let Err(e) = std::fs::remove_dir_all(&work_dir) {
                        tracing::warn!("Failed to clean up work directory: {}", e);
                    }
                    Ok(mux.output_path.clone())
                } else {
                    Err("Mux step did not produce output".to_string())
                }
            }
            Err(e) => {
                // Keep work dir for debugging on failure
                Err(format!("Pipeline failed: {}", e))
            }
        }
    })
    .await
    .map_err(|e| format!("Task panicked: {}", e))?
}
