//! Options dialog layout mirroring `python/vsg_qt/options_dialog/ui.py`.

use std::collections::HashMap;

use cosmic::iced::Length;
use cosmic::widget::{self, scrollable};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    UpdateBool(&'static str, bool),
    UpdateText(&'static str, String),
    UpdateNumber(&'static str, String),
    UpdateChoice(&'static str, usize),
    Action(&'static str),
}

#[derive(Clone, Debug, Default)]
pub struct State {
    bools: HashMap<&'static str, bool>,
    texts: HashMap<&'static str, String>,
    numbers: HashMap<&'static str, String>,
    choices: HashMap<&'static str, Option<usize>>,
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::UpdateBool(key, value) => {
                self.bools.insert(key, value);
            }
            Message::UpdateText(key, value) => {
                self.texts.insert(key, value);
            }
            Message::UpdateNumber(key, value) => {
                self.numbers.insert(key, value);
            }
            Message::UpdateChoice(key, value) => {
                self.choices.insert(key, Some(value));
            }
            Message::Action(_) => {}
        }
    }

    fn bool_value(&self, key: &'static str) -> bool {
        self.bools.get(key).copied().unwrap_or(false)
    }

    fn text_value(&self, key: &'static str) -> String {
        self.texts.get(key).cloned().unwrap_or_default()
    }

    fn number_value(&self, key: &'static str) -> String {
        self.numbers.get(key).cloned().unwrap_or_default()
    }

    fn choice_value(&self, key: &'static str) -> Option<usize> {
        self.choices.get(key).copied().flatten()
    }
}

fn action_button(label: &'static str) -> Element<Message> {
    common::button(label, Message::Action(label))
}

fn checkbox_field(state: &State, key: &'static str, label: &str) -> Element<Message> {
    common::checkbox(label, state.bool_value(key), move |value| {
        Message::UpdateBool(key, value)
    })
}

fn text_field(state: &State, key: &'static str, placeholder: &str) -> Element<Message> {
    common::text_input(
        placeholder,
        &state.text_value(key),
        move |value| Message::UpdateText(key, value),
    )
}

fn number_field(state: &State, key: &'static str, placeholder: &str) -> Element<Message> {
    common::numeric_input(
        placeholder,
        &state.number_value(key),
        move |value| Message::UpdateNumber(key, value),
    )
}

fn dropdown_field(
    state: &State,
    key: &'static str,
    options: &[&'static str],
) -> Element<Message> {
    common::dropdown(
        options,
        state.choice_value(key),
        move |value| Message::UpdateChoice(key, value),
    )
}

fn file_picker_field(state: &State, key: &'static str, label: &str) -> Element<Message> {
    common::file_picker_input(
        label,
        &state.text_value(key),
        move |value| Message::UpdateText(key, value),
        Message::Action(key),
    )
}

fn tab_bar() -> Element<'static, Message> {
    let tabs = [
        "Storage & Tools",
        "Analysis",
        "Stepping Correction",
        "Subtitles",
        "Chapters",
        "Timing",
        "Subtitle Cleanup",
        "Merge Behavior",
        "Logging",
    ];

    widget::row()
        .spacing(8)
        .push(widget::text::body("Tabs:"))
        .push(
            tabs.iter().fold(widget::row().spacing(8), |row, label| {
                row.push(action_button(label))
            }),
        )
        .into()
}

fn storage_tab(state: &State) -> Element<'static, Message> {
    let content = widget::column()
        .spacing(12)
        .push(file_picker_field(state, "output_folder", "Output Directory:"))
        .push(file_picker_field(state, "temp_root", "Temporary Directory:"))
        .push(file_picker_field(state, "videodiff_path", "VideoDiff Path (optional):"))
        .push(file_picker_field(
            state,
            "subtile_ocr_path",
            "Subtitle OCR Path (optional):",
        ))
        .push(common::form_row(
            "OCR Character Blacklist (optional):",
            text_field(state, "subtile_ocr_char_blacklist", "Characters"),
        ));

    common::section("Storage & Tools", content.into())
}

fn subtitle_cleanup_tab(state: &State) -> Element<'static, Message> {
    let content = widget::column()
        .spacing(12)
        .push(checkbox_field(
            state,
            "ocr_cleanup_enabled",
            "Enable post-OCR cleanup",
        ))
        .push(file_picker_field(
            state,
            "ocr_cleanup_custom_wordlist_path",
            "Custom Wordlist:",
        ))
        .push(checkbox_field(
            state,
            "ocr_cleanup_normalize_ellipsis",
            "Normalize ellipsis (...)",
        ));

    common::section("Subtitle Cleanup", content.into())
}

