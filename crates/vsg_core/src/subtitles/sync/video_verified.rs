//! Video-verified sync mode.
//!
//! Uses frame matching to verify the audio correlation offset against actual video frames.
//!
//! # Algorithm
//!
//! 1. Start with the audio correlation delay as a baseline
//! 2. Generate candidate frame offsets around the correlation value
//! 3. Test each candidate at multiple checkpoints across the video
//! 4. Select the best matching frame offset using sequence verification
//! 5. Apply the verified offset (which may differ from audio correlation)
//!
//! # Use Cases
//!
//! Use this mode when:
//! - Subtitles are timed to VIDEO, not audio
//! - Audio may have a slight offset from video in the source
//! - You need frame-accurate subtitle timing
//! - The audio correlation seems slightly off (e.g., 1 frame / ~42ms)
//!
//! # Requirements
//!
//! - Both source and target video paths must be provided
//! - VapourSynth with FFMS2/BestSource, or FFmpeg must be available
//! - Target video FPS should be provided for accurate frame calculations

use crate::subtitles::error::SyncError;
use crate::subtitles::frame_utils::{
    compare_frames, detect_properties, generate_frame_candidates, is_available as is_frame_utils_available,
    open_video, select_checkpoint_times, time_to_frame_floor, ContentType, DeinterlaceMethod,
    VideoReaderConfig,
};
use crate::subtitles::types::{SubtitleData, SyncEventData};

use super::{SyncConfig, SyncDetails, SyncMode, SyncResult};

/// Video-verified sync mode.
///
/// Verifies audio correlation against video frame matching.
pub struct VideoVerified;

impl SyncMode for VideoVerified {
    fn name(&self) -> &str {
        "video-verified"
    }

    fn description(&self) -> &str {
        "Verify delay against video frame matching"
    }

    fn apply(&self, data: &mut SubtitleData, config: &SyncConfig) -> Result<SyncResult, SyncError> {
        if data.events.is_empty() {
            return Err(SyncError::NoEvents);
        }

        // Validate required inputs
        let source_video = config.source_video.as_ref().ok_or_else(|| {
            SyncError::MissingVideo("source_video required for video-verified mode".to_string())
        })?;

        let target_video = config.target_video.as_ref().ok_or_else(|| {
            SyncError::MissingVideo("target_video required for video-verified mode".to_string())
        })?;

        tracing::info!("[VideoVerified] === Video-Verified Sync Mode ===");
        tracing::info!("[VideoVerified] Source: {}", source_video.display());
        tracing::info!("[VideoVerified] Target: {}", target_video.display());

        // Check if frame utils are available
        if !is_frame_utils_available() {
            tracing::warn!(
                "[VideoVerified] Frame utilities not available, falling back to time-based"
            );
            return apply_time_based_fallback(data, config, "fallback-no-frame-utils");
        }

        // Check if files exist
        if !source_video.exists() {
            tracing::warn!(
                "[VideoVerified] Source video not found at {:?}",
                source_video
            );
            return apply_time_based_fallback(data, config, "fallback-source-not-found");
        }

        if !target_video.exists() {
            tracing::warn!(
                "[VideoVerified] Target video not found at {:?}",
                target_video
            );
            return apply_time_based_fallback(data, config, "fallback-target-not-found");
        }

        // Detect video properties
        tracing::info!("[VideoVerified] Detecting video properties...");

        let source_props = match detect_properties(source_video) {
            Ok(p) => p,
            Err(e) => {
                tracing::warn!("[VideoVerified] Failed to detect source properties: {}", e);
                return apply_time_based_fallback(data, config, "fallback-source-props-failed");
            }
        };

        let target_props = match detect_properties(target_video) {
            Ok(p) => p,
            Err(e) => {
                tracing::warn!("[VideoVerified] Failed to detect target properties: {}", e);
                return apply_time_based_fallback(data, config, "fallback-target-props-failed");
            }
        };

        // Determine if we're dealing with interlaced content
        let is_interlaced = should_use_interlaced_settings(
            &source_props.content_type,
            &target_props.content_type,
            &config.video_verified,
        );

        if is_interlaced {
            tracing::info!("[VideoVerified] Using interlaced handling settings");
        }

        // Get effective settings based on content type
        let vv_config = &config.video_verified;
        let num_checkpoints = vv_config.effective_num_checkpoints(is_interlaced);
        let search_range = vv_config.effective_search_range(is_interlaced);
        let hash_algorithm = vv_config.effective_hash_algorithm(is_interlaced);
        let hash_size = vv_config.effective_hash_size(is_interlaced);
        let hash_threshold = vv_config.effective_hash_threshold(is_interlaced);
        let comparison_method = vv_config.effective_comparison_method(is_interlaced);
        let sequence_length = vv_config.effective_sequence_length(is_interlaced);

        tracing::info!(
            "[VideoVerified] Settings: {} checkpoints, {} search range, {} hash, {} threshold",
            num_checkpoints,
            search_range,
            hash_algorithm.name(),
            hash_threshold
        );

        // Configure video reader
        let deinterlace = if is_interlaced && vv_config.interlaced_handling_enabled {
            vv_config.interlaced_deinterlace_method
        } else {
            DeinterlaceMethod::None
        };

        let reader_config = VideoReaderConfig {
            deinterlace,
            indexer_backend: vv_config.indexer_backend,
            temp_dir: None,
        };

        // Open video readers
        tracing::info!("[VideoVerified] Opening video files...");

        let source_reader = match open_video(source_video, &reader_config) {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!("[VideoVerified] Failed to open source video: {}", e);
                return apply_time_based_fallback(data, config, "fallback-source-open-failed");
            }
        };

