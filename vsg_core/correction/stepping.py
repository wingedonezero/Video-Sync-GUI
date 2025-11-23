# vsg_core/correction/stepping.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import gc
import copy
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum, auto

import numpy as np
from scipy.signal import correlate
from collections import Counter

from ..io.runner import CommandRunner
from ..analysis.audio_corr import get_audio_stream_info, run_audio_correlation
from ..orchestrator.steps.context import Context
from ..models.media import StreamProps, Track
from ..extraction.tracks import extract_tracks
from ..models.enums import TrackType

class CorrectionVerdict(Enum):
    UNIFORM = auto()
    STEPPED = auto()
    FAILED = auto()

@dataclass
class CorrectionResult:
    verdict: CorrectionVerdict
    data: Any = None

@dataclass(unsafe_hash=True)
class AudioSegment:
    """Represents an action point on the target timeline for the assembly function."""
    start_s: float
    end_s: float
    delay_ms: int
    drift_rate_ms_s: float = 0.0

def generate_edl_from_correlation(chunks: List[Dict], config: Dict, runner: CommandRunner, diagnosis_details: Optional[Dict] = None) -> List[AudioSegment]:
    """
    Generate a simplified EDL from correlation chunks for subtitle adjustment.
    Used when stepping is detected but no audio correction is needed.

    Args:
        chunks: List of correlation chunk results with 'delay', 'accepted', and 'start' keys
        config: Configuration dictionary
        runner: CommandRunner for logging
        diagnosis_details: Optional diagnosis details with filtered cluster information

    Returns:
        List of AudioSegment objects representing delay regions
    """
    accepted = [c for c in chunks if c.get('accepted', False)]
    if not accepted:
        runner._log_message("[EDL Generation] No accepted chunks available for EDL generation")
        return []

    # Apply cluster filtering if diagnosis details are provided
    if diagnosis_details:
        correction_mode = diagnosis_details.get('correction_mode', 'full')
        if correction_mode == 'filtered':
            invalid_clusters = diagnosis_details.get('invalid_clusters', {})
            validation_results = diagnosis_details.get('validation_results', {})

            if invalid_clusters:
                # Build list of invalid time ranges
                invalid_time_ranges = []
                for label in invalid_clusters.keys():
                    if label in validation_results:
                        time_range = validation_results[label]['time_range']
                        invalid_time_ranges.append(time_range)

                # Filter out chunks that fall within invalid clusters
                filtered_accepted = []
                filtered_count = 0
                for chunk in accepted:
                    chunk_time = chunk['start']
                    in_invalid_cluster = any(
                        start <= chunk_time <= end
                        for start, end in invalid_time_ranges
                    )
                    if not in_invalid_cluster:
                        filtered_accepted.append(chunk)
                    else:
                        filtered_count += 1

                runner._log_message(f"[EDL Generation] Filtered {filtered_count} chunks from invalid clusters")
                runner._log_message(f"[EDL Generation] Using {len(filtered_accepted)} chunks from valid clusters only")
                accepted = filtered_accepted

                if not accepted:
                    runner._log_message("[EDL Generation] No chunks remaining after filtering")
                    return []

    # Group consecutive chunks by delay (within tolerance)
    tolerance_ms = config.get('segment_triage_std_dev_ms', 50)
    edl = []
    current_delay = accepted[0]['delay']
    edl.append(AudioSegment(start_s=0.0, end_s=0.0, delay_ms=current_delay))

    runner._log_message(f"[EDL Generation] Starting with delay: {current_delay}ms")

    for chunk in accepted[1:]:
        delay_diff = abs(chunk['delay'] - current_delay)
        if delay_diff > tolerance_ms:
            # Delay change detected - add new segment
            boundary_time_s = chunk['start']  # Chunk start time in seconds
            current_delay = chunk['delay']
            edl.append(AudioSegment(
                start_s=boundary_time_s,
                end_s=boundary_time_s,
                delay_ms=current_delay,
                drift_rate_ms_s=0.0  # No drift analysis for subtitle-only
            ))
            runner._log_message(f"[EDL Generation] Delay change at {boundary_time_s:.1f}s → {current_delay}ms")

    runner._log_message(f"[EDL Generation] Generated EDL with {len(edl)} segment(s)")
    return edl

def _get_audio_properties(file_path: str, stream_index: int, runner: CommandRunner, tool_paths: dict) -> Tuple[int, str, int]:
    cmd = [ 'ffprobe', '-v', 'error', '-select_streams', f'a:{stream_index}', '-show_entries', 'stream=channels,channel_layout,sample_rate', '-of', 'json', str(file_path) ]
    out = runner.run(cmd, tool_paths)
    if not out: raise RuntimeError(f"Could not probe audio properties for {file_path}")
    try:
        stream_info = json.loads(out)['streams'][0]
        channels = int(stream_info.get('channels', 2))
        channel_layout = stream_info.get('channel_layout', {1: 'mono', 2: 'stereo', 6: '5.1(side)', 8: '7.1'}.get(channels, 'stereo'))
        sample_rate = int(stream_info.get('sample_rate', 48000))
        return channels, channel_layout, sample_rate
    except (json.JSONDecodeError, IndexError, KeyError) as e: raise RuntimeError(f"Failed to parse ffprobe audio properties: {e}")