fn timing_tab(state: &State) -> Element<'static, Message> {
    let overlaps = widget::column()
        .spacing(8)
        .push(checkbox_field(state, "timing_fix_overlaps", "Enable"))
        .push(common::form_row(
            "Minimum Gap:",
            number_field(state, "timing_overlap_min_gap_ms", "ms"),
        ));

    let short = widget::column()
        .spacing(8)
        .push(checkbox_field(state, "timing_fix_short_durations", "Enable"))
        .push(common::form_row(
            "Minimum Duration:",
            number_field(state, "timing_min_duration_ms", "ms"),
        ));

    let long = widget::column()
        .spacing(8)
        .push(checkbox_field(state, "timing_fix_long_durations", "Enable"))
        .push(common::form_row(
            "Max Characters Per Second:",
            number_field(state, "timing_max_cps", "CPS"),
        ));

    let content = widget::column()
        .spacing(16)
        .push(checkbox_field(
            state,
            "timing_fix_enabled",
            "Enable subtitle timing corrections",
        ))
        .push(common::subsection("Fix Overlapping Display Times", overlaps.into()))
        .push(common::subsection("Fix Short Display Times", short.into()))
        .push(common::subsection(
            "Fix Long Display Times (based on Reading Speed)",
            long.into(),
        ));

    common::section("Timing", content.into())
}