        let target_reader = match open_video(target_video, &reader_config) {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!("[VideoVerified] Failed to open target video: {}", e);
                return apply_time_based_fallback(data, config, "fallback-target-open-failed");
            }
        };

        // Calculate pure correlation (total - global shift)
        let pure_correlation_ms = config.pure_correlation_ms();
        let frame_duration_ms = 1000.0 / target_props.fps;
        let correlation_frames = pure_correlation_ms / frame_duration_ms;

        tracing::info!(
            "[VideoVerified] Correlation: {:.1}ms ({:.2} frames at {:.3} fps)",
            pure_correlation_ms,
            correlation_frames,
            target_props.fps
        );

        // Generate candidate frame offsets
        let candidates = generate_frame_candidates(correlation_frames, search_range);
        tracing::info!(
            "[VideoVerified] Testing {} candidates: {:?}",
            candidates.len(),
            candidates
        );

        // Select checkpoint times
        let checkpoint_times = select_checkpoint_times(
            source_props.duration_ms.min(target_props.duration_ms),
            num_checkpoints,
        );
        tracing::info!(
            "[VideoVerified] Checkpoints: {} at {:?}",
            checkpoint_times.len(),
            checkpoint_times.iter().map(|t| format!("{:.0}ms", t)).collect::<Vec<_>>()
        );

        // Test each candidate at checkpoints
        tracing::info!("[VideoVerified] Testing candidates at checkpoints...");

        let mut best_candidate: Option<(i32, usize, usize, f64)> = None; // (offset, matched, verified, avg_dist)

        for &candidate_offset in &candidates {
            let mut matched_checkpoints = 0;
            let mut verified_sequences = 0;
            let mut total_distance = 0.0;
            let mut total_comparisons = 0;

            for &checkpoint_time in &checkpoint_times {
                // Get source frame at checkpoint
                let source_frame_idx = time_to_frame_floor(checkpoint_time, source_props.fps);
                if source_frame_idx < 0 {
                    continue;
                }
                let source_frame_idx = source_frame_idx as u32;

                // Calculate target frame with offset
                let target_frame_idx = (source_frame_idx as i32 + candidate_offset).max(0) as u32;

                // Check bounds
                if source_frame_idx >= source_reader.frame_count()
                    || target_frame_idx >= target_reader.frame_count()
                {
                    continue;
                }

                // Get frames
                let source_frame = match source_reader.get_frame(source_frame_idx) {
                    Ok(f) => f,
                    Err(_) => continue,
                };
                let target_frame = match target_reader.get_frame(target_frame_idx) {
                    Ok(f) => f,
                    Err(_) => continue,
                };

                // Compare frames
                let result = compare_frames(
                    &source_frame,
                    &target_frame,
                    comparison_method,
                    hash_algorithm,
                    hash_size,
                    hash_threshold,
                );

                total_distance += result.distance;
                total_comparisons += 1;

                if result.is_match {
                    matched_checkpoints += 1;

                    // Sequence verification - test consecutive frames
                    let mut sequence_matches = 1;
                    for seq_offset in 1..sequence_length {
                        let src_idx = source_frame_idx + seq_offset as u32;
                        let tgt_idx = target_frame_idx + seq_offset as u32;

                        if src_idx >= source_reader.frame_count()
                            || tgt_idx >= target_reader.frame_count()
                        {
                            break;
                        }

                        let src_frame = match source_reader.get_frame(src_idx) {
                            Ok(f) => f,
                            Err(_) => break,
                        };
                        let tgt_frame = match target_reader.get_frame(tgt_idx) {
                            Ok(f) => f,
                            Err(_) => break,
                        };

                        let seq_result = compare_frames(
                            &src_frame,
                            &tgt_frame,
                            comparison_method,
                            hash_algorithm,
                            hash_size,
                            hash_threshold,
                        );

                        if seq_result.is_match {
                            sequence_matches += 1;
                        } else {
                            break;
                        }
                    }

                    // Check if sequence is verified (70% match)
                    if sequence_matches >= (sequence_length as f64 * 0.7) as usize {
                        verified_sequences += 1;
                    }
                }
            }

            let avg_dist = if total_comparisons > 0 {
                total_distance / total_comparisons as f64
            } else {
                f64::MAX
            };

            tracing::debug!(
                "[VideoVerified] Candidate {} frames: {} matched, {} verified, {:.2} avg dist",
                candidate_offset,
                matched_checkpoints,
                verified_sequences,
                avg_dist
            );

            // Update best candidate
            // Priority: verified sequences > matched checkpoints > lower distance
            let is_better = match &best_candidate {
                None => true,
                Some((_, best_matched, best_verified, best_dist)) => {
                    verified_sequences > *best_verified
                        || (verified_sequences == *best_verified
                            && matched_checkpoints > *best_matched)
                        || (verified_sequences == *best_verified
                            && matched_checkpoints == *best_matched
                            && avg_dist < *best_dist)
                }
            };

            if is_better {
                best_candidate = Some((candidate_offset, matched_checkpoints, verified_sequences, avg_dist));
            }
        }

        // Select best candidate or fall back
        let (frame_offset, matched, verified, avg_dist) = match best_candidate {
            Some(c) => c,
            None => {
                tracing::warn!("[VideoVerified] No valid candidates found, falling back to time-based");
                return apply_time_based_fallback(data, config, "fallback-no-valid-candidates");
            }
        };

        tracing::info!(
            "[VideoVerified] Best candidate: {} frames ({} matched, {} verified, {:.2} avg dist)",
            frame_offset,
            matched,
            verified,
            avg_dist
        );

        // Check if frame matching actually worked
        let frame_match_success = verified > 0 || matched >= (num_checkpoints as f64 * 0.5) as usize;

        if !frame_match_success {
            if is_interlaced && vv_config.interlaced_fallback_to_audio {
                tracing::warn!(
                    "[VideoVerified] Insufficient matches for interlaced content, falling back to audio"
                );
                return apply_time_based_fallback(data, config, "fallback-insufficient-interlaced-matches");
            }
            // For progressive, we'll still use the best candidate with a warning
            tracing::warn!(
                "[VideoVerified] Low confidence match ({} verified, {} matched), using anyway",
                verified,
                matched
            );
        }

        // Calculate final offset
        let video_offset_ms = frame_offset as f64 * frame_duration_ms;
        let final_offset_ms = video_offset_ms + config.global_shift_ms;

        tracing::info!(
            "[VideoVerified] Video offset: {:.1}ms ({} frames)",
            video_offset_ms,
            frame_offset
        );
        tracing::info!(
            "[VideoVerified] Final offset: {:.1}ms (video {:.1}ms + global {:.1}ms)",
            final_offset_ms,
            video_offset_ms,
            config.global_shift_ms
        );

        // Apply offset to all events
        let mut events_affected = 0;

        for event in &mut data.events {
            if event.is_comment {
                continue;
            }

            let original_start = event.start_ms;
            let original_end = event.end_ms;

            event.start_ms = (event.start_ms + final_offset_ms).max(0.0);
            event.end_ms = (event.end_ms + final_offset_ms).max(0.0);

            event.sync_data = Some(SyncEventData {
                original_start_ms: original_start,
                original_end_ms: original_end,
                start_adjustment_ms: final_offset_ms,
                end_adjustment_ms: final_offset_ms,
                snapped_to_frame: false,
                snapped_frame: None,
            });

            events_affected += 1;
        }

        let summary = format!(
            "VideoVerified: {} events, {:+.1}ms ({} frames, {} verified)",
            events_affected, final_offset_ms, frame_offset, verified
        );

        tracing::info!("[VideoVerified] {}", summary);
        tracing::info!("[VideoVerified] === Video-Verified Complete ===");

        Ok(SyncResult {
            events_affected,
            final_offset_ms,
            summary,
            details: SyncDetails {
                reason: "video-verified".to_string(),
                audio_correlation_ms: Some(pure_correlation_ms),
                video_offset_ms: Some(video_offset_ms),
                frame_match_success: Some(frame_match_success),
                checkpoints_matched: Some(matched),
            },
        })
    }
}

