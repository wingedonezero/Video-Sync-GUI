# vsg_core/correction/hybrid_step_drift.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import gc
import copy
import tempfile
from pathlib import Path
from typing import List, Dict, Any

import numpy as np

from ..io.runner import CommandRunner
from ..orchestrator.steps.context import Context
from ..models.media import StreamProps, Track
from ..models.enums import TrackType
from ..extraction.tracks import extract_tracks
from .stepping import SteppingCorrector, CorrectionResult, CorrectionVerdict, AudioSegment, _get_audio_properties, get_audio_stream_info
from ..analysis.audio_corr import run_audio_correlation # Import the main analysis function

def _analyze_segment_for_drift(chunks: List[Dict], r2_threshold: float) -> float:
    """A helper to analyze a SUBSET of chunks for linear drift."""
    if len(chunks) < 4:
        return 0.0
    times = np.array([c['start'] for c in chunks])
    delays = np.array([c['raw_delay'] for c in chunks])
    slope, intercept = np.polyfit(times, delays, 1)
    if abs(slope) > 0.5:
        y_predicted = slope * times + intercept
        r_squared = np.corrcoef(delays, y_predicted)[0, 1]**2
        if r_squared > r2_threshold:
            return slope
    return 0.0

class HybridCorrector(SteppingCorrector):
    """A self-contained corrector for hybrid stepping and drift issues."""

    def _apply_atempo_to_pcm(self, pcm_segment: np.ndarray, slope_ms_s: float, sr: int, channels: int, layout: str) -> np.ndarray:
        """Applies ffmpeg atempo filter to a raw PCM numpy array via a temporary file."""
        self.log(f"    - Applying atempo correction to a segment (slope: {slope_ms_s:.2f} ms/s)...")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_in_path = Path(temp_dir) / "temp_in.raw"
            temp_out_path = Path(temp_dir) / "temp_out.raw"
            temp_in_path.write_bytes(pcm_segment.tobytes())

            tempo_ratio = 1000.0 / (1000.0 + slope_ms_s)

            cmd = [
                'ffmpeg', '-y', '-nostdin', '-v', 'error',
                '-f', 's32le', '-ar', str(sr), '-ac', str(channels), '-channel_layout', layout,
                '-i', str(temp_in_path),
                '-af', f'atempo={tempo_ratio}',
                '-f', 's32le', '-ac', str(channels), '-ar', str(sr),
                str(temp_out_path)
            ]
            self.runner.run(cmd, self.tool_paths)

            corrected_bytes = temp_out_path.read_bytes()
            return np.frombuffer(corrected_bytes, dtype=np.int32)

    def _assemble_hybrid_from_segments(self, pcm_segments: List[np.ndarray], edl: List[AudioSegment], channels: int, sample_rate: int, log_prefix: str) -> np.ndarray:
        """Stitches corrected segments back together, applying stepping correction between them."""
        if not edl or not pcm_segments: return np.array([], dtype=np.int32)
        base_delay = edl[0].delay_ms
        current_base_delay = base_delay

        total_pcm_samples = sum(len(seg) for seg in pcm_segments)
        total_silence_samples = 0
        for i in range(1, len(edl)):
            silence_to_add_ms = edl[i].delay_ms - edl[i-1].delay_ms
            if silence_to_add_ms > 10:
                total_silence_samples += int(silence_to_add_ms / 1000 * sample_rate) * channels

        new_pcm = np.zeros(total_pcm_samples + total_silence_samples, dtype=np.int32)
        current_pos_in_new = 0

        for i, segment_pcm in enumerate(pcm_segments):
            end_copy_pos = current_pos_in_new + len(segment_pcm)
            if end_copy_pos <= len(new_pcm):
                new_pcm[current_pos_in_new : end_copy_pos] = segment_pcm
            current_pos_in_new = end_copy_pos

            if i + 1 < len(edl):
                next_action = edl[i+1]
                silence_to_add_ms = next_action.delay_ms - current_base_delay
                if silence_to_add_ms > 10:
                    self.log(f"    - [{log_prefix}] At {next_action.start_s:.3f}s: Inserting {silence_to_add_ms}ms of silence.")
                    silence_samples = int(silence_to_add_ms / 1000 * sample_rate) * channels
                    current_pos_in_new += silence_samples
                current_base_delay = next_action.delay_ms

        return new_pcm[:current_pos_in_new]

    def run(self, ref_file_path: str, analysis_audio_path: str, target_audio_path: str, base_delay_ms: int, temp_dir: Path) -> CorrectionResult:
        try:
            # ## 1. SELF-CONTAINED DETAILED DIAGNOSIS ##
            self.log("  [HybridCorrector] Performing its own detailed analysis...")
            # This is the "doctor running their own detailed tests".
            all_chunks = run_audio_correlation(
                ref_file=ref_file_path, target_file=analysis_audio_path, config=self.config,
                runner=self.runner, tool_paths=self.tool_paths, ref_lang=None, target_lang=None, role_tag="HybridInternal"
            )
            if len([c for c in all_chunks if c['accepted']]) < self.config.get('min_accepted_chunks', 3):
                 return CorrectionResult(CorrectionVerdict.FAILED, "Internal analysis failed to find enough confident chunks.")

            # ## 2. FIND STEP BOUNDARIES ##
            ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
            analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
            _, _, sample_rate = _get_audio_properties(analysis_audio_path, analysis_index, self.runner, self.tool_paths)
            ref_pcm = self._decode_to_memory(ref_file_path, ref_index, sample_rate)
            analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index, sample_rate)
            if ref_pcm is None or analysis_pcm is None: return CorrectionResult(CorrectionVerdict.FAILED, "Failed to decode audio.")

            coarse_map = self._perform_coarse_scan(ref_pcm, analysis_pcm, sample_rate)
            if not coarse_map: return CorrectionResult(CorrectionVerdict.FAILED, "Coarse scan failed.")

            edl: List[AudioSegment] = [AudioSegment(start_s=0.0, end_s=0.0, delay_ms=coarse_map[0][1])]
            triage_std_dev_ms = self.config.get('segment_triage_std_dev_ms', 50)
            for i in range(len(coarse_map) - 1):
                zone_start_s, delay_before = coarse_map[i]
                zone_end_s, delay_after = coarse_map[i+1]
                if abs(delay_before - delay_after) < triage_std_dev_ms: continue
                boundary_s_ref = self._find_boundary_in_zone(ref_pcm, analysis_pcm, sample_rate, zone_start_s, zone_end_s, delay_before, delay_after)
                boundary_s_target = boundary_s_ref + (delay_before / 1000.0)
                edl.append(AudioSegment(start_s=boundary_s_target, end_s=boundary_s_target, delay_ms=delay_after))
            edl = sorted(list(set(edl)), key=lambda x: x.start_s)
            self.log(f"  [HybridCorrector] Found {len(edl)} segments defined by EDL.")

            # ## 3. PROCESS SEGMENTS INDIVIDUALLY ##
            target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
            target_channels, target_layout, _ = _get_audio_properties(target_audio_path, target_index, self.runner, self.tool_paths)
            target_pcm = self._decode_to_memory(target_audio_path, target_index, sample_rate, target_channels)

            r2_threshold = self.config.get('drift_detection_r2_threshold', 0.90)
            corrected_analysis_segments, corrected_target_segments = [], []

            for i, segment_action in enumerate(edl):
                start_s, end_s = segment_action.start_s, (edl[i+1].start_s if i+1 < len(edl) else float('inf'))
                start_sample, end_sample = int(start_s * sample_rate), (int(end_s * sample_rate) if end_s != float('inf') else -1)

                analysis_segment_pcm = analysis_pcm[start_sample : end_sample]
                target_segment_pcm = target_pcm[start_sample * target_channels : (end_sample * target_channels) if end_sample != -1 else -1]

                chunks_in_segment = [c for c in all_chunks if start_s <= c['start'] < end_s]
                drift_slope = _analyze_segment_for_drift(chunks_in_segment, r2_threshold)

                if drift_slope != 0.0:
                    analysis_segment_pcm = self._apply_atempo_to_pcm(analysis_segment_pcm, drift_slope, sample_rate, 1, 'mono')
                    target_segment_pcm = self._apply_atempo_to_pcm(target_segment_pcm, drift_slope, sample_rate, target_channels, target_layout)

                corrected_analysis_segments.append(analysis_segment_pcm)
                corrected_target_segments.append(target_segment_pcm)

            # ## 4. ASSEMBLE AND QA ##
            self.log("  [HybridCorrector] Assembling temporary QA track...")
            qa_check_pcm = self._assemble_hybrid_from_segments(corrected_analysis_segments, edl, 1, sample_rate, "QA")

            qa_track_path = temp_dir / "qa_track_hybrid.flac"
            if not self._encode_pcm_to_file(qa_check_pcm, qa_track_path, 1, 'mono', sample_rate):
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed during QA track encoding.")
            del qa_check_pcm; gc.collect()

            if not self._qa_check(str(qa_track_path), ref_file_path, edl[0].delay_ms):
                return CorrectionResult(CorrectionVerdict.FAILED, "Corrected track failed QA check.")

            self.log("  [HybridCorrector] Assembling final corrected track...")
            final_pcm = self._assemble_hybrid_from_segments(corrected_target_segments, edl, target_channels, sample_rate, "Final")
            del target_pcm; gc.collect()

            source_key = Path(target_audio_path).stem.split('_track_')[0]
            final_path = temp_dir / f"corrected_{source_key}.flac"
            if not self._encode_pcm_to_file(final_pcm, final_path, target_channels, target_layout, sample_rate):
                return CorrectionResult(CorrectionVerdict.FAILED, "Failed during final track encoding.")
            del final_pcm; gc.collect()

            self.log(f"[SUCCESS] Hybrid correction successful for '{Path(target_audio_path).name}'")
            return CorrectionResult(CorrectionVerdict.STEPPED, final_path)

        except Exception as e:
            self.log(f"[FATAL] HybridCorrector failed: {e}")
            import traceback; self.log(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return CorrectionResult(CorrectionVerdict.FAILED, str(e))

def run_hybrid_correction(ctx: Context, runner: CommandRunner) -> Context:
    """Main entry point for the hybrid correction process."""
    for analysis_track_key, flag_info in ctx.hybrid_drift_flags.items():
        source_key = analysis_track_key.split('_')[0]
        base_delay_ms = flag_info['base_delay']

        target_item = next((item for item in ctx.extracted_items if item.track.source == source_key and item.track.type == TrackType.AUDIO and not item.is_preserved), None)
        if not target_item:
            runner._log_message(f"[HybridCorrection] Could not find a target audio track for {source_key} in layout. Skipping.")
            continue

        analysis_item = next((item for item in ctx.extracted_items if f"{item.track.source}_{item.track.id}" == analysis_track_key), None)
        if not analysis_item:
            runner._log_message(f"[HybridCorrection] Analysis track {analysis_track_key} not in layout. Extracting internally...")
            source_container_path = ctx.sources.get(source_key)
            track_id = int(analysis_track_key.split('_')[1])
            try:
                internal_extract = extract_tracks(source_container_path, ctx.temp_dir, runner, ctx.tool_paths, role=f"{source_key}_internal", specific_tracks=[track_id])
                if not internal_extract: raise RuntimeError("Internal extraction failed.")
                analysis_track_path = internal_extract[0]['path']
            except Exception as e:
                runner._log_message(f"[ERROR] Failed to internally extract analysis track {analysis_track_key}: {e}")
                continue
        else:
            analysis_track_path = str(analysis_item.extracted_path)

        corrector = HybridCorrector(runner, ctx.tool_paths, ctx.settings_dict)
        result: CorrectionResult = corrector.run(
            ref_file_path=ctx.sources.get("Source 1"),
            analysis_audio_path=analysis_track_path,
            target_audio_path=str(target_item.extracted_path),
            base_delay_ms=base_delay_ms,
            temp_dir=ctx.temp_dir
        )

        if result.verdict == CorrectionVerdict.STEPPED:
            corrected_path = result.data
            preserved_item = copy.deepcopy(target_item)
            preserved_item.is_preserved = True
            preserved_item.is_default = False
            original_props = preserved_item.track.props
            preserved_item.track = Track(source=preserved_item.track.source, id=preserved_item.track.id, type=preserved_item.track.type, props=StreamProps(codec_id=original_props.codec_id, lang=original_props.lang, name=f"{original_props.name} (Original)"))

            target_item.extracted_path = corrected_path
            target_item.is_corrected = True
            target_item.apply_track_name = True
            target_item.track = Track(source=target_item.track.source, id=target_item.track.id, type=target_item.track.type, props=StreamProps(codec_id="FLAC", lang=original_props.lang, name=f"{original_props.name} (Corrected)"))

            ctx.extracted_items.append(preserved_item)

        elif result.verdict == CorrectionVerdict.FAILED:
            raise RuntimeError(f"Hybrid correction for {source_key} failed: {result.data}")

    return ctx
