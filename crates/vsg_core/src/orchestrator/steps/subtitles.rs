//! Subtitles step - processes subtitle tracks (sync adjustment).
//!
//! Processes extracted subtitle tracks by applying sync adjustments
//! based on the configured sync mode (time-based or video-verified).

use std::collections::HashMap;
use std::path::PathBuf;

use crate::config::SubtitleSettings;
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, JobState, StepOutcome, SubtitlesOutput};
use crate::subtitles::{
    create_sync_mode, parse_file, write_file, SyncConfig, SyncModeType, VideoVerifiedConfig,
    WriteOptions,
};

/// Subtitles step for processing subtitle tracks.
///
/// Applies sync adjustments to extracted subtitle files based on
/// analysis results and configured sync mode.
pub struct SubtitlesStep;

impl SubtitlesStep {
    pub fn new() -> Self {
        Self
    }

    /// Build VideoVerifiedConfig from SubtitleSettings.
    fn build_video_verified_config(settings: &SubtitleSettings) -> VideoVerifiedConfig {
        VideoVerifiedConfig {
            num_checkpoints: settings.num_checkpoints as usize,
            search_range_frames: settings.search_range_frames,
            sequence_length: settings.sequence_length as usize,
            hash_threshold: settings.hash_threshold,
            frame_audit_enabled: settings.frame_audit_enabled,
            hash_algorithm: settings.hash_algorithm,
            hash_size: settings.hash_size as u8,
            comparison_method: settings.comparison_method,
            indexer_backend: settings.indexer_backend,
            // Interlaced settings
            interlaced_handling_enabled: settings.interlaced_handling_enabled,
            interlaced_hash_threshold: settings.interlaced_hash_threshold,
            interlaced_deinterlace_method: settings.deinterlace_method,
            ..Default::default()
        }
    }

    /// Get source name from track key (e.g., "Source 2:subtitle:0" -> "Source 2").
    fn source_from_track_key(track_key: &str) -> String {
        if let Some(colon_pos) = track_key.find(':') {
            track_key[..colon_pos].to_string()
        } else {
            "Source 1".to_string()
        }
    }

    /// Check if a track key represents a subtitle track.
    fn is_subtitle_track(track_key: &str) -> bool {
        track_key.contains(":subtitle:") || track_key.contains(":subtitles:")
    }

    /// Process a single subtitle track.
    fn process_track(
        &self,
        ctx: &Context,
        track_key: &str,
        input_path: &PathBuf,
        delays: &crate::models::Delays,
    ) -> StepResult<PathBuf> {
        let source = Self::source_from_track_key(track_key);
        let settings = &ctx.settings.subtitle;

        ctx.logger.info(&format!(
            "[SubtitleStep] Processing track: {} (source: {})",
            track_key, source
        ));

        // Get delay for this source
        let total_delay_ms = delays
            .raw_source_delays_ms
            .get(&source)
            .copied()
            .unwrap_or(0.0);
        let global_shift_ms = delays.raw_global_shift_ms;

        ctx.logger.info(&format!(
            "[SubtitleStep] Delay: {:.3}ms (global shift: {:.3}ms)",
            total_delay_ms, global_shift_ms
        ));

        // Parse the subtitle file
        ctx.logger.info(&format!(
            "[SubtitleStep] Parsing: {}",
            input_path.display()
        ));
        let mut subtitle_data = parse_file(input_path).map_err(|e| {
            StepError::other(format!("Failed to parse subtitle file: {}", e))
        })?;

        ctx.logger.info(&format!(
            "[SubtitleStep] Loaded {} events",
            subtitle_data.events.len()
        ));

        // Build sync config
        let mut sync_config = match settings.sync_mode {
            SyncModeType::TimeBased => SyncConfig::time_based(total_delay_ms, global_shift_ms),
            SyncModeType::VideoVerified => {
                // Get video paths for video-verified mode
                let source_video = ctx.source_path(&source).cloned();
                let target_video = ctx.primary_source().cloned();

                if source_video.is_none() || target_video.is_none() {
                    ctx.logger.warn(
                        "[SubtitleStep] Video paths not available, falling back to time-based sync",
                    );
                    SyncConfig::time_based(total_delay_ms, global_shift_ms)
                } else {
                    SyncConfig::video_verified(
                        total_delay_ms,
                        global_shift_ms,
                        source_video.unwrap(),
                        target_video.unwrap(),
                    )
                }
            }
        };

        // Apply video-verified settings if applicable
        if settings.sync_mode == SyncModeType::VideoVerified {
            sync_config.video_verified = Self::build_video_verified_config(settings);
        }

        // Create and apply sync mode
        let sync_mode = create_sync_mode(settings.sync_mode);
        ctx.logger.info(&format!(
            "[SubtitleStep] Applying sync mode: {}",
            settings.sync_mode.name()
        ));

        let result = sync_mode.apply(&mut subtitle_data, &sync_config).map_err(|e| {
            StepError::other(format!("Sync failed: {}", e))
        })?;

        ctx.logger.info(&format!(
            "[SubtitleStep] Sync complete: {} events affected, adjustment: {:.3}ms",
            result.events_affected, result.final_offset_ms
        ));

        // Generate output path
        let input_filename = input_path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("subtitle");
        let output_filename = format!("synced_{}", input_filename);
        let output_path = ctx.work_dir.join(&output_filename);

        // Write output file
        let write_options = WriteOptions::default();
        write_file(&subtitle_data, &output_path, &write_options).map_err(|e| {
            StepError::other(format!("Failed to write subtitle file: {}", e))
        })?;

        ctx.logger.info(&format!(
            "[SubtitleStep] Written: {}",
            output_path.display()
        ));

        Ok(output_path)
    }
}

