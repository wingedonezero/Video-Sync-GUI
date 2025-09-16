# vsg_core/analysis/segment_correction.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum, auto

import numpy as np
import ruptures as rpt
from scipy.signal import correlate
from collections import Counter

from ..io.runner import CommandRunner
from ..analysis.audio_corr import get_audio_stream_info, run_audio_correlation
from .segmentation import BoundaryDetector, AudioFingerprinter, SegmentMatcher, matching

class CorrectionVerdict(Enum):
    """Defines the outcome of the audio correction triage."""
    UNIFORM = auto()
    STEPPED = auto()
    COMPLEX = auto()
    FAILED = auto()

@dataclass
class CorrectionResult:
    """Holds the result of the AudioCorrector's analysis."""
    verdict: CorrectionVerdict
    data: Any = None # Can be the median delay, a file path, or an error message

@dataclass
class AudioSegment:
    """Represents a continuous segment of audio with a stable delay."""
    start_s: float
    end_s: float
    delay_ms: int

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

def detect_stepping(chunks: List[Dict[str, Any]], config: dict) -> bool:
    if len(chunks) < 2: return False
    accepted_delays = [c['delay'] for c in chunks if c.get('accepted', False)]
    if len(accepted_delays) < 2: return False
    drift = max(accepted_delays) - min(accepted_delays)
    return drift > 250

