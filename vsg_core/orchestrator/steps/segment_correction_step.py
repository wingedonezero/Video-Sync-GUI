# vsg_core/orchestrator/steps/segment_correction_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict
import tempfile
import numpy as np
from scipy.signal import correlate

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import PlanItem
from vsg_core.models.media import Track, StreamProps
from vsg_core.models.enums import TrackType

class SegmentCorrectionStep:
    """
    Performs segmented audio correction for sources that have stepping detected.
    Creates corrected audio tracks using precise silence insertion.
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

            # Create corrected track
            corrected_path = self._create_corrected_track(
                audio_track.extracted_path, edl, ctx.temp_dir, runner, ctx.tool_paths, source_key, ctx
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

    def _find_selected_audio_track(self, extracted_items: List[PlanItem], source_key: str) -> Optional[PlanItem]:
        """Find the first audio track from the specified source in the user's selection."""
        for item in extracted_items:
            if item.track.source == source_key and item.track.type == TrackType.AUDIO:
                return item
        return None

    def _create_corrected_track(self, original_path: Path, edl: List[Dict], temp_dir: Path,
                              runner: CommandRunner, tool_paths: dict, source_key: str, ctx: Context) -> Optional[Path]:
        """Create corrected track by splitting audio and inserting precise amounts of silence."""
        segments_dir = temp_dir / f"segments_{source_key.replace(' ', '_')}"
        segments_dir.mkdir(exist_ok=True)

        # Step 1: ALWAYS decode the entire audio to PCM WAV first for reliable segmentation
        # This works for ALL audio formats (TrueHD, DTS, AC3, FLAC, etc.)
        decoded_audio = segments_dir / "decoded_full.wav"

        # Try multiple decode strategies for problematic formats like TrueHD
        decode_strategies = [
            # Strategy 1: Standard PCM decode
            [
                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                '-i', str(original_path),
                '-c:a', 'pcm_s24le', '-ar', '48000', str(decoded_audio)
            ],
            # Strategy 2: Force format detection and use best PCM depth
            [
                'ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 'truehd',
                '-i', str(original_path),
                '-c:a', 'pcm_s32le', '-ar', '48000', str(decoded_audio)
            ],
            # Strategy 3: Let ffmpeg auto-select best decoder and use float PCM
            [
                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                '-i', str(original_path),
                '-c:a', 'pcm_f32le', '-ar', '48000', str(decoded_audio)
            ],
            # Strategy 4: Use FLAC as intermediate (lossless, more compatible)
            [
                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                '-i', str(original_path),
                '-c:a', 'flac', '-ar', '48000', str(decoded_audio.with_suffix('.flac'))
            ]
        ]

        decode_success = False
        for i, decode_cmd in enumerate(decode_strategies):
            runner._log_message(f"  Trying decode strategy {i+1}...")
            if runner.run(decode_cmd, tool_paths):
                # Check if output file exists (handle .flac vs .wav)
                if i == 3:  # FLAC strategy
                    test_file = decoded_audio.with_suffix('.flac')
                    if test_file.exists():
                        decoded_audio = test_file  # Use FLAC file instead
                        decode_success = True
                        break
                else:
                    if decoded_audio.exists():
                        decode_success = True
                        break
            runner._log_message(f"  Strategy {i+1} failed")

        if not decode_success:
            runner._log_message(f"[ERROR] All decode strategies failed for {original_path.name}")
            return None

        runner._log_message(f"  Successfully decoded {original_path.name} to {decoded_audio.suffix.upper()}")

        # Step 2: Split the decoded PCM into segments based on EDL (KEY FIX HERE)
        segment_files = []
        for i, segment in enumerate(edl):
            start_time = segment['start_time']
            end_time = segment['end_time']
            duration = end_time - start_time
            segment_file = segments_dir / f"segment_{i}.flac"

            # CRITICAL FIX: Extract from decoded_audio, NOT original_path
            cmd = [
                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                '-i', str(decoded_audio),  # This is the key change!
                '-ss', str(start_time), '-t', str(duration),
                '-c:a', 'flac', str(segment_file)
            ]

            if runner.run(cmd, tool_paths) and segment_file.exists():
                segment_files.append((segment_file, segment))
                runner._log_message(f"  Extracted segment {i+1}: {start_time:.1f}s-{end_time:.1f}s")
            else:
                runner._log_message(f"[ERROR] Failed to extract segment {i+1} from decoded PCM")
                return None

        # Step 3: Create concat list with silence insertion
        concat_list = temp_dir / f"segments_concat_{source_key.replace(' ', '_')}.txt"
        with open(concat_list, 'w', encoding='utf-8') as f:
            for i, (segment_file, segment_info) in enumerate(segment_files):
                # Insert silence before this segment (except the first)
                if i > 0:
                    prev_delay = edl[i-1]['delay_ms']
                    curr_delay = segment_info['delay_ms']
                    silence_ms = curr_delay - prev_delay

                    if silence_ms > 10:  # Only insert if significant
                        silence_file = segments_dir / f"silence_{i}.flac"
                        silence_duration = silence_ms / 1000.0

                        # Fixed silence generation syntax
                        silence_cmd = [
                            'ffmpeg', '-y', '-v', 'error', '-nostdin',
                            '-f', 'lavfi', '-i', f'anullsrc=rate=48000:sample_fmt=s16:channels=2',
                            '-t', str(silence_duration), '-c:a', 'flac', str(silence_file)
                        ]

                        if runner.run(silence_cmd, tool_paths) and silence_file.exists():
                            f.write(f"file '{silence_file.absolute()}'\n")
                            runner._log_message(f"  Inserted {silence_ms}ms silence before segment {i+1}")
                        else:
                            runner._log_message(f"[WARN] Failed to create silence for segment {i+1}")
                    elif silence_ms < -10:  # Need to trim audio
                        runner._log_message(f"[WARN] Segment {i+1} needs {abs(silence_ms)}ms trimmed - not implemented")

                f.write(f"file '{segment_file.absolute()}'\n")

        # Step 4: Concatenate all segments with silence
        output_file = temp_dir / f"corrected_{source_key.replace(' ', '_')}.flac"
        concat_cmd = [
            'ffmpeg', '-y', '-v', 'error', '-nostdin',
            '-f', 'concat', '-safe', '0', '-i', str(concat_list),
            '-c:a', 'copy', str(output_file)
        ]

        if runner.run(concat_cmd, tool_paths) and output_file.exists():
            runner._log_message(f"  Created corrected track: {output_file.name}")
            return output_file
        else:
            runner._log_message(f"[ERROR] Failed to concatenate corrected track")
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