impl Default for SubtitlesStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for SubtitlesStep {
    fn name(&self) -> &str {
        "Subtitles"
    }

    fn description(&self) -> &str {
        "Process subtitle tracks (sync adjustment)"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Check if we have analysis results (needed for delays)
        // Note: This is soft - we can still process without delays (0 offset)
        if ctx.settings.subtitle.sync_mode == SyncModeType::VideoVerified {
            // Video-verified needs source videos
            if ctx.job_spec.sources.is_empty() {
                return Err(StepError::InvalidInput(
                    "Video-verified sync requires source videos".to_string(),
                ));
            }
        }
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.info("[SubtitleStep] Starting subtitle processing");

        // Get extracted tracks
        let extract_output = match &state.extract {
            Some(e) => e,
            None => {
                ctx.logger
                    .info("[SubtitleStep] No extraction output - skipping");
                state.subtitles = Some(SubtitlesOutput::default());
                return Ok(StepOutcome::Skipped("No extracted tracks".to_string()));
            }
        };

        // Get delays (default to empty if no analysis)
        let delays = state.delays().cloned().unwrap_or_default();

        // Find subtitle tracks
        let subtitle_tracks: Vec<_> = extract_output
            .tracks
            .iter()
            .filter(|(key, _)| Self::is_subtitle_track(key))
            .collect();

        if subtitle_tracks.is_empty() {
            ctx.logger
                .info("[SubtitleStep] No subtitle tracks to process - skipping");
            state.subtitles = Some(SubtitlesOutput::default());
            return Ok(StepOutcome::Skipped("No subtitle tracks".to_string()));
        }

        ctx.logger.info(&format!(
            "[SubtitleStep] Found {} subtitle track(s) to process",
            subtitle_tracks.len()
        ));

        // Process each subtitle track
        let mut processed_files = HashMap::new();
        let mut errors = Vec::new();

        for (track_key, input_path) in subtitle_tracks {
            match self.process_track(ctx, track_key, input_path, &delays) {
                Ok(output_path) => {
                    processed_files.insert(track_key.clone(), output_path);
                }
                Err(e) => {
                    ctx.logger.warn(&format!(
                        "[SubtitleStep] Failed to process {}: {}",
                        track_key, e
                    ));
                    errors.push((track_key.clone(), e));
                }
            }
        }

        // Record results
        state.subtitles = Some(SubtitlesOutput {
            processed_files,
            ocr_performed: false,
        });

        if errors.is_empty() {
            ctx.logger.info("[SubtitleStep] All subtitle tracks processed successfully");
            Ok(StepOutcome::Success)
        } else {
            // Partial success - some tracks failed
            ctx.logger.warn(&format!(
                "[SubtitleStep] {} track(s) failed to process",
                errors.len()
            ));
            Ok(StepOutcome::Success)
        }
    }

    fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
        // Subtitles are optional
        Ok(())
    }

    fn is_optional(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn subtitles_step_has_correct_name() {
        let step = SubtitlesStep::new();
        assert_eq!(step.name(), "Subtitles");
    }

    #[test]
    fn subtitles_step_is_optional() {
        let step = SubtitlesStep::new();
        assert!(step.is_optional());
    }

    #[test]
    fn test_source_from_track_key() {
        assert_eq!(
            SubtitlesStep::source_from_track_key("Source 2:subtitle:0"),
            "Source 2"
        );
        assert_eq!(
            SubtitlesStep::source_from_track_key("Source 1:subtitle:1"),
            "Source 1"
        );
        assert_eq!(
            SubtitlesStep::source_from_track_key("unknown"),
            "Source 1"
        );
    }

    #[test]
    fn test_is_subtitle_track() {
        assert!(SubtitlesStep::is_subtitle_track("Source 1:subtitle:0"));
        assert!(SubtitlesStep::is_subtitle_track("Source 2:subtitles:1"));
        assert!(!SubtitlesStep::is_subtitle_track("Source 1:audio:0"));
        assert!(!SubtitlesStep::is_subtitle_track("Source 1:video:0"));
    }
}