fn analysis_tab(state: &State) -> Element<'static, Message> {
    let prep = widget::column()
        .spacing(12)
        .push(common::form_row(
            "Source Separation:",
            dropdown_field(state, "source_separation_mode", &[
                "None (Use Original Audio)",
                "Instrumental (No Vocals)",
                "Vocals Only",
            ]),
        ))
        .push(common::form_row(
            "Separation Model:",
            dropdown_field(
                state,
                "source_separation_model",
                &["Default (Audio Separator)", "(No models installed)"],
            ),
        ))
        .push(file_picker_field(
            state,
            "source_separation_model_dir",
            "Model Directory:",
        ))
        .push(common::form_row(
            "Apply To:",
            dropdown_field(state, "source_separation_apply_to", &[
                "All Comparisons",
                "Only When Comparing Source 2",
                "Only When Comparing Source 3",
            ]),
        ))
        .push(action_button("Manage Models..."))
        .push(common::form_row(
            "Audio Filtering:",
            dropdown_field(state, "filtering_method", &[
                "None",
                "Low-Pass Filter",
                "Dialogue Band-Pass Filter",
            ]),
        ))
        .push(common::form_row(
            "Low-Pass Cutoff:",
            number_field(state, "audio_bandlimit_hz", "Hz"),
        ));

    let core = widget::column()
        .spacing(12)
        .push(common::form_row(
            "Correlation Method:",
            dropdown_field(state, "correlation_method", &[
                "Standard Correlation (SCC)",
                "Phase Correlation (GCC-PHAT)",
                "Onset Detection",
                "GCC-SCOT",
                "DTW (Dynamic Time Warping)",
                "Spectrogram Correlation",
                "VideoDiff",
            ]),
        ))
        .push(common::form_row(
            "Correlation (Source-Separated):",
            dropdown_field(state, "correlation_method_source_separated", &[
                "Standard Correlation (SCC)",
                "Phase Correlation (GCC-PHAT)",
                "Onset Detection",
                "GCC-SCOT",
                "DTW (Dynamic Time Warping)",
                "Spectrogram Correlation",
            ]),
        ))
        .push(common::form_row(
            "Number of Chunks:",
            number_field(state, "scan_chunk_count", "count"),
        ))
        .push(common::form_row(
            "Duration of Chunks (s):",
            number_field(state, "scan_chunk_duration", "seconds"),
        ))
        .push(common::form_row(
            "Minimum Match Confidence (%):",
            number_field(state, "min_match_pct", "percent"),
        ))
        .push(common::form_row(
            "Minimum Accepted Chunks:",
            number_field(state, "min_accepted_chunks", "count"),
        ))
        .push(common::form_row(
            "Delay Selection Method:",
            dropdown_field(
                state,
                "delay_selection_mode",
                &["Mode (Most Common)", "Mode (Clustered)", "First Stable", "Average"],
            ),
        ))
        .push(common::form_row(
            "Delay Selection (Source-Separated):",
            dropdown_field(
                state,
                "delay_selection_mode_source_separated",
                &["Mode (Most Common)", "Mode (Clustered)", "First Stable", "Average"],
            ),
        ))
        .push(common::form_row(
            "Min Chunks for Stability:",
            number_field(state, "first_stable_min_chunks", "count"),
        ))
        .push(checkbox_field(
            state,
            "first_stable_skip_unstable",
            "Skip Unstable Segments",
        ));

    let multi = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "multi_correlation_enabled",
            "Enable Multi-Correlation Comparison",
        ))
        .push(checkbox_field(state, "multi_corr_scc", "Standard Correlation (SCC)"))
        .push(checkbox_field(
            state,
            "multi_corr_gcc_phat",
            "Phase Correlation (GCC-PHAT)",
        ))
        .push(checkbox_field(state, "multi_corr_onset", "Onset Detection"))
        .push(checkbox_field(state, "multi_corr_gcc_scot", "GCC-SCOT"))
        .push(checkbox_field(
            state,
            "multi_corr_gcc_whiten",
            "Whitened Cross-Correlation",
        ))
        .push(checkbox_field(state, "multi_corr_dtw", "DTW (Dynamic Time Warping)"))
        .push(checkbox_field(
            state,
            "multi_corr_spectrogram",
            "Spectrogram Correlation",
        ));

    let advanced = widget::column()
        .spacing(12)
        .push(common::form_row(
            "Scan Start Position:",
            number_field(state, "scan_start_percentage", "percent"),
        ))
        .push(common::form_row(
            "Scan End Position:",
            number_field(state, "scan_end_percentage", "percent"),
        ))
        .push(common::form_row(
            "Band-Pass Low Cutoff:",
            number_field(state, "filter_bandpass_lowcut_hz", "Hz"),
        ))
        .push(common::form_row(
            "Band-Pass High Cutoff:",
            number_field(state, "filter_bandpass_highcut_hz", "Hz"),
        ))
        .push(common::form_row(
            "Band-Pass Filter Order:",
            number_field(state, "filter_bandpass_order", "order"),
        ))
        .push(common::form_row(
            "Low-Pass Filter Taps:",
            number_field(state, "filter_lowpass_taps", "taps"),
        ));

    let language = widget::column()
        .spacing(12)
        .push(common::form_row(
            "Source 1 (Reference) Language:",
            text_field(state, "analysis_lang_source1", "eng"),
        ))
        .push(common::form_row(
            "Other Sources Language:",
            text_field(state, "analysis_lang_others", "jpn"),
        ));

    let timing_mode = widget::column().push(common::form_row(
        "Sync Mode:",
        dropdown_field(state, "sync_mode", &["positive_only", "allow_negative"]),
    ));

    let diagnostics = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "use_soxr",
            "Use High-Quality Resampling (SoXR)",
        ))
        .push(checkbox_field(
            state,
            "audio_peak_fit",
            "Enable Sub-Sample Peak Fitting (SCC only)",
        ))
        .push(checkbox_field(
            state,
            "log_audio_drift",
            "Log Audio Drift Metric",
        ));

    let content = widget::column()
        .spacing(16)
        .push(common::subsection("Step 1: Audio Pre-Processing", prep.into()))
        .push(common::subsection("Step 2: Core Analysis Engine", core.into()))
        .push(common::subsection(
            "Multi-Correlation Comparison (Analyze Only)",
            multi.into(),
        ))
        .push(common::subsection(
            "Step 3: Advanced Filtering & Scan Controls",
            advanced.into(),
        ))
        .push(common::subsection("Step 4: Audio Track Selection", language.into()))
        .push(common::subsection("Step 5: Timing Sync Mode", timing_mode.into()))
        .push(common::subsection(
            "Step 6: Advanced Tweaks & Diagnostics",
            diagnostics.into(),
        ));

    common::section("Analysis", content.into())
}

