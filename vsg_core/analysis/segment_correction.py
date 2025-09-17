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
from scipy.signal import correlate
from collections import Counter

from ..io.runner import CommandRunner
from ..analysis.audio_corr import get_audio_stream_info, run_audio_correlation

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
    return drift > config.get('segment_stepping_drift_threshold_ms', 250)

class AudioCorrector:
    def __init__(self, runner: CommandRunner, tool_paths: dict, config: dict):
        self.runner = runner
        self.tool_paths = tool_paths
        self.config = config
        self.log = runner._log_message

    def _decode_to_memory(self, file_path: str, stream_index: int, sample_rate: int, channels: int = 1) -> Optional[np.ndarray]:
        cmd = [ 'ffmpeg', '-nostdin', '-v', 'error', '-i', str(file_path), '-map', f'0:a:{stream_index}', '-ac', str(channels), '-ar', str(sample_rate), '-f', 's32le', '-' ]
        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes: return np.frombuffer(pcm_bytes, dtype=np.int32)
        self.log(f"[ERROR] Corrector failed to decode audio stream {stream_index} from '{Path(file_path).name}'")
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
        self.log("  [Corrector] Stage 1: Performing coarse scan to find delay zones...")
        chunk_duration_s = self.config.get('segment_coarse_chunk_s', 15)
        step_duration_s = self.config.get('segment_coarse_step_s', 60)
        locality_s = self.config.get('segment_search_locality_s', 10)

        chunk_samples = int(chunk_duration_s * sample_rate)
        step_samples = int(step_duration_s * sample_rate)
        locality_samples = int(locality_s * sample_rate)
        coarse_map = []
        num_samples = min(len(ref_pcm), len(analysis_pcm))

        initial_offset_seconds = self.config.get('segment_scan_offset_s', 15.0)
        start_offset_samples = int(initial_offset_seconds * sample_rate)

        for start_sample in range(start_offset_samples, num_samples - chunk_samples, step_samples):
            delay = self._get_delay_for_chunk(ref_pcm, analysis_pcm, start_sample, chunk_samples, sample_rate, locality_samples)
            if delay is not None:
                timestamp_s = start_sample / sample_rate
                coarse_map.append((timestamp_s, delay))
                self.log(f"    - Coarse point at {timestamp_s:.1f}s: delay = {delay}ms")
        return coarse_map

    def _find_boundary_in_zone(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, sample_rate: int, zone_start_s: float, zone_end_s: float, delay_before: int, delay_after: int) -> float:
        self.log(f"  [Corrector] Stage 2: Performing fine scan in zone {zone_start_s:.1f}s - {zone_end_s:.1f}s...")
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

    def _encode_pcm_to_file(self, pcm_data: np.ndarray, out_path: Path, channels: int, channel_layout: str, sample_rate: int) -> bool:
        cmd = [ 'ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels), '-channel_layout', channel_layout, '-i', '-', '-c:a', 'flac', str(out_path) ]
        return self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=pcm_data.tobytes()) is not None

    def _assemble_from_pcm_in_memory(self, pcm_data: np.ndarray, edl: List[AudioSegment], channels: int, sample_rate: int, log_prefix: str) -> np.ndarray:
        """Creates a corrected PCM stream using the trusted 'timeline walker' method."""
        if not edl: return pcm_data

        base_delay = edl[0].delay_ms
        total_silence_ms = sum(max(0, seg.delay_ms - base_delay) for seg in edl)
        total_silence_samples = int(total_silence_ms / 1000 * sample_rate) * channels
        final_sample_count = len(pcm_data) + total_silence_samples
        new_pcm = np.zeros(final_sample_count, dtype=np.int32)

        current_pos_in_new = 0
        last_pos_in_old = 0
        current_base_delay = base_delay

        for segment in edl:
            target_action_sample = int(segment.start_s * sample_rate) * channels

            if target_action_sample > last_pos_in_old:
                chunk_to_copy = pcm_data[last_pos_in_old:target_action_sample]
                if current_pos_in_new + len(chunk_to_copy) <= len(new_pcm):
                    new_pcm[current_pos_in_new : current_pos_in_new + len(chunk_to_copy)] = chunk_to_copy
                current_pos_in_new += len(chunk_to_copy)

            silence_to_add_ms = segment.delay_ms - current_base_delay
            if abs(silence_to_add_ms) > 10:
                if silence_to_add_ms > 0:
                    self.log(f"    - [{log_prefix}] At {segment.start_s:.3f}s: Inserting {silence_to_add_ms}ms of silence.")
                    silence_samples = int(silence_to_add_ms / 1000 * sample_rate) * channels
                    current_pos_in_new += silence_samples
                else:
                    self.log(f"    - [{log_prefix}] At {segment.start_s:.3f}s: Removing {-silence_to_add_ms}ms of audio.")

            current_base_delay = segment.delay_ms
            last_pos_in_old = target_action_sample

        if last_pos_in_old < len(pcm_data):
            final_chunk = pcm_data[last_pos_in_old:]
            end_position = current_pos_in_new + len(final_chunk)
            if end_position <= len(new_pcm):
               new_pcm[current_pos_in_new : end_position] = final_chunk
               current_pos_in_new = end_position

        return new_pcm[:current_pos_in_new]

    def _qa_check(self, corrected_path: str, ref_file_path: str, base_delay: int) -> bool:
        self.log("  [Corrector] Performing rigorous QA check on corrected audio map...")
        qa_config = self.config.copy()
        qa_threshold = self.config.get('segmented_qa_threshold', 85.0)
        qa_config.update({'scan_chunk_count': 30, 'min_accepted_chunks': 28, 'min_match_pct': qa_threshold})
        self.log(f"  [QA] Using minimum match confidence of {qa_threshold:.1f}%")

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
            if np.std(delays) > 10:
                self.log(f"  [QA] FAILED: Delay is unstable (Std Dev = {np.std(delays):.1f}ms).")
                return False
            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(self, ref_file_path: str, analysis_audio_path: str, target_audio_path: str, base_delay_ms: int, temp_dir: Path) -> CorrectionResult:
        try:
            ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
            analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
            if ref_index is None or analysis_index is None:
                return CorrectionResult(CorrectionVerdict.FAILED, "Could not find audio streams for analysis.")
            _, _, sample_rate = _get_audio_properties(analysis_audio_path, analysis_index, self.runner, self.tool_paths)

            ref_pcm = self._decode_to_memory(ref_file_path, ref_index, sample_rate)
            analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index, sample_rate)
            if ref_pcm is None or analysis_pcm is None:
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed to decode one or more audio tracks.")

            coarse_map = self._perform_coarse_scan(ref_pcm, analysis_pcm, sample_rate)
            if not coarse_map:
                return CorrectionResult(CorrectionVerdict.FAILED, "Coarse scan did not find any reliable sync points.")

            stable_delays = [d for t, d in coarse_map]
            triage_std_dev_ms = self.config.get('segment_triage_std_dev_ms', 50)
            if len(stable_delays) < 2 or np.std(stable_delays) < triage_std_dev_ms:
                self.log("  [Corrector] Triage Result: Uniform delay detected.")
                return CorrectionResult(CorrectionVerdict.UNIFORM, stable_delays[0] if stable_delays else base_delay_ms)

            edl: List[AudioSegment] = []
            anchor_delay = coarse_map[0][1]
            edl.append(AudioSegment(start_s=0.0, end_s=0.0, delay_ms=anchor_delay))

            for i in range(len(coarse_map) - 1):
                zone_start_s, delay_before = coarse_map[i]
                zone_end_s, delay_after = coarse_map[i+1]
                if abs(delay_before - delay_after) < triage_std_dev_ms:
                    continue

                boundary_s_ref = self._find_boundary_in_zone(ref_pcm, analysis_pcm, sample_rate, zone_start_s, zone_end_s, delay_before, delay_after)
                boundary_s_target = boundary_s_ref + (delay_before / 1000.0)
                edl.append(AudioSegment(start_s=boundary_s_target, end_s=boundary_s_target, delay_ms=delay_after))

            edl = sorted(list(set(edl)), key=lambda x: x.start_s)

            self.log("  [Corrector] Final Edit Decision List (EDL) for assembly created:")
            for i, seg in enumerate(edl): self.log(f"    - Action {i+1}: At target time {seg.start_s:.3f}s, new total delay is {seg.delay_ms}ms")

            return self._run_final_assembly(target_audio_path, edl=edl, temp_dir=temp_dir, ref_file_path=ref_file_path, analysis_pcm=analysis_pcm)

        except Exception as e:
            self.log(f"[FATAL] AudioCorrector failed with exception: {e}")
            import traceback
            self.log(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return CorrectionResult(CorrectionVerdict.FAILED, str(e))

    def _run_final_assembly(self, target_audio_path: str, edl: List[AudioSegment], temp_dir: Path, ref_file_path: str, analysis_pcm: np.ndarray) -> CorrectionResult:
        try:
            target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
            target_channels, target_layout, sample_rate = _get_audio_properties(target_audio_path, target_index, self.runner, self.tool_paths)

            self.log(f"  [Corrector] Stage 3: Decoding final target audio track ({target_layout})...")
            target_pcm = self._decode_to_memory(target_audio_path, target_index, sample_rate, target_channels)
            if target_pcm is None:
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed to decode target audio for final assembly.")

            self.log("  [Corrector] Assembling temporary QA track...")
            qa_check_pcm = self._assemble_from_pcm_in_memory(analysis_pcm, edl, 1, sample_rate, log_prefix="QA")

            qa_track_path = temp_dir / "qa_track.flac"
            if not self._encode_pcm_to_file(qa_check_pcm, qa_track_path, 1, 'mono', sample_rate):
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed during QA track encoding.")
            del qa_check_pcm; gc.collect()

            if not self._qa_check(str(qa_track_path), ref_file_path, edl[0].delay_ms):
                return CorrectionResult(CorrectionVerdict.FAILED, "Corrected track failed QA check.")

            self.log("  [Corrector] Assembling final corrected track in memory...")
            final_pcm = self._assemble_from_pcm_in_memory(target_pcm, edl, target_channels, sample_rate, log_prefix="Final")
            del target_pcm; gc.collect()

            source_key = Path(target_audio_path).stem.split('_track_')[0]
            final_corrected_path = temp_dir / f"corrected_{source_key}.flac"

            if not self._encode_pcm_to_file(final_pcm, final_corrected_path, target_channels, target_layout, sample_rate):
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed during final multichannel track encoding.")

            del final_pcm; gc.collect()

            self.log(f"[SUCCESS] Enhanced correction successful for '{Path(target_audio_path).name}'")
            return CorrectionResult(CorrectionVerdict.STEPPED, final_corrected_path)
        except Exception as e:
            return CorrectionResult(CorrectionVerdict.FAILED, f"Final assembly failed: {e}")