/// Determine if interlaced settings should be used.
fn should_use_interlaced_settings(
    source_content: &ContentType,
    target_content: &ContentType,
    config: &super::VideoVerifiedConfig,
) -> bool {
    if !config.interlaced_handling_enabled {
        return false;
    }

    match config.interlaced_force_mode {
        super::super::frame_utils::types::InterlacedForceMode::Progressive => false,
        super::super::frame_utils::types::InterlacedForceMode::Interlaced => true,
        super::super::frame_utils::types::InterlacedForceMode::Telecine => true,
        super::super::frame_utils::types::InterlacedForceMode::Auto => {
            // Auto-detect: use interlaced settings if either video is interlaced
            matches!(
                source_content,
                ContentType::Interlaced | ContentType::Telecine
            ) || matches!(
                target_content,
                ContentType::Interlaced | ContentType::Telecine
            )
        }
    }
}

/// Apply time-based fallback when video-verified fails.
fn apply_time_based_fallback(
    data: &mut SubtitleData,
    config: &SyncConfig,
    reason: &str,
) -> Result<SyncResult, SyncError> {
    let pure_correlation_ms = config.pure_correlation_ms();
    let final_offset_ms = config.total_delay_ms;

    tracing::info!(
        "[VideoVerified] Fallback: applying time-based offset of {:.1}ms ({})",
        final_offset_ms,
        reason
    );

    // Apply offset to all events
    let mut events_affected = 0;

    for event in &mut data.events {
        if event.is_comment {
            continue;
        }

        let original_start = event.start_ms;
        let original_end = event.end_ms;

        event.start_ms = (event.start_ms + final_offset_ms).max(0.0);
        event.end_ms = (event.end_ms + final_offset_ms).max(0.0);

        event.sync_data = Some(SyncEventData {
            original_start_ms: original_start,
            original_end_ms: original_end,
            start_adjustment_ms: final_offset_ms,
            end_adjustment_ms: final_offset_ms,
            snapped_to_frame: false,
            snapped_frame: None,
        });

        events_affected += 1;
    }

    let summary = format!(
        "VideoVerified: {} events, {:+.1}ms ({})",
        events_affected, final_offset_ms, reason
    );

    Ok(SyncResult {
        events_affected,
        final_offset_ms,
        summary,
        details: SyncDetails {
            reason: reason.to_string(),
            audio_correlation_ms: Some(pure_correlation_ms),
            video_offset_ms: Some(pure_correlation_ms), // Same as audio in fallback
            frame_match_success: None,
            checkpoints_matched: None,
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::subtitles::types::SubtitleEvent;
    use std::path::PathBuf;

    #[test]
    fn test_video_verified_missing_source() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        let config = SyncConfig {
            total_delay_ms: 100.0,
            global_shift_ms: 0.0,
            source_video: None,
            target_video: Some(PathBuf::from("/tmp/target.mkv")),
            ..Default::default()
        };

        let sync = VideoVerified;
        let result = sync.apply(&mut data, &config);

        assert!(matches!(result, Err(SyncError::MissingVideo(_))));
    }

    #[test]
    fn test_video_verified_missing_target() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        let config = SyncConfig {
            total_delay_ms: 100.0,
            global_shift_ms: 0.0,
            source_video: Some(PathBuf::from("/tmp/source.mkv")),
            target_video: None,
            ..Default::default()
        };

        let sync = VideoVerified;
        let result = sync.apply(&mut data, &config);

        assert!(matches!(result, Err(SyncError::MissingVideo(_))));
    }

    #[test]
    fn test_video_verified_fallback() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        let config = SyncConfig {
            total_delay_ms: 150.0,
            global_shift_ms: 50.0,
            source_video: Some(PathBuf::from("/nonexistent/source.mkv")),
            target_video: Some(PathBuf::from("/nonexistent/target.mkv")),
            ..Default::default()
        };

        let sync = VideoVerified;
        let result = sync.apply(&mut data, &config).unwrap();

        // Should fall back to time-based behavior
        assert_eq!(result.events_affected, 1);
        assert!((result.final_offset_ms - 150.0).abs() < 0.001);
        assert!(result.details.reason.starts_with("fallback"));
    }

    #[test]
    fn test_should_use_interlaced_settings() {
        let config = super::super::VideoVerifiedConfig::default();

        // Progressive content
        assert!(!should_use_interlaced_settings(
            &ContentType::Progressive,
            &ContentType::Progressive,
            &config
        ));

        // Interlaced content
        assert!(should_use_interlaced_settings(
            &ContentType::Interlaced,
            &ContentType::Progressive,
            &config
        ));

        // Telecine content
        assert!(should_use_interlaced_settings(
            &ContentType::Telecine,
            &ContentType::Progressive,
            &config
        ));
    }
}
