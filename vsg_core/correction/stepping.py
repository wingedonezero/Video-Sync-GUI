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

class GapHandlingStrategy(Enum):
    """Strategy for handling gaps between segments."""
    TIME_STRETCH = auto()    # Stretch audio window to absorb gap
    CROSSFADE = auto()       # Crossfade between segments
    SILENCE = auto()         # Insert/remove silence (current behavior)
    FADED_SILENCE = auto()   # Silence with fade in/out

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

@dataclass
class GapClassification:
    """Classification result for a gap between segments."""
    gap_ms: float
    strategy: GapHandlingStrategy
    stretch_window_s: Optional[float] = None
    crossfade_duration_ms: Optional[float] = None
    reason: str = ""

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

    def _classify_gap(self, gap_ms: float, segment_duration_s: float) -> GapClassification:
        """
        Classify a gap and determine the best correction strategy.

        Args:
            gap_ms: Gap size in milliseconds (positive = insert, negative = remove)
            segment_duration_s: Duration of the segment preceding this gap

        Returns:
            GapClassification with recommended strategy and parameters
        """
        abs_gap = abs(gap_ms)

        # Get thresholds from config
        tiny_threshold = self.config.get('segment_gap_tiny_threshold_ms', 50)
        small_threshold = self.config.get('segment_gap_small_threshold_ms', 200)
        medium_threshold = self.config.get('segment_gap_medium_threshold_ms', 500)

        # Get mode override
        mode = self.config.get('segment_gap_handling_mode', 'auto')

        # Force mode if specified
        if mode == 'always_stretch' and abs_gap < medium_threshold:
            window_s = self.config.get('segment_stretch_window_s', 5.0)
            min_window_s = self.config.get('segment_stretch_min_window_s', 2.0)
            actual_window_s = min(window_s, max(min_window_s, segment_duration_s * 0.9))
            return GapClassification(
                gap_ms=gap_ms,
                strategy=GapHandlingStrategy.TIME_STRETCH,
                stretch_window_s=actual_window_s,
                reason=f"Force mode: always_stretch"
            )
        elif mode == 'always_silence':
            return GapClassification(
                gap_ms=gap_ms,
                strategy=GapHandlingStrategy.SILENCE,
                reason=f"Force mode: always_silence"
            )

        # Auto mode - classify by gap size
        if abs_gap < tiny_threshold:
            # Tiny gaps: Time-stretch (frame-level corrections)
            window_s = self.config.get('segment_stretch_window_s', 5.0)
            min_window_s = self.config.get('segment_stretch_min_window_s', 2.0)

            # Don't make window larger than 90% of segment duration
            actual_window_s = min(window_s, max(min_window_s, segment_duration_s * 0.9))

            if actual_window_s < min_window_s:
                # Segment too short for time-stretching, fall back to silence
                return GapClassification(
                    gap_ms=gap_ms,
                    strategy=GapHandlingStrategy.SILENCE,
                    reason=f"Segment too short ({segment_duration_s:.1f}s) for time-stretch"
                )

            return GapClassification(
                gap_ms=gap_ms,
                strategy=GapHandlingStrategy.TIME_STRETCH,
                stretch_window_s=actual_window_s,
                reason=f"Tiny gap ({abs_gap:.1f}ms) - frame-level correction"
            )

        elif abs_gap < small_threshold:
            # Small gaps: Crossfade option
            crossfade_ms = self.config.get('segment_crossfade_duration_ms', 20)
            return GapClassification(
                gap_ms=gap_ms,
                strategy=GapHandlingStrategy.CROSSFADE,
                crossfade_duration_ms=crossfade_ms,
                reason=f"Small gap ({abs_gap:.1f}ms) - crossfade recommended"
            )

        elif abs_gap < medium_threshold:
            # Medium gaps: Faded silence
            return GapClassification(
                gap_ms=gap_ms,
                strategy=GapHandlingStrategy.FADED_SILENCE,
                reason=f"Medium gap ({abs_gap:.1f}ms) - faded silence"
            )

        else:
            # Large gaps: Pure silence (current behavior)
            return GapClassification(
                gap_ms=gap_ms,
                strategy=GapHandlingStrategy.SILENCE,
                reason=f"Large gap ({abs_gap:.1f}ms) - pure silence/removal"
            )

    def _apply_stretch_correction(
        self,
        pcm_data: np.ndarray,
        segment_start_s: float,
        segment_end_s: float,
        gap_ms: float,
        stretch_window_s: float,
        sample_rate: int,
        channels: int,
        channel_layout: str,
        assembly_dir: Path,
        segment_index: int
    ) -> Optional[Path]:
        """
        Apply time-stretch correction to absorb a gap.

        Args:
            pcm_data: Full PCM audio data
            segment_start_s: Start time of the segment
            segment_end_s: End time of the segment
            gap_ms: Gap to absorb (positive = needs stretching, negative = needs compression)
            stretch_window_s: Window size to stretch (from end of segment backwards)
            sample_rate: Audio sample rate
            channels: Number of audio channels
            channel_layout: Channel layout string
            assembly_dir: Directory for temporary files
            segment_index: Index for file naming

        Returns:
            Path to the stretched segment file, or None on failure
        """
        # Calculate the actual window to stretch (from the end of segment backwards)
        window_end_s = segment_end_s
        window_start_s = max(segment_start_s, segment_end_s - stretch_window_s)
        actual_window_s = window_end_s - window_start_s

        if actual_window_s < 0.1:
            self.log(f"    [WARN] Window too small ({actual_window_s:.2f}s), skipping stretch")
            return None

        # Calculate stretch ratio
        # Positive gap means we need to slow down (stretch) to create more time
        original_duration_ms = actual_window_s * 1000.0
        target_duration_ms = original_duration_ms + gap_ms
        tempo_ratio = target_duration_ms / original_duration_ms

        # Sanity check - don't stretch more than 10%
        if abs(tempo_ratio - 1.0) > 0.10:
            self.log(f"    [WARN] Stretch ratio too extreme ({tempo_ratio:.4f}), falling back to silence")
            return None

        self.log(f"    - Time-stretching {actual_window_s:.2f}s window by {tempo_ratio:.4f}x to absorb {gap_ms:+.1f}ms gap")

        # Extract the window to stretch
        window_start_sample = int(window_start_s * sample_rate) * channels
        window_end_sample = int(window_end_s * sample_rate) * channels

        if window_end_sample > len(pcm_data):
            window_end_sample = len(pcm_data)

        window_pcm = pcm_data[window_start_sample:window_end_sample]

        if window_pcm.size == 0:
            self.log(f"    [WARN] Empty window, skipping stretch")
            return None

        # Encode window to temp file
        window_file = assembly_dir / f"stretch_window_{segment_index:03d}.flac"
        encode_cmd = [
            'ffmpeg', '-y', '-v', 'error', '-nostdin',
            '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels),
            '-channel_layout', channel_layout, '-i', '-',
            '-map_metadata', '-1',
            '-map_metadata:s:a', '-1',
            '-fflags', '+bitexact',
            '-c:a', 'flac',
            str(window_file)
        ]

        if self.runner.run(encode_cmd, self.tool_paths, is_binary=True, input_data=window_pcm.tobytes()) is None:
            self.log(f"    [ERROR] Failed to encode stretch window")
            return None

        # Apply time-stretch using configured engine
        stretched_file = assembly_dir / f"stretch_window_{segment_index:03d}_stretched.flac"
        resample_engine = self.config.get('segment_resample_engine', 'rubberband')

        filter_chain = ''
        if resample_engine == 'rubberband':
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
            filter_chain = f'atempo={tempo_ratio}'

        else:  # Default to aresample
            new_sample_rate = sample_rate * tempo_ratio
            filter_chain = f'asetrate={new_sample_rate},aresample={sample_rate}'

        resample_cmd = [
            'ffmpeg', '-y', '-nostdin', '-v', 'error',
            '-i', str(window_file),
            '-af', filter_chain,
            '-map_metadata', '-1',
            '-map_metadata:s:a', '-1',
            '-fflags', '+bitexact',
            str(stretched_file)
        ]

        if self.runner.run(resample_cmd, self.tool_paths) is None:
            error_msg = f"Time-stretching with '{resample_engine}' failed"
            if resample_engine == 'rubberband':
                error_msg += " (Ensure your FFmpeg build includes 'librubberband')"
            self.log(f"    [ERROR] {error_msg}")
            return None

        # If the window doesn't cover the entire segment, we need to combine unstretched + stretched parts
        if window_start_s > segment_start_s:
            # Extract unstretched beginning
            unstretched_start_sample = int(segment_start_s * sample_rate) * channels
            unstretched_end_sample = int(window_start_s * sample_rate) * channels
            unstretched_pcm = pcm_data[unstretched_start_sample:unstretched_end_sample]

            if unstretched_pcm.size > 0:
                # Encode unstretched part
                unstretched_file = assembly_dir / f"stretch_unstretched_{segment_index:03d}.flac"
                encode_cmd = [
                    'ffmpeg', '-y', '-v', 'error', '-nostdin',
                    '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels),
                    '-channel_layout', channel_layout, '-i', '-',
                    '-map_metadata', '-1',
                    '-map_metadata:s:a', '-1',
                    '-fflags', '+bitexact',
                    '-c:a', 'flac',
                    str(unstretched_file)
                ]
                if self.runner.run(encode_cmd, self.tool_paths, is_binary=True, input_data=unstretched_pcm.tobytes()) is None:
                    self.log(f"    [ERROR] Failed to encode unstretched part")
                    return None

                # Concatenate unstretched + stretched
                combined_file = assembly_dir / f"stretch_combined_{segment_index:03d}.flac"
                concat_list = assembly_dir / f"stretch_concat_{segment_index:03d}.txt"
                concat_list.write_text(
                    f"file '{unstretched_file.name}'\nfile '{stretched_file.name}'",
                    encoding='utf-8'
                )

                concat_cmd = [
                    'ffmpeg', '-y', '-v', 'error',
                    '-f', 'concat', '-safe', '0', '-i', str(concat_list),
                    '-map_metadata', '-1',
                    '-map_metadata:s:a', '-1',
                    '-fflags', '+bitexact',
                    '-c:a', 'flac',
                    str(combined_file)
                ]
                if self.runner.run(concat_cmd, self.tool_paths) is None:
                    self.log(f"    [ERROR] Failed to concatenate stretched parts")
                    return None

                return combined_file

        # Window covers entire segment, just return stretched version
        return stretched_file

    def _get_codec_id(self, file_path: str) -> str:
        """Uses ffprobe to get the codec name for a given audio file."""
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)]
        out = self.runner.run(cmd, self.tool_paths)
        return (out or '').strip().lower()

    def _decode_to_memory(self, file_path: str, stream_index: int, sample_rate: int, channels: int = 1) -> Optional[np.ndarray]:
        cmd = [ 'ffmpeg', '-nostdin', '-v', 'error', '-i', str(file_path), '-map', f'0:a:{stream_index}', '-ac', str(channels), '-ar', str(sample_rate), '-f', 's32le', '-' ]
        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes: return np.frombuffer(pcm_bytes, dtype=np.int32)
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
        start_pct = self.config.get('scan_start_percentage', 5.0)
        end_pct = self.config.get('scan_end_percentage', 95.0)
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

    def _assemble_from_segments_via_ffmpeg(self, pcm_data: np.ndarray, edl: List[AudioSegment], channels: int, channel_layout: str, sample_rate: int, out_path: Path, log_prefix: str) -> bool:
        self.log(f"  [{log_prefix}] Assembling audio from {len(edl)} segment(s) via FFmpeg...")

        assembly_dir = out_path.parent / f"assembly_{out_path.stem}"
        assembly_dir.mkdir(exist_ok=True)

        concat_list_path = assembly_dir / "concat_list.txt"
        segment_files = []
        base_delay_ms = edl[0].delay_ms
        current_base_delay = base_delay_ms

        try:
            pcm_duration_s = len(pcm_data) / float(sample_rate * channels)

            # Track segments that need time-stretch correction (processed before gap)
            segments_to_stretch = {}

            # First pass: classify all gaps and identify segments that need stretching
            for i, segment in enumerate(edl):
                gap_ms = segment.delay_ms - current_base_delay

                if abs(gap_ms) > 10:
                    # Calculate segment duration for classification
                    segment_start_s_on_timeline = segment.start_s
                    segment_end_s_on_timeline = edl[i+1].start_s if i + 1 < len(edl) else pcm_duration_s
                    segment_duration_s = segment_end_s_on_timeline - segment_start_s_on_timeline

                    # Classify this gap
                    classification = self._classify_gap(gap_ms, segment_duration_s)

                    self.log(f"    - Gap at {segment.start_s:.3f}s: {gap_ms:+.1f}ms → Strategy: {classification.strategy.name}")
                    self.log(f"      Reason: {classification.reason}")

                    # If time-stretch strategy, mark the PREVIOUS segment for stretching
                    if classification.strategy == GapHandlingStrategy.TIME_STRETCH and i > 0:
                        # Store stretch info for the previous segment
                        segments_to_stretch[i-1] = classification

                current_base_delay = segment.delay_ms

            # Reset for second pass
            current_base_delay = base_delay_ms

            # Second pass: process segments with smart gap handling
            for i, segment in enumerate(edl):
                gap_ms = segment.delay_ms - current_base_delay
                needs_stretch = i in segments_to_stretch

                # Handle gap insertion/removal based on strategy
                if abs(gap_ms) > 10:
                    segment_start_s_on_timeline = segment.start_s
                    segment_end_s_on_timeline = edl[i+1].start_s if i + 1 < len(edl) else pcm_duration_s
                    segment_duration_s = segment_end_s_on_timeline - segment_start_s_on_timeline

                    classification = self._classify_gap(gap_ms, segment_duration_s)

                    if classification.strategy == GapHandlingStrategy.TIME_STRETCH:
                        # Time-stretch will be handled when processing the segment
                        # The gap will be absorbed into the stretched segment, so no silence needed
                        pass

                    elif classification.strategy == GapHandlingStrategy.SILENCE:
                        # Original behavior: pure silence insertion/removal
                        if gap_ms > 0:
                            self.log(f"    - At {segment.start_s:.3f}s: Inserting {gap_ms}ms of pure silence.")
                            silence_duration_s = gap_ms / 1000.0
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
                            self.log(f"    - At {segment.start_s:.3f}s: Removing {-gap_ms}ms of audio.")

                    elif classification.strategy in [GapHandlingStrategy.CROSSFADE, GapHandlingStrategy.FADED_SILENCE]:
                        # TODO: Implement crossfade and faded silence
                        # For now, fall back to regular silence
                        self.log(f"    - {classification.strategy.name} not yet implemented, using SILENCE")
                        if gap_ms > 0:
                            silence_duration_s = gap_ms / 1000.0
                            silence_file = assembly_dir / f"silence_{i:03d}.flac"
                            silence_samples = int(silence_duration_s * sample_rate) * channels
                            silence_pcm = np.zeros(silence_samples, dtype=np.int32)
                            encode_cmd = [
                                'ffmpeg', '-y', '-v', 'error', '-nostdin',
                                '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels),
                                '-channel_layout', channel_layout, '-i', '-',
                                '-map_metadata', '-1', '-map_metadata:s:a', '-1',
                                '-fflags', '+bitexact', '-c:a', 'flac',
                                str(silence_file)
                            ]
                            if self.runner.run(encode_cmd, self.tool_paths, is_binary=True, input_data=silence_pcm.tobytes()) is not None:
                                segment_files.append(f"file '{silence_file.name}'")
                        else:
                            self.log(f"    - At {segment.start_s:.3f}s: Removing {-gap_ms}ms of audio.")

                current_base_delay = segment.delay_ms

                segment_start_s_on_target_timeline = segment.start_s
                segment_end_s_on_target_timeline = edl[i+1].start_s if i + 1 < len(edl) else pcm_duration_s

                # Only adjust start time if we're removing audio (and NOT using time-stretch)
                if gap_ms < 0 and not needs_stretch:
                    segment_start_s_on_target_timeline += abs(gap_ms) / 1000.0

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

                # Apply time-stretch correction if needed (to absorb gap after this segment)
                if needs_stretch:
                    classification = segments_to_stretch[i]
                    next_gap_ms = edl[i+1].delay_ms - segment.delay_ms  # Gap after this segment

                    stretched_file = self._apply_stretch_correction(
                        pcm_data=pcm_data,
                        segment_start_s=segment_start_s_on_target_timeline,
                        segment_end_s=segment_end_s_on_target_timeline,
                        gap_ms=next_gap_ms,
                        stretch_window_s=classification.stretch_window_s,
                        sample_rate=sample_rate,
                        channels=channels,
                        channel_layout=channel_layout,
                        assembly_dir=assembly_dir,
                        segment_index=i
                    )

                    if stretched_file is not None:
                        # Replace segment file with stretched version
                        segment_file = stretched_file
                    else:
                        # Stretch failed, will fall back to silence insertion on next iteration
                        self.log(f"    [WARN] Time-stretch failed for segment {i}, gap will use fallback method")

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

    def _qa_check(self, corrected_path: str, ref_file_path: str, base_delay: int) -> bool:
        self.log("  [SteppingCorrector] Performing rigorous QA check on corrected audio map...")
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
            if abs(median_delay - base_delay) > 20:
                self.log(f"  [QA] FAILED: Median delay ({median_delay:.1f}ms) does not match base delay ({base_delay}ms).")
                return False
            if np.std(delays) > 15:
                self.log(f"  [QA] FAILED: Delay is unstable (Std Dev = {np.std(delays):.1f}ms).")
                return False
            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(self, ref_file_path: str, analysis_audio_path: str, base_delay_ms: int) -> CorrectionResult:
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
            if not self._assemble_from_segments_via_ffmpeg(analysis_pcm, edl, 1, 'mono', sample_rate, qa_track_path, log_prefix="QA"):
                return CorrectionResult(CorrectionVerdict.FAILED, {'error': "Failed during QA track assembly."})

            if not self._qa_check(str(qa_track_path), ref_file_path, edl[0].delay_ms):
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

    def apply_plan_to_file(self, target_audio_path: str, edl: List[AudioSegment], temp_dir: Path) -> Optional[Path]:
        """Applies a pre-generated EDL to a given audio file."""
        target_pcm = None
        try:
            target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
            if target_index is None:
                self.log(f"[ERROR] Could not find audio stream in {target_audio_path}")
                return None

            target_channels, target_layout, sample_rate = _get_audio_properties(target_audio_path, target_index, self.runner, self.tool_paths)

            self.log(f"  [SteppingCorrector] Applying correction plan to '{Path(target_audio_path).name}'...")
            self.log(f"    - Decoding final target audio track ({target_layout})...")
            target_pcm = self._decode_to_memory(target_audio_path, target_index, sample_rate, target_channels)
            if target_pcm is None:
                return None

            corrected_path = temp_dir / f"corrected_{Path(target_audio_path).stem}.flac"

            if not self._assemble_from_segments_via_ffmpeg(target_pcm, edl, target_channels, target_layout, sample_rate, corrected_path, log_prefix="Final"):
                return None

            self.log(f"[SUCCESS] Stepping correction applied successfully for '{Path(target_audio_path).name}'")
            return corrected_path

        except Exception as e:
            self.log(f"[FATAL] Assembly failed for {target_audio_path}: {e}")
            return None
        finally:
            if target_pcm is not None:
                del target_pcm
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
        result: CorrectionResult = corrector.run(
            ref_file_path=ref_file_path,
            analysis_audio_path=analysis_track_path,
            base_delay_ms=base_delay_ms
        )

        if result.verdict == CorrectionVerdict.UNIFORM:
            new_delay = result.data['delay']
            runner._log_message(f"[SteppingCorrection] No stepping found. Refined uniform delay is {new_delay} ms.")
            runner._log_message(f"[SteppingCorrection] The globally-shifted delay from the main analysis will be used.")

        elif result.verdict == CorrectionVerdict.STEPPED:
            edl = result.data['edl']
            runner._log_message(f"[SteppingCorrection] Analysis successful. Applying correction plan to {len(target_items)} audio track(s) from {source_key}.")

            for target_item in target_items:
                corrected_path = corrector.apply_plan_to_file(str(target_item.extracted_path), edl, ctx.temp_dir)

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
