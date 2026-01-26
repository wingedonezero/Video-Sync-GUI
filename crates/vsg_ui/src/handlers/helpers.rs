//! Helper functions for handler modules.

use std::path::PathBuf;
use std::process::Command as StdCommand;

use vsg_core::config::Settings;
use vsg_core::logging::{JobLogger, LogConfig};
use vsg_core::models::JobSpec;
use vsg_core::jobs::ManualLayout;
use vsg_core::orchestrator::{AnalyzeStep, Context, JobState, Pipeline, create_standard_pipeline};

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

/// Probe tracks from a video file using mkvmerge -J.
pub fn probe_tracks(path: &PathBuf) -> Vec<TrackInfo> {
    let output = StdCommand::new("mkvmerge").arg("-J").arg(path).output();

    match output {
        Ok(output) if output.status.success() => {
            parse_mkvmerge_json(&String::from_utf8_lossy(&output.stdout))
        }
        _ => {
            vec![
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
            ]
        }
    }
}

/// Parse mkvmerge -J JSON output.
/// Produces Qt-style summaries: [TYPE-ID] CODEC (lang) | details
fn parse_mkvmerge_json(json_str: &str) -> Vec<TrackInfo> {
    let json: serde_json::Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };

    let mut tracks = Vec::new();

    if let Some(track_array) = json.get("tracks").and_then(|t| t.as_array()) {
        for track in track_array {
            let track_type = track
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("unknown")
                .to_string();

            let codec = track
                .get("codec")
                .and_then(|c| c.as_str())
                .unwrap_or("Unknown");

            let properties = track.get("properties");

            // Get raw language code (e.g., "jpn", "eng", "und")
            let lang_code = properties
                .and_then(|p| p.get("language"))
                .and_then(|l| l.as_str())
                .map(|s| s.to_string());

            let codec_id = properties
                .and_then(|p| p.get("codec_id"))
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();

            let is_default = properties
                .and_then(|p| p.get("default_track"))
                .and_then(|d| d.as_bool())
                .unwrap_or(false);

            let is_forced = properties
                .and_then(|p| p.get("forced_track"))
                .and_then(|f| f.as_bool())
                .unwrap_or(false);

            let track_id = track
                .get("id")
                .and_then(|id| id.as_u64())
                .unwrap_or(0) as usize;

            // Type prefix for track ID display (V=video, A=audio, S=subtitles)
            let type_prefix = match track_type.as_str() {
                "video" => "V",
                "audio" => "A",
                "subtitles" => "S",
                _ => "?",
            };

            // Build Qt-style summary: [TYPE-ID] CODEC (lang) | details
            let summary = match track_type.as_str() {
                "video" => {
                    let dimensions = properties
                        .and_then(|p| p.get("pixel_dimensions"))
                        .and_then(|d| d.as_str())
                        .unwrap_or("");
                    let fps = properties
                        .and_then(|p| p.get("default_duration"))
                        .and_then(|d| d.as_u64())
                        .map(|ns| 1_000_000_000.0 / ns as f64)
                        .map(|fps| format!("{:.3} fps", fps))
                        .unwrap_or_default();
                    let lang = lang_code.as_deref().unwrap_or("und");

                    if fps.is_empty() {
                        format!("[{}-{}] {} ({}) | {}", type_prefix, track_id, codec, lang, dimensions)
                    } else {
                        format!("[{}-{}] {} ({}) | {}, {}", type_prefix, track_id, codec, lang, dimensions, fps)
                    }
                }
                "audio" => {
                    let channels = properties
                        .and_then(|p| p.get("audio_channels"))
                        .and_then(|c| c.as_u64())
                        .unwrap_or(2);
                    let sample_rate = properties
                        .and_then(|p| p.get("audio_sampling_frequency"))
                        .and_then(|f| f.as_u64())
                        .unwrap_or(48000);
                    let channel_str = channel_layout(channels as u8);
                    let lang = lang_code.as_deref().unwrap_or("und");

                    format!("[{}-{}] {} ({}) | {} Hz, {}", type_prefix, track_id, codec, lang, sample_rate, channel_str)
                }
                "subtitles" => {
                    let lang = lang_code.as_deref().unwrap_or("und");
                    format!("[{}-{}] {} ({})", type_prefix, track_id, codec, lang)
                }
                _ => format!("[?-{}] {}", track_id, codec),
            };

            let mut badges_list = Vec::new();
            if is_default {
                badges_list.push("Default");
            }
            if is_forced {
                badges_list.push("Forced");
            }

            tracks.push(TrackInfo {
                track_id,
                track_type,
                codec_id,
                language: lang_code,
                summary,
                badges: badges_list.join(" | "),
            });
        }
    }

    tracks
}

/// Convert channel count to display string.
fn channel_layout(channels: u8) -> String {
    match channels {
        1 => "Mono".to_string(),
        2 => "Stereo".to_string(),
        6 => "5.1".to_string(),
        8 => "7.1".to_string(),
        _ => format!("{} ch", channels),
    }
}

/// Run analysis only pipeline (async wrapper).
pub async fn run_analyze_only(
    job_spec: JobSpec,
    settings: Settings,
) -> Result<(Option<i64>, Option<i64>), String> {
    tokio::task::spawn_blocking(move || {
        let job_name = job_spec
            .sources
            .get("Source 1")
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
                    let d2 = analysis.delays.source_delays_ms.get("Source 2").copied();
                    let d3 = analysis.delays.source_delays_ms.get("Source 3").copied();
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
    sources: std::collections::HashMap<String, PathBuf>,
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
                    map.insert("source".to_string(), serde_json::json!(track.source_key));
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