fn stepping_tab(state: &State) -> Element<'static, Message> {
    let detection = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "segmented_enabled",
            "Enable stepping correction",
        ))
        .push(common::form_row(
            "DBSCAN Epsilon:",
            number_field(state, "detection_dbscan_epsilon_ms", "ms"),
        ))
        .push(common::form_row(
            "DBSCAN Min Samples:",
            number_field(state, "detection_dbscan_min_samples", "count"),
        ))
        .push(common::form_row(
            "Triage Threshold:",
            number_field(state, "segment_triage_std_dev_ms", "ms"),
        ))
        .push(common::form_row(
            "Lossy R² Threshold:",
            number_field(state, "drift_detection_r2_threshold", "value"),
        ))
        .push(common::form_row(
            "Lossless R² Threshold:",
            number_field(state, "drift_detection_r2_threshold_lossless", "value"),
        ))
        .push(common::form_row(
            "Lossy Slope Threshold:",
            number_field(state, "drift_detection_slope_threshold_lossy", "ms/s"),
        ))
        .push(common::form_row(
            "Lossless Slope Threshold:",
            number_field(state, "drift_detection_slope_threshold_lossless", "ms/s"),
        ));

    let quality = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Correction Mode:",
            dropdown_field(
                state,
                "stepping_correction_mode",
                &["full", "filtered", "strict", "disabled"],
            ),
        ))
        .push(common::form_row(
            "Quality Mode:",
            dropdown_field(
                state,
                "stepping_quality_mode",
                &["strict", "normal", "lenient", "custom"],
            ),
        ))
        .push(common::form_row(
            "Filtered Fallback:",
            dropdown_field(
                state,
                "stepping_filtered_fallback",
                &["nearest", "interpolate", "uniform", "skip", "reject"],
            ),
        ))
        .push(common::form_row(
            "Min Chunks/Cluster:",
            number_field(state, "stepping_min_chunks_per_cluster", "count"),
        ))
        .push(common::form_row(
            "Min Cluster %:",
            number_field(state, "stepping_min_cluster_percentage", "percent"),
        ))
        .push(common::form_row(
            "Min Cluster Duration:",
            number_field(state, "stepping_min_cluster_duration_s", "seconds"),
        ))
        .push(common::form_row(
            "Min Match Quality:",
            number_field(state, "stepping_min_match_quality_pct", "percent"),
        ))
        .push(common::form_row(
            "Min Total Clusters:",
            number_field(state, "stepping_min_total_clusters", "count"),
        ));

    let delay_selection = widget::column()
        .spacing(8)
        .push(common::form_row(
            "First Stable Min Chunks:",
            number_field(state, "stepping_first_stable_min_chunks", "count"),
        ))
        .push(checkbox_field(
            state,
            "stepping_first_stable_skip_unstable",
            "First Stable Skip Unstable",
        ));

    let scan_config = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Scan Start Position:",
            number_field(state, "stepping_scan_start_percentage", "percent"),
        ))
        .push(common::form_row(
            "Scan End Position:",
            number_field(state, "stepping_scan_end_percentage", "percent"),
        ))
        .push(common::form_row(
            "Coarse Chunk Duration:",
            number_field(state, "segment_coarse_chunk_s", "seconds"),
        ))
        .push(common::form_row(
            "Coarse Step Size:",
            number_field(state, "segment_coarse_step_s", "seconds"),
        ))
        .push(common::form_row(
            "Search Window:",
            number_field(state, "segment_search_locality_s", "seconds"),
        ))
        .push(common::form_row(
            "Min Confidence Ratio:",
            number_field(state, "segment_min_confidence_ratio", "ratio"),
        ))
        .push(common::form_row(
            "Fine Chunk Duration:",
            number_field(state, "segment_fine_chunk_s", "seconds"),
        ))
        .push(common::form_row(
            "Fine Iterations:",
            number_field(state, "segment_fine_iterations", "count"),
        ))
        .push(common::form_row(
            "QA Threshold:",
            number_field(state, "segmented_qa_threshold", "percent"),
        ))
        .push(common::form_row(
            "QA Chunk Count:",
            number_field(state, "segment_qa_chunk_count", "count"),
        ))
        .push(common::form_row(
            "QA Min Accepted:",
            number_field(state, "segment_qa_min_accepted_chunks", "count"),
        ));

    let silence_detection = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Detection Method:",
            dropdown_field(
                state,
                "stepping_silence_detection_method",
                &["smart_fusion", "ffmpeg_silencedetect", "rms_basic"],
            ),
        ))
        .push(checkbox_field(
            state,
            "stepping_vad_enabled",
            "Enable speech protection (VAD)",
        ))
        .push(common::form_row(
            "VAD Aggressiveness:",
            number_field(state, "stepping_vad_aggressiveness", "level"),
        ))
        .push(checkbox_field(
            state,
            "stepping_transient_detection_enabled",
            "Enable transient detection (avoid musical beats)",
        ))
        .push(common::form_row(
            "Transient Threshold:",
            number_field(state, "stepping_transient_threshold", "dB"),
        ))
        .push(checkbox_field(
            state,
            "stepping_snap_to_silence",
            "Enable boundary snapping to silence zones",
        ))
        .push(common::form_row(
            "Search Window:",
            number_field(state, "stepping_silence_search_window_s", "seconds"),
        ))
        .push(common::form_row(
            "Silence Threshold:",
            number_field(state, "stepping_silence_threshold_db", "dB"),
        ))
        .push(common::form_row(
            "Min Silence Duration:",
            number_field(state, "stepping_silence_min_duration_ms", "ms"),
        ))
        .push(checkbox_field(
            state,
            "stepping_snap_to_video_frames",
            "Enable boundary snapping to video frames/scenes",
        ))
        .push(common::form_row(
            "Video Snap Mode:",
            dropdown_field(
                state,
                "stepping_video_snap_mode",
                &["scenes", "keyframes", "any_frame"],
            ),
        ))
        .push(common::form_row(
            "Max Snap Distance:",
            number_field(state, "stepping_video_snap_max_offset_s", "seconds"),
        ))
        .push(common::form_row(
            "Scene Threshold:",
            number_field(state, "stepping_video_scene_threshold", "value"),
        ));

    let audio_processing = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Resample Engine:",
            dropdown_field(
                state,
                "segment_resample_engine",
                &["aresample", "atempo", "rubberband"],
            ),
        ))
        .push(checkbox_field(
            state,
            "segment_rb_pitch_correct",
            "Enable Pitch Correction",
        ))
        .push(common::form_row(
            "Transient Handling:",
            dropdown_field(
                state,
                "segment_rb_transients",
                &["crisp", "mixed", "smooth"],
            ),
        ))
        .push(checkbox_field(
            state,
            "segment_rb_smoother",
            "Enable Phase Smoothing (Higher Quality)",
        ))
        .push(checkbox_field(
            state,
            "segment_rb_pitchq",
            "Enable High-Quality Pitch Algorithm",
        ))
        .push(common::form_row(
            "Fill Mode:",
            dropdown_field(state, "stepping_fill_mode", &["silence", "auto", "content"]),
        ))
        .push(common::form_row(
            "Content Threshold:",
            number_field(state, "stepping_content_correlation_threshold", "value"),
        ))
        .push(common::form_row(
            "Search Window:",
            number_field(state, "stepping_content_search_window_s", "seconds"),
        ))
        .push(common::form_row(
            "R² Threshold:",
            number_field(state, "segment_drift_r2_threshold", "value"),
        ))
        .push(common::form_row(
            "Slope Threshold:",
            number_field(state, "segment_drift_slope_threshold", "ms/s"),
        ))
        .push(common::form_row(
            "Outlier Sensitivity:",
            number_field(state, "segment_drift_outlier_sensitivity", "value"),
        ))
        .push(common::form_row(
            "Scan Buffer %:",
            number_field(state, "segment_drift_scan_buffer_pct", "percent"),
        ));

    let naming = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Corrected Track Label:",
            text_field(state, "stepping_corrected_track_label", "Label"),
        ))
        .push(common::form_row(
            "Preserved Track Label:",
            text_field(state, "stepping_preserved_track_label", "Label"),
        ));

    let subtitle_adjust = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "stepping_adjust_subtitles",
            "Adjust subtitle timestamps for stepped sources",
        ))
        .push(checkbox_field(
            state,
            "stepping_adjust_subtitles_no_audio",
            "Apply stepping to subtitles when no audio is merged",
        ))
        .push(common::form_row(
            "Boundary Spanning Mode:",
            dropdown_field(state, "stepping_boundary_mode", &["start", "majority", "midpoint"]),
        ));

    let diagnostics = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "stepping_diagnostics_verbose",
            "Enable detailed cluster diagnostics",
        ));

    let content = widget::column()
        .spacing(16)
        .push(common::subsection("Detection Settings", detection.into()))
        .push(common::subsection("Quality Validation", quality.into()))
        .push(common::subsection("Delay Selection", delay_selection.into()))
        .push(common::subsection("Scan Configuration", scan_config.into()))
        .push(common::subsection(
            "Advanced Silence Detection",
            silence_detection.into(),
        ))
        .push(common::subsection("Audio Processing", audio_processing.into()))
        .push(common::subsection("Track Naming", naming.into()))
        .push(common::subsection(
            "Subtitle Adjustment",
            subtitle_adjust.into(),
        ))
        .push(common::subsection("Diagnostics", diagnostics.into()));

    common::section("Stepping Correction", content.into())
}

