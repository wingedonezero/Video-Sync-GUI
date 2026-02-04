//! Subtitles step - processes subtitle tracks (sync adjustment).
//!
//! Processes extracted subtitle tracks by applying sync adjustments
//! based on the configured sync mode (time-based or video-verified).
//!
//! # Video-Verified Per-Source Processing
//!
//! When video-verified mode is enabled, frame matching is performed ONCE per
//! source (not per track). All subtitle tracks from the same source receive
//! the same video-verified delay. This is correct because:
//! - The delay is a property of the source video, not individual subtitle tracks
//! - Running frame matching once per source is efficient
//! - All tracks from Source 2 should sync the same way to Source 1
//!
//! # Bitmap Subtitle Handling
//!
//! Bitmap formats (VOB/VobSub, PGS) cannot be parsed and modified directly.
//! For these formats, mkvmerge --sync will handle the delay application.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use crate::config::SubtitleSettings;
use crate::models::Delays;
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{
    Context, JobState, StepOutcome, SubtitlesOutput, VideoVerifiedSourceResult,
};
use crate::subtitles::{
    calculate_video_verified_offset, create_sync_mode, parse_file, write_file, SyncConfig,
    SyncModeType, VideoVerifiedConfig, WriteOptions,
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

    /// Check if a file is a bitmap subtitle format (VOB/PGS).
    fn is_bitmap_subtitle(path: &Path) -> bool {
        matches!(
            path.extension().and_then(|e| e.to_str()).map(|s| s.to_lowercase()).as_deref(),
            Some("idx" | "sub" | "sup")
        )
    }

    /// Run video-verified sync ONCE per source that has subtitle tracks.
    ///
    /// This is the per-source pre-processing step. Frame matching is expensive,
    /// so we do it once per source and cache the result for all tracks from
    /// that source.
    fn run_video_verified_per_source(
        &self,
        ctx: &Context,
        delays: &Delays,
        subtitle_tracks: &[(&String, &PathBuf)],
    ) -> HashMap<String, VideoVerifiedSourceResult> {
        let settings = &ctx.settings.subtitle;
        let mut cache = HashMap::new();

        // Find unique sources that have subtitle tracks (excluding Source 1)
        let sources_with_subs: HashSet<String> = subtitle_tracks
            .iter()
            .map(|(key, _)| Self::source_from_track_key(key))
            .filter(|s| s != "Source 1")
            .collect();

        if sources_with_subs.is_empty() {
            ctx.logger.info("[Subtitles] No sources (other than Source 1) with subtitle tracks");
            return cache;
        }

        // Get Source 1 (reference) video path
        let target_video = match ctx.primary_source() {
            Some(p) => p.clone(),
            None => {
                ctx.logger.warn("[Subtitles] Source 1 video not available for frame matching");
                return cache;
            }
        };

        // Log section header (Python-style)
        ctx.logger.info("[VideoVerified] ═══════════════════════════════════════════════════════");
        ctx.logger.info("[VideoVerified] Video-to-Video Frame Alignment");
        ctx.logger.info("[VideoVerified] ═══════════════════════════════════════════════════════");
        ctx.logger.info(&format!(
            "[VideoVerified] Reference: Source 1 ({})",
            target_video.file_name().and_then(|n| n.to_str()).unwrap_or("unknown")
        ));
        ctx.logger.info(&format!(
            "[VideoVerified] Aligning: {} → Source 1",
            sources_with_subs.iter().cloned().collect::<Vec<_>>().join(", ")
        ));

        let vv_config = Self::build_video_verified_config(settings);

        // Process each source
        for source_key in sources_with_subs {
            ctx.logger.info(&format!(
                "\n[VideoVerified] ─── {} vs Source 1 ───",
                source_key
            ));

            // Get source video path
            let source_video = match ctx.source_path(&source_key) {
                Some(p) => p.clone(),
                None => {
                    ctx.logger.warn(&format!(
                        "[VideoVerified] WARNING: No video file for {}, skipping",
                        source_key
                    ));
                    continue;
                }
            };

            // Get delay for this source
            let total_delay_ms = delays
                .raw_source_delays_ms
                .get(&source_key)
                .copied()
                .unwrap_or(0.0);
            let global_shift_ms = delays.raw_global_shift_ms;

            // Create logging closure for the calculation function
            let logger = ctx.logger.clone();
            let log_fn = move |msg: &str| {
                logger.info(msg);
            };

            // Calculate video-verified offset
            match calculate_video_verified_offset(
                &source_video,
                &target_video,
                total_delay_ms,
                global_shift_ms,
                &vv_config,
                log_fn,
            ) {
                Ok(result) => {
                    let symbol = if result.frame_match_success { "✓" } else { "⚠" };
                    ctx.logger.info(&format!(
                        "[VideoVerified] {} {} → Source 1: {:+.3}ms ({} frames, {} verified)",
                        symbol,
                        source_key,
                        result.corrected_delay_ms,
                        result.frame_offset,
                        result.verified_sequences
                    ));

                    // Check if correction differs from audio
                    let diff = result.corrected_delay_ms - total_delay_ms;
                    if diff.abs() > 1.0 {
                        ctx.logger.info(&format!(
                            "[VideoVerified]   Frame correction: {:+.1}ms (was {:+.1}ms)",
                            result.corrected_delay_ms,
                            total_delay_ms
                        ));
                    }

                    cache.insert(
                        source_key.clone(),
                        VideoVerifiedSourceResult {
                            source_key: source_key.clone(),
                            original_delay_ms: total_delay_ms,
                            corrected_delay_ms: result.corrected_delay_ms,
                            frame_offset: result.frame_offset,
                            matched_checkpoints: result.matched_checkpoints,
                            verified_sequences: result.verified_sequences,
                            reason: result.reason,
                        },
                    );
                }
                Err(e) => {
                    ctx.logger.warn(&format!(
                        "[VideoVerified] ✗ {}: ERROR - {}",
                        source_key, e
                    ));
                    // On error, fall back to audio correlation
                    cache.insert(
                        source_key.clone(),
                        VideoVerifiedSourceResult {
                            source_key: source_key.clone(),
                            original_delay_ms: total_delay_ms,
                            corrected_delay_ms: total_delay_ms,
                            frame_offset: 0,
                            matched_checkpoints: 0,
                            verified_sequences: 0,
                            reason: format!("error: {}", e),
                        },
                    );
                }
            }
        }

        ctx.logger.info("\n[VideoVerified] ═══════════════════════════════════════════════════════");
        ctx.logger.info("[VideoVerified] Frame alignment complete");
        ctx.logger.info("[VideoVerified] ═══════════════════════════════════════════════════════\n");

        cache
    }

    /// Process a single text-based subtitle track.
    fn process_text_subtitle(
        &self,
        ctx: &Context,
        track_key: &str,
        input_path: &PathBuf,
        delays: &Delays,
        cached_vv: Option<&VideoVerifiedSourceResult>,
    ) -> StepResult<PathBuf> {
        let source = Self::source_from_track_key(track_key);

        // Determine which delay to use
        let (total_delay_ms, global_shift_ms, delay_source) = if let Some(cached) = cached_vv {
            // Use pre-computed video-verified delay
            ctx.logger.info(&format!(
                "[Sync] Using pre-computed video-verified delay for {}",
                source
            ));
            ctx.logger.info(&format!(
                "[Sync]   Delay: {:+.1}ms (was {:+.1}ms from audio)",
                cached.corrected_delay_ms, cached.original_delay_ms
            ));
            (cached.corrected_delay_ms, 0.0, "video-verified")
        } else if source == "Source 1" {
            // Source 1 is reference - apply delay directly
            let delay = delays.raw_source_delays_ms.get(&source).copied().unwrap_or(0.0);
            ctx.logger.info("[Sync] Source 1 is reference - applying delay directly");
            (delay, delays.raw_global_shift_ms, "reference")
        } else {
            // Time-based mode or no cached result
            let delay = delays.raw_source_delays_ms.get(&source).copied().unwrap_or(0.0);
            (delay, delays.raw_global_shift_ms, "time-based")
        };

        ctx.logger.info(&format!(
            "[Sync] Mode: {} | Delay: {:+.3}ms (global: {:+.3}ms)",
            delay_source, total_delay_ms, global_shift_ms
        ));

        // Parse the subtitle file
        let mut subtitle_data = parse_file(input_path).map_err(|e| {
            StepError::other(format!("Failed to parse subtitle file: {}", e))
        })?;

        ctx.logger.info(&format!(
            "[Sync] Loaded {} events from {}",
            subtitle_data.events.len(),
            input_path.file_name().and_then(|n| n.to_str()).unwrap_or("?")
        ));

        // Build sync config - always use time-based since we pre-computed the delay
        let sync_config = SyncConfig::time_based(total_delay_ms, global_shift_ms);

        // Apply sync (time-based is fine since video-verified already computed the offset)
        let sync_mode = create_sync_mode(SyncModeType::TimeBased);
        let result = sync_mode.apply(&mut subtitle_data, &sync_config).map_err(|e| {
            StepError::other(format!("Sync failed: {}", e))
        })?;

        ctx.logger.info(&format!(
            "[Sync] Applied {:+.1}ms to {} events",
            result.final_offset_ms, result.events_affected
        ));

        // Generate output path
        let input_filename = input_path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("subtitle");
        let output_filename = format!("synced_{}", input_filename);
        let output_path = ctx.work_dir.join(&output_filename);

        // Write output file with configured rounding mode
        let write_options = WriteOptions {
            rounding: ctx.settings.subtitle.rounding_mode,
            ..Default::default()
        };
        write_file(&subtitle_data, &output_path, &write_options).map_err(|e| {
            StepError::other(format!("Failed to write subtitle file: {}", e))
        })?;

        ctx.logger.info(&format!(
            "[Subtitles] Written: {} (rounding: {:?})",
            output_filename, ctx.settings.subtitle.rounding_mode
        ));

        Ok(output_path)
    }

    /// Handle bitmap subtitle track (VOB/PGS).
    ///
    /// Bitmap subtitles can't be parsed and modified - mkvmerge will handle
    /// the delay via --sync flag during muxing.
    ///
    /// - **Time-Based**: Pass through directly, mkvmerge uses audio correlation delay
    /// - **Video-Verified**: Use the pre-computed video-verified delay from cache
    fn handle_bitmap_subtitle(
        &self,
        ctx: &Context,
        track_key: &str,
        input_path: &PathBuf,
        delays: &Delays,
        cached_vv: Option<&VideoVerifiedSourceResult>,
        is_video_verified_mode: bool,
    ) {
        let source = Self::source_from_track_key(track_key);
        let ext = input_path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("?");

        // Get the delay to report (for logging)
        let delay_ms = if let Some(cached) = cached_vv {
            // Video-verified mode with cached result
            ctx.logger.info(&format!(
                "[Subtitles] Bitmap track {} ({}): video-verified delay {:+.1}ms",
                track_key, ext, cached.corrected_delay_ms
            ));
            cached.corrected_delay_ms
        } else if source == "Source 1" {
            // Source 1 is the reference
            let delay = delays.raw_source_delays_ms.get(&source).copied().unwrap_or(0.0);
            ctx.logger.info(&format!(
                "[Subtitles] Bitmap track {} ({}): Source 1 reference (delay {:+.1}ms)",
                track_key, ext, delay
            ));
            delay
        } else if is_video_verified_mode {
            // Video-verified mode but no cache (fallback case)
            let delay = delays.raw_source_delays_ms.get(&source).copied().unwrap_or(0.0);
            ctx.logger.info(&format!(
                "[Subtitles] Bitmap track {} ({}): fallback to audio delay {:+.1}ms",
                track_key, ext, delay
            ));
            delay
        } else {
            // Time-based mode - just pass through with audio delay
            let delay = delays.raw_source_delays_ms.get(&source).copied().unwrap_or(0.0);
            ctx.logger.info(&format!(
                "[Subtitles] Bitmap track {} ({}): pass-through (delay {:+.1}ms)",
                track_key, ext, delay
            ));
            delay
        };

        ctx.logger.info(&format!(
            "[Subtitles]   → mkvmerge --sync with {:+.0}ms",
            delay_ms
        ));
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
        if ctx.settings.subtitle.sync_mode == SyncModeType::VideoVerified {
            if ctx.job_spec.sources.is_empty() {
                return Err(StepError::InvalidInput(
                    "Video-verified sync requires source videos".to_string(),
                ));
            }
        }
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        let settings = &ctx.settings.subtitle;

        ctx.logger.info("[Subtitles] ═══════════════════════════════════════════════════════");
        ctx.logger.info("[Subtitles] Subtitle Processing");
        ctx.logger.info("[Subtitles] ═══════════════════════════════════════════════════════");
        ctx.logger.info(&format!("[Subtitles] Mode: {}", settings.sync_mode.name()));

        // Get extracted tracks
        let extract_output = match &state.extract {
            Some(e) => e,
            None => {
                ctx.logger.info("[Subtitles] No extraction output - skipping");
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
            ctx.logger.info("[Subtitles] No subtitle tracks to process - skipping");
            state.subtitles = Some(SubtitlesOutput::default());
            return Ok(StepOutcome::Skipped("No subtitle tracks".to_string()));
        }

        ctx.logger.info(&format!(
            "[Subtitles] Found {} subtitle track(s)",
            subtitle_tracks.len()
        ));

        // === Per-Source Video-Verified Pre-Processing ===
        // Run frame matching ONCE per source, cache results
        let video_verified_cache = if settings.sync_mode == SyncModeType::VideoVerified {
            self.run_video_verified_per_source(ctx, &delays, &subtitle_tracks)
        } else {
            HashMap::new()
        };

        // === Process Individual Tracks ===
        let mut processed_files = HashMap::new();
        let mut errors = Vec::new();

        for (track_key, input_path) in &subtitle_tracks {
            let source = Self::source_from_track_key(track_key);
            let cached_vv = video_verified_cache.get(&source);

            ctx.logger.info(&format!(
                "\n[Subtitles] ─── {} ───",
                track_key
            ));

            // Check if bitmap format
            if Self::is_bitmap_subtitle(input_path) {
                let is_vv_mode = settings.sync_mode == SyncModeType::VideoVerified;
                self.handle_bitmap_subtitle(ctx, track_key, input_path, &delays, cached_vv, is_vv_mode);
                // Bitmap subs aren't "processed" - mkvmerge handles them
                // We still record them so merge plan knows about them
                processed_files.insert((*track_key).clone(), (*input_path).clone());
                continue;
            }

            // Process text-based subtitle
            match self.process_text_subtitle(ctx, track_key, input_path, &delays, cached_vv) {
                Ok(output_path) => {
                    processed_files.insert((*track_key).clone(), output_path);
                }
                Err(e) => {
                    ctx.logger.warn(&format!(
                        "[Subtitles] Failed to process {}: {}",
                        track_key, e
                    ));
                    errors.push(((*track_key).clone(), e));
                }
            }
        }

        // Record results
        state.subtitles = Some(SubtitlesOutput {
            processed_files,
            ocr_performed: false,
            video_verified_cache,
        });

        ctx.logger.info("\n[Subtitles] ═══════════════════════════════════════════════════════");
        if errors.is_empty() {
            ctx.logger.info("[Subtitles] All subtitle tracks processed successfully");
            ctx.logger.info("[Subtitles] ═══════════════════════════════════════════════════════\n");
            Ok(StepOutcome::Success)
        } else {
            ctx.logger.warn(&format!(
                "[Subtitles] {} track(s) failed to process",
                errors.len()
            ));
            ctx.logger.info("[Subtitles] ═══════════════════════════════════════════════════════\n");
            Ok(StepOutcome::Success)
        }
    }

    fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
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

    #[test]
    fn test_is_bitmap_subtitle() {
        assert!(SubtitlesStep::is_bitmap_subtitle(Path::new("track.idx")));
        assert!(SubtitlesStep::is_bitmap_subtitle(Path::new("track.sub")));
        assert!(SubtitlesStep::is_bitmap_subtitle(Path::new("track.sup")));
        assert!(SubtitlesStep::is_bitmap_subtitle(Path::new("track.SUP")));
        assert!(!SubtitlesStep::is_bitmap_subtitle(Path::new("track.srt")));
        assert!(!SubtitlesStep::is_bitmap_subtitle(Path::new("track.ass")));
    }
}