class AudioCorrector:
    def __init__(self, runner: CommandRunner, tool_paths: dict, config: dict):
        self.runner = runner
        self.tool_paths = tool_paths
        self.config = config
        self.log = runner._log_message
        self.boundary_detector: Optional[BoundaryDetector] = None
        self.fingerprinter: Optional[AudioFingerprinter] = None
        self.matcher: Optional[SegmentMatcher] = None

    def _init_segmentation_modules(self, sample_rate: int):
        if self.boundary_detector is None:
            self.boundary_detector = BoundaryDetector(sample_rate, self.log)
            self.fingerprinter = AudioFingerprinter(sample_rate, self.log)
            self.matcher = SegmentMatcher(self.fingerprinter, self.log)

    def _decode_to_memory(self, file_path: str, stream_index: int, sample_rate: int, channels: int, force_mono: bool = False) -> Optional[np.ndarray]:
        cmd = [ 'ffmpeg', '-nostdin', '-v', 'error', '-i', str(file_path), '-map', f'0:a:{stream_index}' ]
        if force_mono: cmd.extend(['-ac', '1'])
        else: cmd.extend(['-ac', str(channels)])
        cmd.extend(['-ar', str(sample_rate), '-f', 's32le', '-'])
        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes: return np.frombuffer(pcm_bytes, dtype=np.int32)
        self.log(f"[ERROR] Corrector failed to decode audio stream {stream_index} from '{Path(file_path).name}'")
        return None

    def _build_precise_edl(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, delay_signal: np.ndarray, sample_rate: int, base_delay_ms: int, step_samples: int) -> Optional[List[AudioSegment]]:
        num_chunks = len(delay_signal)
        if num_chunks == 0:
            self.log("[ERROR] No chunks to process in EDL building")
            return None

        self.log(f"  [Corrector] Finding approximate change points from {num_chunks} chunks...")
        algo = rpt.Binseg(model="l1").fit(delay_signal)
        penalty = np.log(num_chunks) * np.std(delay_signal)**2 * 0.1
        approx_change_indices = algo.predict(pen=penalty)

        self.log("  [Corrector] Refining change points to be sample-accurate...")
        refined_change_indices = [0]
        for approx_idx in approx_change_indices:
            if approx_idx == 0 or approx_idx >= num_chunks: continue
            refined_idx = self._refine_change_point(ref_pcm, analysis_pcm, approx_idx, step_samples, sample_rate)
            refined_change_indices.append(refined_idx)

        refined_change_indices.append(len(ref_pcm))

        boundary_indices = sorted(list(set(refined_change_indices)))
        segments = []

        for i in range(len(boundary_indices) - 1):
            start_idx, end_idx = boundary_indices[i], boundary_indices[i+1]
            if start_idx >= end_idx: continue

            coarse_start_chunk = start_idx // step_samples
            coarse_end_chunk = min(end_idx // step_samples, len(delay_signal))

            if coarse_start_chunk >= len(delay_signal):
                coarse_start_chunk = len(delay_signal) - 1

            segment_delays = delay_signal[coarse_start_chunk:coarse_end_chunk]

            if len(segment_delays) == 0:
                if coarse_start_chunk > 0:
                    stable_delay = int(delay_signal[coarse_start_chunk - 1])
                else:
                    stable_delay = base_delay_ms
            else:
                stable_delay = int(Counter(segment_delays).most_common(1)[0][0])

            segments.append(AudioSegment(start_s=(start_idx / sample_rate), end_s=(end_idx / sample_rate), delay_ms=stable_delay))

        if segments:
            segments[0].delay_ms = base_delay_ms
            self.log(f"  [Corrector] Detailed mapping found {len(segments)} segments.")
            for i, seg in enumerate(segments):
                self.log(f"    - Segment {i+1}: {seg.start_s:.4f}s - {seg.end_s:.4f}s @ {seg.delay_ms}ms")
            return segments
        return None

    def _refine_change_point(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, approx_chunk_idx: int, step_samples: int, sample_rate: int) -> int:
        approx_sample_idx = approx_chunk_idx * step_samples
        search_radius = int((500 / 1000) * sample_rate)
        start_scan = max(0, approx_sample_idx - search_radius)
        end_scan = min(len(ref_pcm), approx_sample_idx + search_radius)
        corr_radius = int((20 / 1000) * sample_rate)

        # Ensure we have enough samples for correlation
        if start_scan < corr_radius or end_scan > len(ref_pcm) - corr_radius:
            return approx_sample_idx

        pre_chunk = analysis_pcm[start_scan - corr_radius : start_scan]
        ref_chunk = ref_pcm[start_scan - corr_radius : start_scan]

        if len(pre_chunk) == 0 or len(ref_chunk) == 0:
            return approx_sample_idx

        r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
        t = (pre_chunk - np.mean(pre_chunk)) / (np.std(pre_chunk) + 1e-9)
        c = correlate(r, t, 'full', 'fft')
        baseline_lag = np.argmax(np.abs(c)) - (len(t) - 1)

        for i in range(start_scan, end_scan - corr_radius):
            post_chunk = analysis_pcm[i : i + corr_radius]
            ref_chunk = ref_pcm[i : i + corr_radius]

            if len(post_chunk) == 0 or len(ref_chunk) == 0:
                continue

            r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
            t = (post_chunk - np.mean(post_chunk)) / (np.std(post_chunk) + 1e-9)
            c = correlate(r, t, 'full', 'fft')
            current_lag = np.argmax(np.abs(c)) - (len(t) - 1)

            if abs(current_lag - baseline_lag) > 5:
                self.log(f"    - Refined point from ~{(approx_sample_idx/sample_rate):.3f}s to {(i/sample_rate):.3f}s")
                return i

        self.log(f"    - Warning: Could not refine point at ~{(approx_sample_idx/sample_rate):.3f}s. Using original estimate.")
        return approx_sample_idx

    def _assemble_from_pcm_in_memory(self, pcm_data: np.ndarray, edl: List[AudioSegment], channels: int, sample_rate: int) -> np.ndarray:
        base_delay = edl[0].delay_ms
        total_silence_ms = sum(max(0, seg.delay_ms - base_delay) for seg in edl)
        total_silence_samples = int(total_silence_ms / 1000 * sample_rate) * channels
        final_sample_count = pcm_data.shape[0] + total_silence_samples
        new_pcm = np.zeros(final_sample_count, dtype=np.int32)
        current_pos_in_new = 0
        last_pos_in_old = 0

        for segment in edl:
            start_sample = int(segment.start_s * sample_rate) * channels
            end_sample = int(segment.end_s * sample_rate) * channels

            if start_sample > last_pos_in_old:
                gap_chunk = pcm_data[last_pos_in_old:start_sample]
                new_pcm[current_pos_in_new : current_pos_in_new + len(gap_chunk)] = gap_chunk
                current_pos_in_new += len(gap_chunk)

            silence_to_add_ms = segment.delay_ms - base_delay
            if silence_to_add_ms > 10:
                silence_samples = int(silence_to_add_ms / 1000 * sample_rate) * channels
                current_pos_in_new += silence_samples

            segment_chunk = pcm_data[start_sample:end_sample]
            new_pcm[current_pos_in_new : current_pos_in_new + len(segment_chunk)] = segment_chunk
            current_pos_in_new += len(segment_chunk)
            last_pos_in_old = end_sample

        if last_pos_in_old < len(pcm_data):
            final_chunk = pcm_data[last_pos_in_old:]
            new_pcm[current_pos_in_new : current_pos_in_new + len(final_chunk)] = final_chunk
        return new_pcm

    def _encode_pcm_to_file(self, pcm_data: np.ndarray, out_path: Path, channels: int, channel_layout: str, sample_rate: int) -> bool:
        cmd = [ 'ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels), '-channel_layout', channel_layout, '-i', '-', '-c:a', 'flac', str(out_path) ]
        return self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=pcm_data.tobytes()) is not None

    def _qa_check(self, corrected_path: str, ref_file_path: str, base_delay: int) -> bool:
        self.log("  [Corrector] Performing rigorous QA check on corrected audio map...")
        qa_config = self.config.copy()
        qa_config.update({'scan_chunk_count': 30, 'min_accepted_chunks': 28, 'min_match_pct': 70.0})
        try:
            results = run_audio_correlation(ref_file=ref_file_path, target_file=corrected_path, config=qa_config, runner=self.runner, tool_paths=self.tool_paths, ref_lang=None, target_lang=None, role_tag="QA")
            accepted = [r for r in results if r.get('accepted', False)]
            if len(accepted) < qa_config['min_accepted_chunks']:
                self.log(f"  [QA] FAILED: Not enough confident chunks ({len(accepted)}/{qa_config['min_accepted_chunks']}).")
                return False
            delays = [r['delay'] for r in accepted]
            median_delay = np.median(delays)
            if abs(median_delay - base_delay) > 20:
                self.log(f"  [QA] FAILED: Median delay ({median_delay:.1f}ms) does not match base delay ({base_delay}ms).")
                return False
            if np.std(delays) > 10:
                self.log(f"  [QA] FAILED: Delay is unstable (Std Dev = {np.std(delays):.1f}ms).")
                return False
            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(self, ref_file_path: str, analysis_audio_path: str, target_audio_path: str, base_delay_ms: int, temp_dir: Path) -> CorrectionResult:
        """Main entry point. Performs triage to decide on the correction strategy."""
        self.log(f"  [Corrector] Starting correction for '{Path(target_audio_path).name}'...")
        try:
            ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
            analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
            if ref_index is None or analysis_index is None:
                return CorrectionResult(CorrectionVerdict.FAILED, "Could not find audio streams for analysis.")
            _, _, sample_rate = _get_audio_properties(analysis_audio_path, analysis_index, self.runner, self.tool_paths)

            self.log("  [Corrector] Decoding analysis tracks for high-resolution scan...")
            ref_pcm = self._decode_to_memory(ref_file_path, ref_index, sample_rate, 1, force_mono=True)
            analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index, sample_rate, 1, force_mono=True)

            if ref_pcm is None or analysis_pcm is None:
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed to decode audio for analysis.")

            # Log decoded sizes for debugging
            self.log(f"  [Corrector] Decoded audio: ref={len(ref_pcm)} samples, analysis={len(analysis_pcm)} samples")

            # Check minimum audio length
            min_duration_s = 5.0  # Require at least 5 seconds
            if len(ref_pcm) < sample_rate * min_duration_s or len(analysis_pcm) < sample_rate * min_duration_s:
                return CorrectionResult(CorrectionVerdict.FAILED, f"Audio too short for analysis (< {min_duration_s}s)")

            self.log("  [Corrector] Performing high-resolution scan for verification & triage...")
            window_s, step_s = 2.0, 0.25
            window_samples, step_samples = int(window_s * sample_rate), int(step_s * sample_rate)

            # Use the shorter of the two for safety
            min_length = min(len(ref_pcm), len(analysis_pcm))

            # Check if we have enough samples for at least one window
            if min_length < window_samples:
                return CorrectionResult(CorrectionVerdict.FAILED, f"Audio too short for window size ({min_length} < {window_samples} samples)")

            num_chunks = int((min_length - window_samples) / step_samples)

            if num_chunks <= 0:
                return CorrectionResult(CorrectionVerdict.FAILED, "Not enough audio chunks for analysis")

            self.log(f"  [Corrector] Processing {num_chunks} chunks...")

            delay_signal = np.zeros(num_chunks)
            valid_chunks = 0

            for i in range(num_chunks):
                start = i * step_samples
                end = start + window_samples

                # Extra safety check
                if end > min_length:
                    break

                ref_chunk = ref_pcm[start:end]
                analysis_chunk = analysis_pcm[start:end]

                # Check for silent/flat chunks
                ref_std = np.std(ref_chunk)
                analysis_std = np.std(analysis_chunk)

                # Skip if either chunk is silent/flat
                if ref_std < 1e-6 or analysis_std < 1e-6:
                    # Use previous delay for continuity
                    delay_signal[i] = delay_signal[i-1] if i > 0 else base_delay_ms
                    continue

                # Normal correlation calculation
                r = (ref_chunk - np.mean(ref_chunk)) / (ref_std + 1e-9)
                t = (analysis_chunk - np.mean(analysis_chunk)) / (analysis_std + 1e-9)

                c = correlate(r, t, mode='full', method='fft')
                k = np.argmax(np.abs(c))
                delay_signal[i] = int(round((float(k - (len(t) - 1)) / sample_rate) * 1000.0))
                valid_chunks += 1

            if valid_chunks == 0:
                return CorrectionResult(CorrectionVerdict.FAILED, "No valid audio chunks found (all silent/corrupted)")

            self.log(f"  [Corrector] Processed {valid_chunks}/{num_chunks} valid chunks")

            # Check for uniform delay
            if np.std(delay_signal) < 15:
                median_delay = int(round(np.median(delay_signal)))
                self.log(f"  [Corrector] Triage Result: Uniform delay detected. Overriding with more accurate delay of {median_delay} ms.")
                return CorrectionResult(CorrectionVerdict.UNIFORM, median_delay)

            # Check for stepped delay
            algo = rpt.Binseg(model="l1").fit(delay_signal)
            penalty = np.log(num_chunks) * np.std(delay_signal)**2 * 0.1
            change_points = algo.predict(pen=penalty)
            num_segments = len(change_points)

            if 2 <= num_segments <= 5:
                self.log(f"  [Corrector] Triage Result: Stepped delay confirmed ({num_segments} segments). Proceeding with correction.")
                edl = self._build_precise_edl(ref_pcm, analysis_pcm, delay_signal, sample_rate, base_delay_ms, step_samples)
                if not edl:
                    return CorrectionResult(CorrectionVerdict.FAILED, "Failed to build timing map.")
                return self._run_tier2_assembly(ref_file_path, analysis_pcm, edl, target_audio_path, temp_dir)
            else:
                self.log(f"  [Corrector] Triage Result: Complex sync detected ({num_segments} segments). Full fingerprinting would be required.")
                return CorrectionResult(CorrectionVerdict.COMPLEX, f"Sync is too complex ({num_segments} segments found).")

        except Exception as e:
            self.log(f"[FATAL] AudioCorrector failed with exception: {e}")
            import traceback
            self.log(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return CorrectionResult(CorrectionVerdict.FAILED, str(e))

    def _run_tier2_assembly(self, ref_file_path: str, analysis_pcm: np.ndarray, edl: List[AudioSegment], target_audio_path: str, temp_dir: Path) -> CorrectionResult:
        """Encapsulates the assembly and QA process for a simple stepped correction."""
        try:
            target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
            target_channels, target_layout, sample_rate = _get_audio_properties(target_audio_path, target_index, self.runner, self.tool_paths)

            qa_pcm = self._assemble_from_pcm_in_memory(analysis_pcm, edl, 1, sample_rate)
            qa_track_path = temp_dir / "qa_track.flac"
            if not self._encode_pcm_to_file(qa_pcm, qa_track_path, 1, 'mono', sample_rate):
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed to assemble QA track.")
            del qa_pcm

            if not self._qa_check(str(qa_track_path), ref_file_path, edl[0].delay_ms):
                return CorrectionResult(CorrectionVerdict.FAILED, "Corrected track failed QA check.")

            del analysis_pcm
            gc.collect()

            self.log(f"  [Corrector] Decoding target audio track to memory ({target_layout})...")
            target_pcm = self._decode_to_memory(target_audio_path, target_index, sample_rate, target_channels, force_mono=False)
            if target_pcm is None:
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed to decode target audio.")

            self.log("  [Corrector] Assembling final corrected track in memory...")
            final_pcm = self._assemble_from_pcm_in_memory(target_pcm, edl, target_channels, sample_rate)
            del target_pcm
            gc.collect()

            source_key = Path(target_audio_path).stem.split('_track_')[0]
            final_corrected_path = temp_dir / f"corrected_{source_key}.flac"

            if not self._encode_pcm_to_file(final_pcm, final_corrected_path, target_channels, target_layout, sample_rate):
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed during final track assembly.")
            del final_pcm
            gc.collect()

            return CorrectionResult(CorrectionVerdict.STEPPED, final_corrected_path)
        except Exception as e:
            return CorrectionResult(CorrectionVerdict.FAILED, f"Tier 2 assembly failed: {e}")