fn subtitle_sync_tab(state: &State) -> Element<'static, Message> {
    let sync_mode = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Sync Mode:",
            dropdown_field(state, "subtitle_sync_mode", &[
                "time-based",
                "timebase-frame-locked-timestamps",
                "duration-align",
                "correlation-frame-snap",
                "subtitle-anchored-frame-snap",
                "correlation-guided-frame-anchor",
            ]),
        ))
        .push(checkbox_field(
            state,
            "time_based_use_raw_values",
            "Use raw correlation values (pysubs)",
        ))
        .push(common::form_row(
            "Rounding:",
            dropdown_field(state, "raw_delay_rounding", &["floor", "round", "ceil"]),
        ))
        .push(checkbox_field(
            state,
            "time_based_frame_boundary_correction",
            "Fix frame boundary errors (CFR)",
        ))
        .push(common::form_row(
            "VTS Rounding:",
            dropdown_field(state, "videotimestamps_rounding", &["floor", "round"]),
        ))
        .push(checkbox_field(
            state,
            "framelocked_enable_post_ass_correction",
            "Enable post-ASS correction",
        ))
        .push(checkbox_field(
            state,
            "framelocked_log_post_ass_corrections",
            "Log post-ASS corrections",
        ))
        .push(checkbox_field(
            state,
            "framelocked_log_initial_snap",
            "Log initial frame-snapping",
        ))
        .push(checkbox_field(
            state,
            "duration_align_use_vapoursynth",
            "Use VapourSynth indexing",
        ))
        .push(checkbox_field(
            state,
            "duration_align_validate",
            "Validate frame alignment",
        ))
        .push(common::form_row(
            "Validation Points:",
            dropdown_field(
                state,
                "duration_align_validate_points",
                &["1 point (fast)", "3 points (thorough)"],
            ),
        ))
        .push(common::form_row(
            "Hash Algorithm:",
            dropdown_field(
                state,
                "duration_align_hash_algorithm",
                &["dhash", "phash", "average_hash", "whash"],
            ),
        ))
        .push(common::form_row(
            "Hash Size:",
            dropdown_field(state, "duration_align_hash_size", &["4", "8", "16"]),
        ))
        .push(common::form_row(
            "Hash Threshold:",
            number_field(state, "duration_align_hash_threshold", "value"),
        ))
        .push(common::form_row(
            "Strictness:",
            number_field(state, "duration_align_strictness", "percent"),
        ))
        .push(checkbox_field(
            state,
            "duration_align_verify_with_frames",
            "Verify alignment with frame matching (hybrid mode)",
        ))
        .push(common::form_row(
            "Verify Search Window:",
            number_field(state, "duration_align_verify_search_window", "ms"),
        ))
        .push(common::form_row(
            "Verify Tolerance:",
            number_field(state, "duration_align_verify_tolerance", "ms"),
        ))
        .push(common::form_row(
            "Fallback Mode:",
            dropdown_field(
                state,
                "duration_align_fallback_mode",
                &["none", "abort", "auto-fallback", "duration-offset"],
            ),
        ))
        .push(common::form_row(
            "Fallback Target:",
            dropdown_field(state, "duration_align_fallback_target", &["not-implemented"]),
        ))
        .push(checkbox_field(
            state,
            "duration_align_skip_validation_generated_tracks",
            "Skip validation for generated tracks (recommended)",
        ))
        .push(common::form_row(
            "Corr+Snap Fallback:",
            dropdown_field(
                state,
                "correlation_snap_fallback_mode",
                &["snap-to-frame", "use-raw", "abort"],
            ),
        ))
        .push(common::form_row(
            "Corr+Snap Hash:",
            dropdown_field(
                state,
                "correlation_snap_hash_algorithm",
                &["dhash", "phash", "average_hash"],
            ),
        ))
        .push(common::form_row(
            "Corr+Snap Threshold:",
            number_field(state, "correlation_snap_hash_threshold", "value"),
        ))
        .push(common::form_row(
            "Corr+Snap Window:",
            number_field(state, "correlation_snap_window_radius", "frames"),
        ))
        .push(common::form_row(
            "Corr+Snap Search:",
            number_field(state, "correlation_snap_search_range", "frames"),
        ))
        .push(common::form_row(
            "SubAnchor Search Range:",
            number_field(state, "sub_anchor_search_range_ms", "ms"),
        ))
        .push(common::form_row(
            "SubAnchor Hash:",
            dropdown_field(
                state,
                "sub_anchor_hash_algorithm",
                &["dhash", "phash", "average_hash"],
            ),
        ))
        .push(common::form_row(
            "SubAnchor Threshold:",
            number_field(state, "sub_anchor_hash_threshold", "value"),
        ))
        .push(common::form_row(
            "SubAnchor Window:",
            number_field(state, "sub_anchor_window_radius", "frames"),
        ))
        .push(common::form_row(
            "SubAnchor Tolerance:",
            number_field(state, "sub_anchor_agreement_tolerance_ms", "ms"),
        ))
        .push(common::form_row(
            "SubAnchor Fallback:",
            dropdown_field(state, "sub_anchor_fallback_mode", &["abort", "use-median"]),
        ))
        .push(common::form_row(
            "CorrGuided Search Range:",
            number_field(state, "corr_anchor_search_range_ms", "ms"),
        ))
        .push(common::form_row(
            "CorrGuided Hash:",
            dropdown_field(
                state,
                "corr_anchor_hash_algorithm",
                &["dhash", "phash", "average_hash"],
            ),
        ))
        .push(common::form_row(
            "CorrGuided Threshold:",
            number_field(state, "corr_anchor_hash_threshold", "value"),
        ))
        .push(common::form_row(
            "CorrGuided Window:",
            number_field(state, "corr_anchor_window_radius", "frames"),
        ))
        .push(common::form_row(
            "CorrGuided Tolerance:",
            number_field(state, "corr_anchor_agreement_tolerance_ms", "ms"),
        ))
        .push(common::form_row(
            "CorrGuided Fallback:",
            dropdown_field(
                state,
                "corr_anchor_fallback_mode",
                &["abort", "use-median", "use-correlation"],
            ),
        ))
        .push(checkbox_field(
            state,
            "corr_anchor_refine_per_line",
            "Refine each subtitle to exact frames",
        ))
        .push(common::form_row(
            "CorrGuided Workers:",
            number_field(state, "corr_anchor_refine_workers", "count"),
        ));

    common::section("Subtitles", sync_mode.into())
}

