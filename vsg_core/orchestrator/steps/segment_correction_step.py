# vsg_core/orchestrator/steps/segment_correction_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import copy

from vsg_core.orchestrator.steps.context import Context
from ...io.runner import CommandRunner
from ...models.enums import TrackType
from ...models.media import StreamProps, Track
from ...analysis.segment_correction import AudioCorrector
from ...extraction.tracks import extract_tracks

class SegmentCorrectionStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.settings_dict.get('segmented_enabled', False) or not ctx.segment_flags:
            return ctx

        # Identify which audio tracks the user wants to correct based on the final layout
        correction_jobs = []
        # Find the single audio track selected from each source flagged for correction
        for source_key in {flag['analysis_track_key'].split('_')[0] for flag in ctx.segment_flags.values()}:
            targets = [item for item in ctx.extracted_items if item.track.source == source_key and item.track.type == TrackType.AUDIO]
            if len(targets) == 1:
                target_item = targets[0]
                # Find the corresponding flag for this source
                for flag_key, flag_info in ctx.segment_flags.items():
                    if flag_key.startswith(source_key):
                        correction_jobs.append({
                            "target_item": target_item,
                            "flag_info": flag_info
                        })
                        break # Assume one flag per source for now
            else:
                runner._log_message(f"[SegmentCorrection] Skipping correction for {source_key}: Expected exactly 1 selected audio track but found {len(targets)}. Ambiguous target.")

        if not correction_jobs:
            return ctx

        runner._log_message("--- Segmented Audio Correction Phase ---")

        extracted_audio_map = {
            f"{item.track.source}_{item.track.id}": item
            for item in ctx.extracted_items
        }

        corrector = AudioCorrector(runner, ctx.tool_paths, ctx.settings_dict)

        for job in correction_jobs:
            target_item = job['target_item']
            flag_info = job['flag_info']
            analysis_track_key = flag_info['analysis_track_key']

            analysis_item = extracted_audio_map.get(analysis_track_key)

            if not analysis_item:
                runner._log_message(f"[SegmentCorrection] Analysis track {analysis_track_key} not in user selection. Extracting internally...")
                source_key, track_id_str = analysis_track_key.split('_')
                track_id = int(track_id_str)
                source_container_path = ctx.sources.get(source_key)

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

            ref_file_path = ctx.sources.get("Source 1")

            # THE FIX IS HERE: The `base_delay_ms` argument is removed from the call.
            corrected_path = corrector.run(
                ref_file_path=ref_file_path,
                analysis_audio_path=analysis_track_path,
                target_audio_path=str(target_item.extracted_path),
                temp_dir=ctx.temp_dir
            )

            if corrected_path:
                runner._log_message(f"[SUCCESS] Correction successful for '{target_item.track.props.name}'")

                preserved_item = copy.deepcopy(target_item)
                preserved_item.is_preserved = True
                preserved_item.is_default = False
                preserved_item.track = Track(
                    source=preserved_item.track.source, id=preserved_item.track.id, type=preserved_item.track.type,
                    props=StreamProps(
                        codec_id=preserved_item.track.props.codec_id,
                        lang=preserved_item.track.props.lang,
                        name=f"{preserved_item.track.props.name} (Original)"
                    )
                )

                target_item.extracted_path = corrected_path
                target_item.track = Track(
                    source=target_item.track.source, id=target_item.track.id, type=target_item.track.type,
                    props=StreamProps(
                        codec_id="FLAC",
                        lang=target_item.track.props.lang,
                        name=f"{target_item.track.props.name} (Corrected)"
                    )
                )
                target_item.is_default = True
                target_item.apply_track_name = True

                last_audio_idx = max([i for i, item in enumerate(ctx.extracted_items) if item.track.type == TrackType.AUDIO and not item.is_preserved], default=-1)
                ctx.extracted_items.insert(last_audio_idx + 1, preserved_item)
        return ctx