class SteppingCorrector:
    def __init__(self, runner: CommandRunner, tool_paths: dict, config: dict):
        self.runner = runner
        self.tool_paths = tool_paths
        self.config = config
        self.log = runner._log_message

    def _get_codec_id(self, file_path: str) -> str:
        """Uses ffprobe to get the codec name for a given audio file."""
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)]
        out = self.runner.run(cmd, self.tool_paths)
        return (out or '').strip().lower()

    def _decode_to_memory(self, file_path: str, stream_index: int, sample_rate: int, channels: int = 1) -> Optional[np.ndarray]:
        cmd = [ 'ffmpeg', '-nostdin', '-v', 'error', '-i', str(file_path), '-map', f'0:a:{stream_index}', '-ac', str(channels), '-ar', str(sample_rate), '-f', 's32le', '-' ]
        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes:
            # Ensure buffer size is a multiple of element size (4 bytes for int32)
            # This fixes issues with Opus and other codecs that may produce unaligned output
            element_size = np.dtype(np.int32).itemsize
            aligned_size = (len(pcm_bytes) // element_size) * element_size
            if aligned_size != len(pcm_bytes):
                trimmed_bytes = len(pcm_bytes) - aligned_size
                self.log(f"[BUFFER ALIGNMENT] Trimmed {trimmed_bytes} bytes from {Path(file_path).name} (likely Opus/other codec)")
                pcm_bytes = pcm_bytes[:aligned_size]
            return np.frombuffer(pcm_bytes, dtype=np.int32)
        self.log(f"[ERROR] SteppingCorrector failed to decode audio stream {stream_index} from '{Path(file_path).name}'")
        return None

    def _get_delay_for_chunk(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, start_sample: int, num_samples: int, sample_rate: int, locality_samples: int) -> Optional[int]:
        end_sample = start_sample + num_samples
        if end_sample > len(ref_pcm): return None
        ref_chunk = ref_pcm[start_sample:end_sample]

        search_center = start_sample
        search_start = max(0, search_center - locality_samples)
        search_end = min(len(analysis_pcm), search_center + num_samples + locality_samples)
        analysis_chunk = analysis_pcm[search_start:search_end]

        if len(ref_chunk) < 100 or len(analysis_chunk) < len(ref_chunk): return None
        ref_std, analysis_std = np.std(ref_chunk), np.std(analysis_chunk)
        if ref_std < 1e-6 or analysis_std < 1e-6: return None

        r = (ref_chunk - np.mean(ref_chunk)) / (ref_std + 1e-9)
        t = (analysis_chunk - np.mean(analysis_chunk)) / (analysis_std + 1e-9)
        c = correlate(r, t, mode='valid', method='fft')

        if len(c) == 0: return None
        abs_c = np.abs(c)
        k = np.argmax(abs_c)

        peak_val = abs_c[k]
        noise_floor = np.median(abs_c) + 1e-9
        confidence_ratio = peak_val / noise_floor

        min_confidence = self.config.get('segment_min_confidence_ratio', 5.0)
        if confidence_ratio < min_confidence:
            return None

        lag_in_window = k
        absolute_lag_start = search_start + lag_in_window
        delay_samples = absolute_lag_start - start_sample
        return int(round((delay_samples / sample_rate) * 1000.0))

    def _perform_coarse_scan(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, sample_rate: int) -> List[Tuple[float, int]]:
        self.log("  [SteppingCorrector] Stage 1: Performing coarse scan to find delay zones...")
        chunk_duration_s = self.config.get('segment_coarse_chunk_s', 15)
        step_duration_s = self.config.get('segment_coarse_step_s', 60)
        locality_s = self.config.get('segment_search_locality_s', 10)

        chunk_samples = int(chunk_duration_s * sample_rate)
        step_samples = int(step_duration_s * sample_rate)
        locality_samples = int(locality_s * sample_rate)
        coarse_map = []
        num_samples = min(len(ref_pcm), len(analysis_pcm))
        duration_s = len(ref_pcm) / float(sample_rate)

        # Use stepping-specific scan ranges (independent from main analysis settings)
        start_pct = self.config.get('stepping_scan_start_percentage', 5.0)
        end_pct = self.config.get('stepping_scan_end_percentage', 99.0)
        scan_start_s = duration_s * (start_pct / 100.0)
        scan_end_s = duration_s * (end_pct / 100.0)
        start_offset_samples = int(scan_start_s * sample_rate)
        scan_end_limit = min(int(scan_end_s * sample_rate), num_samples)
        scan_end_point = scan_end_limit - chunk_samples - step_samples

        for start_sample in range(start_offset_samples, scan_end_point, step_samples):
            delay = self._get_delay_for_chunk(ref_pcm, analysis_pcm, start_sample, chunk_samples, sample_rate, locality_samples)
            if delay is not None:
                timestamp_s = start_sample / sample_rate
                coarse_map.append((timestamp_s, delay))
                self.log(f"    - Coarse point at {timestamp_s:.1f}s: delay = {delay}ms")
        return coarse_map

    def _find_boundary_in_zone(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, sample_rate: int, zone_start_s: float, zone_end_s: float, delay_before: int, delay_after: int) -> float:
        self.log(f"  [SteppingCorrector] Stage 2: Performing fine scan in zone {zone_start_s:.1f}s - {zone_end_s:.1f}s...")
        zone_start_sample, zone_end_sample = int(zone_start_s * sample_rate), int(zone_end_s * sample_rate)

        fine_chunk_s = self.config.get('segment_fine_chunk_s', 2.0)
        locality_s = self.config.get('segment_search_locality_s', 10)
        iterations = self.config.get('segment_fine_iterations', 10)

        chunk_samples = int(fine_chunk_s * sample_rate)
        locality_samples = int(locality_s * sample_rate)
        low, high = zone_start_sample, zone_end_sample

        for _ in range(iterations):
            if high - low < chunk_samples: break
            mid = (low + high) // 2
            delay = self._get_delay_for_chunk(ref_pcm, analysis_pcm, mid, chunk_samples, sample_rate, locality_samples)
            if delay is not None:
                if abs(delay - delay_before) < abs(delay - delay_after): low = mid
                else: high = mid
            else: low += chunk_samples

        final_boundary_s = high / sample_rate
        self.log(f"    - Found precise boundary at: {final_boundary_s:.3f}s")
        return final_boundary_s

    def _extract_content_from_reference(
        self,
        ref_pcm: np.ndarray,
        analysis_pcm: np.ndarray,
        boundary_s_target: float,
        gap_duration_ms: float,
        sample_rate: int,
        current_delay_ms: float
    ) -> Tuple[Optional[np.ndarray], float, str]:
        """
        Attempts to extract matching content from reference audio to fill a gap.

        Args:
            boundary_s_target: Position on the TARGET timeline (where the gap will be inserted)
            current_delay_ms: The current delay BEFORE the jump (to convert to reference timeline)

        Returns:
            Tuple of (extracted_pcm, correlation_score, fill_type)
            fill_type: 'content' if good match found, 'silence' otherwise
        """
        fill_mode = self.config.get('stepping_fill_mode', 'auto')
        correlation_threshold = self.config.get('stepping_content_correlation_threshold', 0.5)
        search_window_s = self.config.get('stepping_content_search_window_s', 5.0)

        # Force silence mode if configured
        if fill_mode == 'silence':
            return None, 0.0, 'silence'

        gap_samples = int((gap_duration_ms / 1000.0) * sample_rate)

        # CRITICAL FIX: Convert target timeline position to reference timeline position
        # The boundary_s_target is on the target (analysis) timeline, but we need to extract
        # from the reference timeline. The current delay tells us the offset.
        # Positive delay means target is EARLY, so reference position is EARLIER in time.
        boundary_s_ref = boundary_s_target - (current_delay_ms / 1000.0)

        # Safeguard: Ensure reference position doesn't go negative
        if boundary_s_ref < 0:
            self.log(f"      [Smart Fill] WARNING: Reference position would be negative ({boundary_s_ref:.3f}s), clamping to 0.0s")
            boundary_s_ref = 0.0

        boundary_sample_ref = int(boundary_s_ref * sample_rate)

        self.log(f"      [Smart Fill] Target boundary: {boundary_s_target:.3f}s, Current delay: {current_delay_ms:+.0f}ms → Reference position: {boundary_s_ref:.3f}s")

        # Define search window in reference audio around the reference position
        search_window_samples = int(search_window_s * sample_rate)
        search_start = max(0, boundary_sample_ref - search_window_samples)
        search_end = min(len(ref_pcm), boundary_sample_ref + search_window_samples + gap_samples)

        if search_end - search_start < gap_samples:
            self.log(f"      [Smart Fill] Insufficient reference audio for content search.")
            return None, 0.0, 'silence'

        # Try to find best matching content in reference
        # Extract from the REFERENCE timeline position
        if boundary_sample_ref + gap_samples <= len(ref_pcm):
            candidate_content = ref_pcm[boundary_sample_ref:boundary_sample_ref + gap_samples]

            # Check if this is actual content (not silence)
            content_std = np.std(candidate_content)
            if content_std < 1e-6:
                self.log(f"      [Smart Fill] Reference has silence at position → using silence fill")
                return None, 0.0, 'silence'

            # In 'content' mode, always use reference content if available
            if fill_mode == 'content':
                self.log(f"      [Smart Fill] Extracting {gap_duration_ms:.0f}ms from reference at {boundary_s_ref:.3f}s (forced mode)")
                return candidate_content, 1.0, 'content'

            # In 'auto' mode, correlate to verify it's a good match
            # Look for where this content might appear in the analysis audio
            if len(analysis_pcm) > gap_samples:
                # Normalize candidate for correlation
                candidate_norm = (candidate_content - np.mean(candidate_content)) / (content_std + 1e-9)

                # Search in analysis audio near the boundary (on TARGET timeline)
                boundary_sample_target = int(boundary_s_target * sample_rate)
                analysis_search_start = max(0, boundary_sample_target - search_window_samples)
                analysis_search_end = min(len(analysis_pcm), boundary_sample_target + search_window_samples)
                analysis_search_region = analysis_pcm[analysis_search_start:analysis_search_end]

                if len(analysis_search_region) > gap_samples:
                    analysis_std = np.std(analysis_search_region)
                    if analysis_std > 1e-6:
                        analysis_norm = (analysis_search_region - np.mean(analysis_search_region)) / (analysis_std + 1e-9)

                        # Correlate to find if this content exists in analysis
                        corr = correlate(candidate_norm, analysis_norm, mode='valid', method='fft')

                        if len(corr) > 0:
                            max_corr = np.max(np.abs(corr))
                            normalized_corr = max_corr / len(candidate_norm)

                            self.log(f"      [Smart Fill] Content correlation: {normalized_corr:.3f} (threshold: {correlation_threshold:.3f})")

                            if normalized_corr < correlation_threshold:
                                # Low correlation - this content is NOT in analysis, so we should add it
                                self.log(f"      [Smart Fill] Content appears to be missing from analysis → extracting from reference")
                                return candidate_content, normalized_corr, 'content'
                            else:
                                # High correlation means content already exists in analysis
                                self.log(f"      [Smart Fill] Content already exists in analysis → using silence")
                                return None, normalized_corr, 'silence'

            # Default to using content if we can't determine otherwise
            if fill_mode == 'auto':
                self.log(f"      [Smart Fill] Using reference content at {boundary_s_ref:.3f}s (auto mode, unable to verify)")
                return candidate_content, 0.5, 'content'

        # If we get here, use silence
        return None, 0.0, 'silence'

    def _analyze_internal_drift(self, edl: List[AudioSegment], ref_pcm: np.ndarray, analysis_pcm: np.ndarray, sample_rate: int, codec_name: str) -> List[AudioSegment]:
        self.log(f"  [SteppingCorrector] Stage 2.5: Analyzing segments for internal drift (Codec: {codec_name})...")
        final_edl = []

        r_squared_threshold = self.config.get('segment_drift_r2_threshold', 0.75)
        slope_threshold = self.config.get('segment_drift_slope_threshold', 0.7)
        outlier_sensitivity = self.config.get('segment_drift_outlier_sensitivity', 1.5)
        scan_buffer_pct = self.config.get('segment_drift_scan_buffer_pct', 2.0)
        pcm_duration_s = len(analysis_pcm) / float(sample_rate)

        for i, current_segment in enumerate(edl):
            segment_start_s = current_segment.start_s
            segment_end_s = edl[i+1].start_s if i + 1 < len(edl) else pcm_duration_s
            segment_duration_s = segment_end_s - segment_start_s

            if segment_duration_s < 1.0:
                self.log(f"    - Skipping segment from {segment_start_s:.2f}s to {segment_end_s:.2f}s: too short ({segment_duration_s:.2f}s)")
                final_edl.append(current_segment)
                continue

            if segment_duration_s < 20.0:
                final_edl.append(current_segment)
                continue

            self.log(f"    - Scanning segment from {segment_start_s:.2f}s to {segment_end_s:.2f}s (Target Timeline)...")

            scan_chunk_s = 5.0
            num_scans = max(5, int(segment_duration_s / 20.0))
            chunk_samples = int(scan_chunk_s * sample_rate)
            locality_samples = int(self.config.get('segment_search_locality_s', 10) * sample_rate)

            offset = min(30.0, segment_duration_s * (scan_buffer_pct / 100.0))
            scan_window_start = segment_start_s + offset
            scan_window_end = segment_end_s - offset - scan_chunk_s

            if scan_window_end <= scan_window_start:
                final_edl.append(current_segment)
                continue

            scan_points_s_target = np.linspace(scan_window_start, scan_window_end, num=num_scans)

            times, delays = [], []
            for t_s_target in scan_points_s_target:
                base_delay_s = current_segment.delay_ms / 1000.0
                t_s_ref = t_s_target - base_delay_s
                start_sample_ref = int(t_s_ref * sample_rate)

                delay = self._get_delay_for_chunk(ref_pcm, analysis_pcm, start_sample_ref, chunk_samples, sample_rate, locality_samples)
                if delay is not None:
                    times.append(t_s_ref)
                    delays.append(delay)

            if len(times) < 4:
                final_edl.append(current_segment)
                continue

            delays_arr = np.array(delays)
            median = np.median(delays_arr)
            std_dev = np.std(delays_arr)

            filtered_times, filtered_delays = [], []
            if std_dev > 0:
                for t, d in zip(times, delays):
                    if abs(d - median) < outlier_sensitivity * std_dev:
                        filtered_times.append(t)
                        filtered_delays.append(d)
            else:
                filtered_times, filtered_delays = times, delays

            if len(filtered_times) < 4:
                self.log(f"      [STABLE] Not enough consistent points after outlier rejection.")
                final_edl.append(current_segment)
                continue

            self.log(f"      - Kept {len(filtered_times)}/{len(times)} points for drift calculation after outlier rejection.")

            times_arr, delays_arr = np.array(filtered_times), np.array(filtered_delays)

            try:
                correlation_matrix = np.corrcoef(times_arr, delays_arr)
                if np.isnan(correlation_matrix).any():
                    r_squared = 0.0
                else:
                    r_squared = correlation_matrix[0, 1]**2

                if np.isnan(r_squared):
                    r_squared = 0.0

                slope, _ = np.polyfit(times_arr, delays_arr, 1)
            except (np.linalg.LinAlgError, ValueError):
                r_squared, slope = 0.0, 0.0

            if r_squared > r_squared_threshold and abs(slope) > slope_threshold:
                self.log(f"      [DRIFT DETECTED] Found internal drift of {slope:+.2f} ms/s in segment (R²={r_squared:.2f}).")
                current_segment.drift_rate_ms_s = slope
            else:
                self.log(f"      [STABLE] Segment is internally stable (slope={slope:+.2f} ms/s, R²={r_squared:.2f}).")

            final_edl.append(current_segment)

        return final_edl

    def _assemble_from_segments_via_ffmpeg(self, pcm_data: np.ndarray, edl: List[AudioSegment], channels: int, channel_layout: str, sample_rate: int, out_path: Path, log_prefix: str, ref_pcm: Optional[np.ndarray] = None) -> bool:
        self.log(f"  [{log_prefix}] Assembling audio from {len(edl)} segment(s) via FFmpeg...")

        assembly_dir = out_path.parent / f"assembly_{out_path.stem}"
        assembly_dir.mkdir(exist_ok=True)

        concat_list_path = assembly_dir / "concat_list.txt"
        segment_files = []
        base_delay_ms = edl[0].delay_ms
        current_base_delay = base_delay_ms

        try:
            pcm_duration_s = len(pcm_data) / float(sample_rate * channels)

            for i, segment in enumerate(edl):
                silence_to_add_ms = segment.delay_ms - current_base_delay
                if abs(silence_to_add_ms) > 10:
                    if silence_to_add_ms > 0:
                        # Try Smart Fill if reference audio is available
                        fill_content = None
                        fill_type = 'silence'

                        if ref_pcm is not None:
                            fill_content, corr_score, fill_type = self._extract_content_from_reference(
                                ref_pcm=ref_pcm,
                                analysis_pcm=pcm_data,
                                boundary_s_target=segment.start_s,
                                gap_duration_ms=silence_to_add_ms,
                                sample_rate=sample_rate,
                                current_delay_ms=current_base_delay
                            )

                        if fill_content is not None and fill_type == 'content':
                            # Use extracted content from reference
                            self.log(f"    - At {segment.start_s:.3f}s: Inserting {silence_to_add_ms}ms of CONTENT from reference (Smart Fill, correlation={corr_score:.3f}).")
                            content_file = assembly_dir / f"content_{i:03d}.flac"

                            # Convert mono ref_pcm to match target channels if needed
                            if channels == 1:
                                content_to_encode = fill_content
                            else:
                                # Duplicate mono to all channels
                                content_mono = fill_content
                                content_interleaved = np.zeros(len(content_mono) * channels, dtype=np.int32)
                                for ch in range(channels):
                                    content_interleaved[ch::channels] = content_mono
                                content_to_encode = content_interleaved

                            encode_cmd = [
                                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                                '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels),
                                '-channel_layout', channel_layout, '-i', '-',
                                '-map_metadata', '-1',
                                '-map_metadata:s:a', '-1',
                                '-fflags', '+bitexact',
                                '-c:a', 'flac',
                                str(content_file)
                            ]
                            if self.runner.run(encode_cmd, self.tool_paths, is_binary=True, input_data=content_to_encode.tobytes()) is not None:
                                segment_files.append(f"file '{content_file.name}'")
                        else:
                            # Use silence (traditional approach)
                            self.log(f"    - At {segment.start_s:.3f}s: Inserting {silence_to_add_ms}ms of silence.")
                            silence_duration_s = silence_to_add_ms / 1000.0
                            silence_file = assembly_dir / f"silence_{i:03d}.flac"

                            silence_samples = int(silence_duration_s * sample_rate) * channels
                            silence_pcm = np.zeros(silence_samples, dtype=np.int32)

                            encode_cmd = [
                                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                                '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels),
                                '-channel_layout', channel_layout, '-i', '-',
                                '-map_metadata', '-1',
                                '-map_metadata:s:a', '-1',
                                '-fflags', '+bitexact',
                                '-c:a', 'flac',
                                str(silence_file)
                            ]
                            if self.runner.run(encode_cmd, self.tool_paths, is_binary=True, input_data=silence_pcm.tobytes()) is not None:
                                segment_files.append(f"file '{silence_file.name}'")
                    else:
                        self.log(f"    - At {segment.start_s:.3f}s: Removing {-silence_to_add_ms}ms of audio.")

                current_base_delay = segment.delay_ms

                segment_start_s_on_target_timeline = segment.start_s
                segment_end_s_on_target_timeline = edl[i+1].start_s if i + 1 < len(edl) else pcm_duration_s

                if silence_to_add_ms < 0:
                    segment_start_s_on_target_timeline += abs(silence_to_add_ms) / 1000.0

                if segment_end_s_on_target_timeline <= segment_start_s_on_target_timeline:
                    continue

                start_sample = int(segment_start_s_on_target_timeline * sample_rate) * channels
                end_sample = int(segment_end_s_on_target_timeline * sample_rate) * channels

                if end_sample > len(pcm_data):
                    end_sample = len(pcm_data)

                chunk_to_process = pcm_data[start_sample:end_sample]

                if chunk_to_process.size == 0:
                    continue

                segment_file = assembly_dir / f"segment_{i:03d}.flac"

                encode_cmd = [
                    'ffmpeg', '-y', '-v', 'error', '-nostdin',
                    '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels),
                    '-channel_layout', channel_layout, '-i', '-',
                    '-map_metadata', '-1',
                    '-map_metadata:s:a', '-1',
                    '-fflags', '+bitexact',
                    '-c:a', 'flac',
                    str(segment_file)
                ]
                if self.runner.run(encode_cmd, self.tool_paths, is_binary=True, input_data=chunk_to_process.tobytes()) is None:
                    raise RuntimeError(f"Failed to encode segment {i}")

                if abs(segment.drift_rate_ms_s) > 0.5:
                    self.log(f"    - Applying drift correction ({segment.drift_rate_ms_s:+.2f} ms/s) to segment {i}.")
                    tempo_ratio = 1000.0 / (1000.0 + segment.drift_rate_ms_s)
                    corrected_file = assembly_dir / f"segment_{i:03d}_corrected.flac"

                    resample_engine = self.config.get('segment_resample_engine', 'aresample')
                    filter_chain = ''

                    if resample_engine == 'rubberband':
                        self.log(f"    - Using 'rubberband' engine for high-quality resampling.")
                        rb_opts = [f'tempo={tempo_ratio}']

                        if not self.config.get('segment_rb_pitch_correct', False):
                            rb_opts.append(f'pitch={tempo_ratio}')

                        rb_opts.append(f"transients={self.config.get('segment_rb_transients', 'crisp')}")

                        if self.config.get('segment_rb_smoother', True):
                            rb_opts.append('smoother=on')

                        if self.config.get('segment_rb_pitchq', True):
                            rb_opts.append('pitchq=on')

                        filter_chain = 'rubberband=' + ':'.join(rb_opts)

                    elif resample_engine == 'atempo':
                        self.log(f"    - Using 'atempo' engine for fast resampling.")
                        filter_chain = f'atempo={tempo_ratio}'

                    else: # Default to aresample
                        self.log(f"    - Using 'aresample' engine for high-quality resampling.")
                        new_sample_rate = sample_rate * tempo_ratio
                        filter_chain = f'asetrate={new_sample_rate},aresample={sample_rate}'

                    resample_cmd = [
                        'ffmpeg', '-y', '-nostdin', '-v', 'error',
                        '-i', str(segment_file),
                        '-af', filter_chain,
                        '-map_metadata', '-1',
                        '-map_metadata:s:a', '-1',
                        '-fflags', '+bitexact',
                        str(corrected_file)
                    ]

                    if self.runner.run(resample_cmd, self.tool_paths) is None:
                        error_msg = f"Resampling with '{resample_engine}' failed for segment {i}."
                        if resample_engine == 'rubberband':
                            error_msg += " (Ensure your FFmpeg build includes 'librubberband')."
                        raise RuntimeError(error_msg)

                    segment_file = corrected_file

                segment_files.append(f"file '{segment_file.name}'")

            if not segment_files:
                raise RuntimeError("No segments were generated for assembly.")

            concat_list_path.write_text('\n'.join(segment_files), encoding='utf-8')

            final_assembly_cmd = [
                'ffmpeg', '-y', '-v', 'error',
                '-f', 'concat', '-safe', '0', '-i', str(concat_list_path),
                '-map_metadata', '-1',
                '-map_metadata:s:a', '-1',
                '-fflags', '+bitexact',
                '-c:a', 'flac',
                str(out_path)
            ]
            if self.runner.run(final_assembly_cmd, self.tool_paths) is None:
                raise RuntimeError("Final FFmpeg concat assembly failed.")

            return True

        except Exception as e:
            self.log(f"    [ERROR] FFmpeg assembly failed: {e}")
            return False
        finally:
            if assembly_dir.exists():
                shutil.rmtree(assembly_dir, ignore_errors=True)

    def _filter_coarse_map_by_clusters(
        self,
        coarse_map: List[Tuple[float, int]],
        diagnosis_details: Dict,
        sample_rate: int
    ) -> List[Tuple[float, int]]:
        """
        Filters coarse_map to remove entries that fall within invalid clusters.
        Applies fallback strategy for filtered regions.

        Returns filtered coarse_map.
        """
        correction_mode = diagnosis_details.get('correction_mode', 'full')

        # If not in filtered mode, return original map
        if correction_mode != 'filtered':
            return coarse_map

        valid_clusters = diagnosis_details.get('valid_clusters', {})
        invalid_clusters = diagnosis_details.get('invalid_clusters', {})
        validation_results = diagnosis_details.get('validation_results', {})
        fallback_mode = diagnosis_details.get('fallback_mode', 'nearest')

        if not invalid_clusters:
            # No filtering needed
            return coarse_map

        self.log(f"  [Filtered Stepping] Filtering coarse map: {len(invalid_clusters)} invalid cluster(s) detected")
        self.log(f"  [Filtered Stepping] Fallback mode: {fallback_mode}")

        # Build a list of time ranges for invalid clusters
        invalid_time_ranges = []
        for label, members in invalid_clusters.items():
            if label in validation_results:
                time_range = validation_results[label]['time_range']
                invalid_time_ranges.append(time_range)
                self.log(f"    - Invalid cluster {label+1}: {time_range[0]:.1f}s - {time_range[1]:.1f}s will be filtered")

        # Filter coarse_map entries
        filtered_map = []
        skipped_count = 0

        for timestamp_s, delay in coarse_map:
            # Check if this timestamp falls within any invalid cluster
            in_invalid_cluster = any(
                start <= timestamp_s <= end
                for start, end in invalid_time_ranges
            )

            if not in_invalid_cluster:
                filtered_map.append((timestamp_s, delay))
            else:
                skipped_count += 1

        self.log(f"  [Filtered Stepping] Filtered {skipped_count} coarse scan points from invalid clusters")
        self.log(f"  [Filtered Stepping] Retained {len(filtered_map)} coarse scan points from valid clusters")

        # Apply fallback strategy if needed
        if fallback_mode == 'nearest' and skipped_count > 0:
            self.log(f"  [Filtered Stepping] Note: Boundaries will only be detected between valid clusters")
        elif fallback_mode == 'skip':
            self.log(f"  [Filtered Stepping] Skipped regions will maintain original timing (no correction)")

        return filtered_map

    def _qa_check(self, corrected_path: str, ref_file_path: str, base_delay: int, diagnosis_details: Optional[Dict] = None) -> bool:
        self.log("  [SteppingCorrector] Performing rigorous QA check on corrected audio map...")

        # Check if we're using skip mode with filtered clusters
        skip_mode_active = False
        if diagnosis_details:
            correction_mode = diagnosis_details.get('correction_mode', 'full')
            fallback_mode = diagnosis_details.get('fallback_mode', 'nearest')
            invalid_clusters = diagnosis_details.get('invalid_clusters', {})

            if correction_mode == 'filtered' and fallback_mode == 'skip' and invalid_clusters:
                skip_mode_active = True
                self.log(f"  [QA] Note: 'skip' fallback mode is active with {len(invalid_clusters)} filtered cluster(s).")
                self.log(f"  [QA] Filtered regions retain original timing, so delay stability check will be relaxed.")

        qa_config = self.config.copy()
        qa_threshold = self.config.get('segmented_qa_threshold', 85.0)
        qa_scan_chunks = self.config.get('segment_qa_chunk_count', 30)
        qa_min_chunks = self.config.get('segment_qa_min_accepted_chunks', 28)

        qa_config.update({
            'scan_chunk_count': qa_scan_chunks,
            'min_accepted_chunks': qa_min_chunks,
            'min_match_pct': qa_threshold,
            'scan_start_percentage': self.config.get('scan_start_percentage', 5.0),
            'scan_end_percentage': self.config.get('scan_end_percentage', 95.0)
        })
        self.log(f"  [QA] Using minimum match confidence of {qa_threshold:.1f}% within main scan window.")

        try:
            results = run_audio_correlation(
                ref_file=ref_file_path, target_file=corrected_path, config=qa_config,
                runner=self.runner, tool_paths=self.tool_paths, ref_lang=None, target_lang=None, role_tag="QA"
            )
            accepted = [r for r in results if r.get('accepted', False)]

            if len(accepted) < qa_config['min_accepted_chunks']:
                self.log(f"  [QA] FAILED: Not enough confident chunks ({len(accepted)}/{qa_config['min_accepted_chunks']}).")
                return False

            delays = [r['delay'] for r in accepted]
            median_delay = np.median(delays)

            # For skip mode, use a more lenient median check since we expect different delays
            median_tolerance = 100 if skip_mode_active else 20

            if abs(median_delay - base_delay) > median_tolerance:
                self.log(f"  [QA] FAILED: Median delay ({median_delay:.1f}ms) does not match base delay ({base_delay}ms).")
                return False

            # For skip mode, relax or skip the std dev check
            std_dev = np.std(delays)
            if skip_mode_active:
                # Very lenient std dev check for skip mode (only fail if extremely unstable)
                if std_dev > 500:
                    self.log(f"  [QA] FAILED: Delay is extremely unstable (Std Dev = {std_dev:.1f}ms).")
                    return False
                else:
                    self.log(f"  [QA] Delay std dev = {std_dev:.1f}ms (acceptable for 'skip' mode with filtered regions).")
            else:
                # Normal strict std dev check
                if std_dev > 15:
                    self.log(f"  [QA] FAILED: Delay is unstable (Std Dev = {std_dev:.1f}ms).")
                    return False

            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(self, ref_file_path: str, analysis_audio_path: str, base_delay_ms: int, diagnosis_details: Optional[Dict] = None) -> CorrectionResult:
        ref_pcm = None
        analysis_pcm = None

        try:
            ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
            analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
            if ref_index is None or analysis_index is None:
                return CorrectionResult(CorrectionVerdict.FAILED, {'error': "Could not find audio streams for analysis."})
            _, _, sample_rate = _get_audio_properties(analysis_audio_path, analysis_index, self.runner, self.tool_paths)

            analysis_codec = self._get_codec_id(analysis_audio_path)

            ref_pcm = self._decode_to_memory(ref_file_path, ref_index, sample_rate)
            analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index, sample_rate)
            if ref_pcm is None or analysis_pcm is None:
                return CorrectionResult(CorrectionVerdict.FAILED, {'error': "Failed to decode one or more audio tracks."})

            coarse_map = self._perform_coarse_scan(ref_pcm, analysis_pcm, sample_rate)
            if not coarse_map:
                return CorrectionResult(CorrectionVerdict.FAILED, {'error': "Coarse scan did not find any reliable sync points."})

            # Apply cluster filtering if diagnosis details are provided
            if diagnosis_details:
                coarse_map = self._filter_coarse_map_by_clusters(coarse_map, diagnosis_details, sample_rate)
                if not coarse_map:
                    return CorrectionResult(CorrectionVerdict.FAILED, {'error': "After filtering invalid clusters, no reliable sync points remain."})

            edl: List[AudioSegment] = []
            anchor_delay = coarse_map[0][1]
            edl.append(AudioSegment(start_s=0.0, end_s=0.0, delay_ms=anchor_delay))

            triage_std_dev_ms = self.config.get('segment_triage_std_dev_ms', 50)

            for i in range(len(coarse_map) - 1):
                zone_start_s, delay_before = coarse_map[i]
                zone_end_s, delay_after = coarse_map[i+1]
                if abs(delay_before - delay_after) < triage_std_dev_ms:
                    continue

                boundary_s_ref = self._find_boundary_in_zone(ref_pcm, analysis_pcm, sample_rate, zone_start_s, zone_end_s, delay_before, delay_after)
                boundary_s_target = boundary_s_ref + (delay_before / 1000.0)
                edl.append(AudioSegment(start_s=boundary_s_target, end_s=boundary_s_target, delay_ms=delay_after))

            edl = sorted(list(set(edl)), key=lambda x: x.start_s)

            if len(edl) <= 1:
                refined_delay = edl[0].delay_ms if edl else base_delay_ms
                self.log("  [SteppingCorrector] No stepping detected. Audio delay is uniform throughout.")
                self.log(f"  [SteppingCorrector] Refined delay measurement: {refined_delay}ms")
                if abs(refined_delay - base_delay_ms) > 5:
                    self.log(f"  [SteppingCorrector] Refined delay differs from initial estimate by {abs(refined_delay - base_delay_ms)}ms")
                    self.log(f"  [SteppingCorrector] Recommending use of refined value: {refined_delay}ms")
                return CorrectionResult(CorrectionVerdict.UNIFORM, {'delay': refined_delay})

            edl = self._analyze_internal_drift(edl, ref_pcm, analysis_pcm, sample_rate, analysis_codec)

            self.log("  [SteppingCorrector] Final Edit Decision List (EDL) for assembly created:")
            for i, seg in enumerate(edl):
                self.log(f"    - Action {i+1}: At target time {seg.start_s:.3f}s, new total delay is {seg.delay_ms}ms, internal drift is {seg.drift_rate_ms_s:+.2f} ms/s")

            # --- QA Check ---
            self.log("  [SteppingCorrector] Assembling temporary QA track...")
            qa_track_path = Path(analysis_audio_path).parent / "qa_track.flac"
            if not self._assemble_from_segments_via_ffmpeg(analysis_pcm, edl, 1, 'mono', sample_rate, qa_track_path, log_prefix="QA", ref_pcm=ref_pcm):
                return CorrectionResult(CorrectionVerdict.FAILED, {'error': "Failed during QA track assembly."})

            if not self._qa_check(str(qa_track_path), ref_file_path, edl[0].delay_ms, diagnosis_details):
                return CorrectionResult(CorrectionVerdict.FAILED, {'error': "Corrected track failed QA check."})

            # If QA passes, the EDL is good. Return it.
            return CorrectionResult(CorrectionVerdict.STEPPED, {'edl': edl})

        except Exception as e:
            self.log(f"[FATAL] SteppingCorrector failed with exception: {e}")
            import traceback
            self.log(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return CorrectionResult(CorrectionVerdict.FAILED, {'error': str(e)})
        finally:
            if ref_pcm is not None: del ref_pcm
            if analysis_pcm is not None: del analysis_pcm
            gc.collect()

    def apply_plan_to_file(self, target_audio_path: str, edl: List[AudioSegment], temp_dir: Path, ref_file_path: Optional[str] = None) -> Optional[Path]:
        """Applies a pre-generated EDL to a given audio file."""
        target_pcm = None
        ref_pcm = None
        try:
            target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
            if target_index is None:
                self.log(f"[ERROR] Could not find audio stream in {target_audio_path}")
                return None

            target_channels, target_layout, sample_rate = _get_audio_properties(target_audio_path, target_index, self.runner, self.tool_paths)

            # Decode reference audio for Smart Fill if provided
            if ref_file_path:
                self.log(f"  [SteppingCorrector] Decoding reference audio for Smart Fill capability...")
                ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
                if ref_index is not None:
                    ref_pcm = self._decode_to_memory(ref_file_path, ref_index, sample_rate)
                    if ref_pcm is None:
                        self.log(f"  [WARNING] Failed to decode reference audio, Smart Fill will be disabled")

            self.log(f"  [SteppingCorrector] Applying correction plan to '{Path(target_audio_path).name}'...")
            self.log(f"    - Decoding final target audio track ({target_layout})...")
            target_pcm = self._decode_to_memory(target_audio_path, target_index, sample_rate, target_channels)
            if target_pcm is None:
                return None

            corrected_path = temp_dir / f"corrected_{Path(target_audio_path).stem}.flac"

            if not self._assemble_from_segments_via_ffmpeg(target_pcm, edl, target_channels, target_layout, sample_rate, corrected_path, log_prefix="Final", ref_pcm=ref_pcm):
                return None

            self.log(f"[SUCCESS] Stepping correction applied successfully for '{Path(target_audio_path).name}'")
            return corrected_path

        except Exception as e:
            self.log(f"[FATAL] Assembly failed for {target_audio_path}: {e}")
            return None
        finally:
            if target_pcm is not None:
                del target_pcm
            if ref_pcm is not None:
                del ref_pcm
            gc.collect()

def run_stepping_correction(ctx: Context, runner: CommandRunner) -> Context:
    extracted_audio_map = {
        f"{item.track.source}_{item.track.id}": item
        for item in ctx.extracted_items if item.track.type == TrackType.AUDIO
    }

    corrector = SteppingCorrector(runner, ctx.tool_paths, ctx.settings_dict)
    ref_file_path = ctx.sources.get("Source 1")

    for analysis_track_key, flag_info in ctx.segment_flags.items():
        source_key = analysis_track_key.split('_')[0]
        base_delay_ms = flag_info['base_delay']

        target_items = [
            item for item in ctx.extracted_items
            if item.track.source == source_key and item.track.type == TrackType.AUDIO and not item.is_preserved
        ]

        if not target_items:
            runner._log_message(f"[SteppingCorrection] Skipping {source_key}: No audio tracks found in layout to correct.")
            continue

        analysis_item = extracted_audio_map.get(analysis_track_key)
        if not analysis_item:
            runner._log_message(f"[SteppingCorrection] Analysis track {analysis_track_key} not in layout. Extracting internally...")
            source_container_path = ctx.sources.get(source_key)
            track_id = int(analysis_track_key.split('_')[1])
            try:
                internal_extract = extract_tracks(
                    source_container_path, ctx.temp_dir, runner, ctx.tool_paths,
                    role=f"{source_key}_internal", specific_tracks=[track_id]
                )
                if not internal_extract: raise RuntimeError("Internal extraction failed.")
                analysis_track_path = internal_extract[0]['path']
            except Exception as e:
                runner._log_message(f"[ERROR] Failed to internally extract analysis track {analysis_track_key}: {e}")
                continue
        else:
            analysis_track_path = str(analysis_item.extracted_path)

        # Run analysis once to get the correction plan (EDL)
        # Pass diagnosis details for filtered stepping support
        diagnosis_details = {
            'valid_clusters': flag_info.get('valid_clusters', {}),
            'invalid_clusters': flag_info.get('invalid_clusters', {}),
            'validation_results': flag_info.get('validation_results', {}),
            'correction_mode': flag_info.get('correction_mode', 'full'),
            'fallback_mode': flag_info.get('fallback_mode', 'nearest')
        }

        result: CorrectionResult = corrector.run(
            ref_file_path=ref_file_path,
            analysis_audio_path=analysis_track_path,
            base_delay_ms=base_delay_ms,
            diagnosis_details=diagnosis_details if flag_info.get('correction_mode') else None
        )

        if result.verdict == CorrectionVerdict.UNIFORM:
            new_delay = result.data['delay']
            runner._log_message(f"[SteppingCorrection] No stepping found. Refined uniform delay is {new_delay} ms.")
            runner._log_message(f"[SteppingCorrection] The globally-shifted delay from the main analysis will be used.")

        elif result.verdict == CorrectionVerdict.STEPPED:
            edl = result.data['edl']
            runner._log_message(f"[SteppingCorrection] Analysis successful. Applying correction plan to {len(target_items)} audio track(s) from {source_key}.")

            # Store EDL in context for subtitle adjustment
            ctx.stepping_edls[source_key] = edl

            for target_item in target_items:
                corrected_path = corrector.apply_plan_to_file(str(target_item.extracted_path), edl, ctx.temp_dir, ref_file_path=ref_file_path)

                if corrected_path:
                    # Preserve the original track
                    preserved_item = copy.deepcopy(target_item)
                    preserved_item.is_preserved = True
                    preserved_item.is_default = False
                    original_props = preserved_item.track.props
                    preserved_item.track = Track(
                        source=preserved_item.track.source, id=preserved_item.track.id, type=preserved_item.track.type,
                        props=StreamProps(
                            codec_id=original_props.codec_id,
                            lang=original_props.lang,
                            name=f"{original_props.name} (Original)" if original_props.name else "Original"
                        )
                    )

                    # Update the main track to point to corrected FLAC
                    target_item.extracted_path = corrected_path
                    target_item.is_corrected = True
                    target_item.container_delay_ms = 0  # FIXED: New FLAC has no container delay
                    target_item.track = Track(
                        source=target_item.track.source, id=target_item.track.id, type=target_item.track.type,
                        props=StreamProps(
                            codec_id="FLAC",
                            lang=original_props.lang,
                            name=f"{original_props.name} (Stepping Corrected)" if original_props.name else "Stepping Corrected"  # FIXED: Clearer name
                        )
                    )
                    target_item.apply_track_name = True
                    ctx.extracted_items.append(preserved_item)
                else:
                    runner._log_message(f"[ERROR] Failed to apply correction plan to {target_item.extracted_path.name}. Keeping original.")

        elif result.verdict == CorrectionVerdict.FAILED:
            error_message = result.data.get('error', 'Unknown error')
            raise RuntimeError(f"Stepping correction for {source_key} failed: {error_message}")

    return ctx