fn chapters_tab(state: &State) -> Element<'static, Message> {
    let content = widget::column()
        .spacing(12)
        .push(checkbox_field(
            state,
            "rename_chapters",
            "Rename to \"Chapter NN\"",
        ))
        .push(checkbox_field(
            state,
            "snap_chapters",
            "Snap chapter timestamps to nearest keyframe",
        ))
        .push(common::form_row(
            "Snap Mode:",
            dropdown_field(state, "snap_mode", &["previous", "nearest"]),
        ))
        .push(common::form_row(
            "Snap Threshold (ms):",
            number_field(state, "snap_threshold_ms", "ms"),
        ))
        .push(checkbox_field(
            state,
            "snap_starts_only",
            "Only snap chapter start times (not end times)",
        ));

    common::section("Chapters", content.into())
}

fn merge_behavior_tab(state: &State) -> Element<'static, Message> {
    let general = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "apply_dialog_norm_gain",
            "Remove dialog normalization gain (AC3/E-AC3)",
        ))
        .push(checkbox_field(
            state,
            "disable_track_statistics_tags",
            "Disable track statistics tags (for purist remuxes)",
        ))
        .push(checkbox_field(
            state,
            "disable_header_compression",
            "Disable header removal compression for all tracks",
        ));

    let post_merge = widget::column()
        .spacing(8)
        .push(checkbox_field(
            state,
            "post_mux_normalize_timestamps",
            "Rebase timestamps to fix thumbnails (requires FFmpeg)",
        ))
        .push(checkbox_field(
            state,
            "post_mux_strip_tags",
            "Strip ENCODER tag added by FFmpeg (requires mkvpropedit)",
        ));

    let content = widget::column()
        .spacing(16)
        .push(common::subsection("General", general.into()))
        .push(common::subsection(
            "Post-Merge Finalization",
            post_merge.into(),
        ));

    common::section("Merge Behavior", content.into())
}

