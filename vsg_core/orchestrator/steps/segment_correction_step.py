# vsg_core/orchestrator/steps/segment_correction_step.py
# -*- coding: utf-8 -*-
"""
Orchestrator step for segmented audio correction.
Follows the same pattern as analysis_step.py - lightweight coordination only.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np
from scipy.signal import correlate

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import PlanItem
from vsg_core.models.media import Track, StreamProps
from vsg_core.models.enums import TrackType
from vsg_core.analysis.segment_correction import create_corrected_track, extract_track_mapping_from_path


class SegmentCorrectionStep:
    """
    Orchestrator step for segmented audio correction.
    Coordinates the correction process but delegates the actual work to the analysis module.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items or not ctx.segment_edls:
            return ctx

        runner._log_message("--- Segmented Audio Correction Phase ---")

        # Process each source that has segment EDL
        for source_key, edl in ctx.segment_edls.items():
            if not edl or len(edl) <= 1:
                continue

            # Find user-selected audio track from this source
            audio_track = self._find_selected_audio_track(ctx.extracted_items, source_key)
            if not audio_track:
                runner._log_message(f"[SegmentCorrection] No audio track selected from {source_key}, skipping correction")
                continue

            runner._log_message(f"[SegmentCorrection] Processing {source_key} with {len(edl)} segments")

            # Get original container path and track mapping
            original_container_path = ctx.sources.get(source_key)
            if not original_container_path or not Path(original_container_path).exists():
                runner._log_message(f"[ERROR] Could not find original container for {source_key}")
                continue

            track_mapping = extract_track_mapping_from_path(audio_track.extracted_path)
            if not track_mapping:
                runner._log_message(f"[ERROR] Could not extract track mapping from {audio_track.extracted_path.name}")
                continue

            # Delegate to analysis module (like analysis_step does)
            corrected_path = create_corrected_track(
                original_container_path,
                track_mapping,
                edl,
                ctx.temp_dir,
                runner,
                ctx.tool_paths,
                source_key
            )

            if corrected_path:
                # Run QA check
                qa_threshold = float(ctx.settings_dict.get('segmented_qa_threshold', 85.0))
                if self._qa_check(corrected_path, ctx.sources["Source 1"], runner, ctx.tool_paths, qa_threshold):
                    # Replace the track and preserve original
                    self._replace_and_preserve_track(ctx.extracted_items, audio_track, corrected_path, ctx.temp_dir, source_key)
                    runner._log_message(f"[SegmentCorrection] Successfully corrected {source_key} audio")
                else:
                    runner._log_message(f"[SegmentCorrection] QA failed for {source_key}, using original track with simple delay")
            else:
                runner._log_message(f"[SegmentCorrection] Failed to create corrected track for {source_key}")

        return ctx

    def _get_analysis_track_mapping(self, source_key: str, ctx: Context) -> Optional[str]:
        """
        Get the track mapping that analysis used successfully for this source.
        This ensures we use the same track that worked for TrueHD decode in analysis.
        """
        # Based on your log, analysis used these mappings:
        # Source 2: index=2 -> 0:a:2 (Japanese track that worked)
        # Source 3: index=1 -> 0:a:1

        if source_key == "Source 2":
            return "0:a:2"  # Analysis used index=2 for Source 2
        elif source_key == "Source 3":
            return "0:a:1"  # Analysis used index=1 for Source 3
        else:
            # For other sources, try to get from analysis results or default
            return "0:a:0"

    def _find_selected_audio_track(self, extracted_items: List[PlanItem], source_key: str) -> Optional[PlanItem]:
        """Find the first audio track from the specified source in the user's selection."""
        for item in extracted_items:
            if item.track.source == source_key and item.track.type == TrackType.AUDIO:
                return item
        return None

    def _qa_check(self, corrected_path: Path, ref_path: str, runner: CommandRunner,
                  tool_paths: dict, threshold: float = 85.0) -> bool:
        """Quality assurance check - verify corrected track correlates well with reference."""
        try:
            runner._log_message(f"[QA] Verifying corrected track quality (threshold: {threshold:.1f}%)")

            # Decode both tracks to memory for correlation check
            ref_pcm = self._decode_to_memory(ref_path, runner, tool_paths)
            corrected_pcm = self._decode_to_memory(str(corrected_path), runner, tool_paths)

            if ref_pcm is None or corrected_pcm is None:
                runner._log_message("[QA] Failed to decode audio for quality check")
                return False

            # Take a 15-second sample from the middle for correlation
            sample_length = 15 * 48000  # 15 seconds at 48kHz
            ref_mid = len(ref_pcm) // 2
            corr_mid = len(corrected_pcm) // 2

            ref_sample = ref_pcm[ref_mid:ref_mid + sample_length]
            corr_sample = corrected_pcm[corr_mid:corr_mid + sample_length]

            # Make sure samples are same length
            min_len = min(len(ref_sample), len(corr_sample))
            if min_len < 48000:  # Less than 1 second
                runner._log_message("[QA] Sample too short for reliable QA")
                return False

            ref_sample = ref_sample[:min_len]
            corr_sample = corr_sample[:min_len]

            # Normalize samples
            ref_norm = (ref_sample - np.mean(ref_sample)) / (np.std(ref_sample) + 1e-9)
            corr_norm = (corr_sample - np.mean(corr_sample)) / (np.std(corr_sample) + 1e-9)

            # Cross-correlation
            correlation = correlate(ref_norm, corr_norm, mode='full')
            peak_corr = np.max(np.abs(correlation))

            # Calculate match percentage
            match_pct = (peak_corr / (np.sqrt(np.sum(ref_norm**2) * np.sum(corr_norm**2)) + 1e-9)) * 100.0

            runner._log_message(f"[QA] Correlation match: {match_pct:.1f}%")

            return match_pct >= threshold

        except Exception as e:
            runner._log_message(f"[QA] Error during quality check: {e}")
            return False

    def _decode_to_memory(self, file_path: str, runner: CommandRunner, tool_paths: dict) -> Optional[np.ndarray]:
        """Decode audio file to numpy array."""
        try:
            cmd = [
                'ffmpeg', '-nostdin', '-v', 'error',
                '-i', str(file_path),
                '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'
            ]

            pcm_bytes = runner.run(cmd, tool_paths, is_binary=True)
            if not pcm_bytes or not isinstance(pcm_bytes, bytes):
                return None

            return np.frombuffer(pcm_bytes, dtype=np.float32)

        except Exception:
            return None

    def _replace_and_preserve_track(self, extracted_items: List[PlanItem], original_track: PlanItem,
                                  corrected_path: Path, temp_dir: Path, source_key: str):
        """Replace original track with corrected version and add original to end of audio group."""

        # Create new track model for corrected version
        corrected_track = Track(
            source=source_key,
            id=original_track.track.id,  # Keep same ID for reference
            type=TrackType.AUDIO,
            props=StreamProps(
                codec_id='A_FLAC',  # Corrected tracks are always FLAC
                lang=original_track.track.props.lang,
                name=f"{original_track.track.props.name} (Corrected)" if original_track.track.props.name else "Corrected Audio"
            )
        )

        # Create corrected plan item
        corrected_item = PlanItem(
            track=corrected_track,
            extracted_path=corrected_path,
            is_default=original_track.is_default,  # Keep default status
            is_forced_display=False,
            apply_track_name=True,
            convert_to_ass=False,
            rescale=False,
            size_multiplier=1.0
        )

        # Create preserved original track
        preserved_track = Track(
            source=source_key,
            id=original_track.track.id + 1000,  # Unique ID
            type=TrackType.AUDIO,
            props=StreamProps(
                codec_id=original_track.track.props.codec_id,
                lang=original_track.track.props.lang,
                name=f"{original_track.track.props.name} (Original)" if original_track.track.props.name else "Original Audio"
            )
        )

        preserved_item = PlanItem(
            track=preserved_track,
            extracted_path=original_track.extracted_path,
            is_default=False,  # Never default
            is_forced_display=False,
            apply_track_name=True,
            convert_to_ass=False,
            rescale=False,
            size_multiplier=1.0
        )

        # Find the position of the original track
        original_index = extracted_items.index(original_track)

        # Replace original with corrected
        extracted_items[original_index] = corrected_item

        # Find position to insert preserved original (end of audio group)
        audio_end_pos = len(extracted_items)
        for i, item in enumerate(extracted_items):
            if item.track.type != TrackType.AUDIO:
                audio_end_pos = i
                break

        # Insert preserved original at end of audio group
        extracted_items.insert(audio_end_pos, preserved_item)
