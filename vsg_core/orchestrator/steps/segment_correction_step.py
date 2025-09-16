# vsg_core/orchestrator/steps/segment_correction_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import copy

from vsg_core.orchestrator.steps.context import Context
from ...io.runner import CommandRunner
from ...models.enums import TrackType
from ...models.media import StreamProps, Track
from ...analysis.segment_correction import AudioCorrector, CorrectionVerdict, CorrectionResult
from ...extraction.tracks import extract_tracks

class SegmentCorrectionStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.settings_dict.get('segmented_enabled', False) or not ctx.segment_flags:
            return ctx

        extracted_audio_map = {
            f"{item.track.source}_{item.track.id}": item
            for item in ctx.extracted_items if item.track.type == TrackType.AUDIO
        }

        corrector = AudioCorrector(runner, ctx.tool_paths, ctx.settings_dict)
        ref_file_path = ctx.sources.get("Source 1")

        for analysis_track_key, flag_info in ctx.segment_flags.items():
            source_key = flag_info['analysis_track_key'].split('_')[0]
            base_delay_ms = flag_info['base_delay']

            target_items = [
                item for item in ctx.extracted_items
                if item.track.source == source_key and item.track.type == TrackType.AUDIO and not item.is_preserved
            ]

            if len(target_items) != 1:
                runner._log_message(f"[SegmentCorrection] Skipping {source_key}: Expected 1 audio track to correct, but found {len(target_items)}. Ambiguous target.")
                continue

            target_item = target_items[0]

            analysis_item = extracted_audio_map.get(analysis_track_key)
            if not analysis_item:
                runner._log_message(f"[SegmentCorrection] Analysis track {analysis_track_key} not in user selection. Extracting internally...")
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

            # --- Main Triage Logic ---
            result: CorrectionResult = corrector.run(
                ref_file_path=ref_file_path,
                analysis_audio_path=analysis_track_path,
                target_audio_path=str(target_item.extracted_path),
                base_delay_ms=base_delay_ms,
                temp_dir=ctx.temp_dir
            )

            if result.verdict == CorrectionVerdict.UNIFORM:
                new_delay = result.data
                runner._log_message(f"[SegmentCorrection] Overriding delay for {source_key} with more accurate value: {new_delay} ms.")
                if ctx.delays and source_key in ctx.delays.source_delays_ms:
                    ctx.delays.source_delays_ms[source_key] = new_delay

            elif result.verdict == CorrectionVerdict.STEPPED:
                corrected_path = result.data
                runner._log_message(f"[SUCCESS] Enhanced correction successful for '{target_item.track.props.name}'")

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

                target_item.extracted_path = corrected_path
                target_item.is_corrected = True
                target_item.track = Track(
                    source=target_item.track.source, id=target_item.track.id, type=target_item.track.type,
                    props=StreamProps(
                        codec_id="FLAC",
                        lang=original_props.lang,
                        name=f"{original_props.name} (Corrected)" if original_props.name else "Corrected Audio"
                    )
                )
                target_item.is_default = True
                target_item.apply_track_name = True

                ctx.extracted_items.append(preserved_item)

            elif result.verdict in [CorrectionVerdict.COMPLEX, CorrectionVerdict.FAILED]:
                error_message = result.data
                raise RuntimeError(f"Segment correction for {source_key} failed: {error_message}")

        return ctx