fn logging_tab(state: &State) -> Element<'static, Message> {
    let content = widget::column()
        .spacing(12)
        .push(checkbox_field(state, "log_compact", "Use compact logging"))
        .push(checkbox_field(
            state,
            "log_autoscroll",
            "Auto-scroll log view during jobs",
        ))
        .push(common::form_row(
            "Progress Step:",
            number_field(state, "log_progress_step", "percent"),
        ))
        .push(common::form_row(
            "Error Tail:",
            number_field(state, "log_error_tail", "lines"),
        ))
        .push(checkbox_field(
            state,
            "log_show_options_pretty",
            "Show mkvmerge options in log (pretty text)",
        ))
        .push(checkbox_field(
            state,
            "log_show_options_json",
            "Show mkvmerge options in log (raw JSON)",
        ));

    common::section("Logging", content.into())
}

pub fn view(state: &State) -> Element<'static, Message> {
    let content = widget::column()
        .spacing(20)
        .push(tab_bar())
        .push(storage_tab(state))
        .push(analysis_tab(state))
        .push(stepping_tab(state))
        .push(subtitle_sync_tab(state))
        .push(timing_tab(state))
        .push(subtitle_cleanup_tab(state))
        .push(chapters_tab(state))
        .push(merge_behavior_tab(state))
        .push(logging_tab(state))
        .push(
            widget::row()
                .spacing(12)
                .push(widget::horizontal_space(Length::Fill))
                .push(action_button("Save"))
                .push(action_button("Cancel")),
        );

    scrollable(content)
        .height(Length::Fill)
        .padding(16)
        .into()
}
