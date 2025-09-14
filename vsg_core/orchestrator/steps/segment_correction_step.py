# vsg_core/orchestrator/steps/segment_correction_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import copy

from vsg_core.orchestrator.steps.context import Context
from ...io.runner import CommandRunner
from ...models.enums import TrackType
from ...models.media import StreamProps
from ...analysis.segment_correction import AudioCorrector

class SegmentCorrectionStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.settings_dict.get('segmented_enabled', False):
            return ctx

        correction_jobs = []
        for item in ctx.extracted_items:
            # (THE FIX IS HERE) The PlanItem now has the user's selection directly.
            if item.track.type == TrackType.AUDIO and item.correction_source:
                if item.correction_source in ctx.segment_flags:
                    correction_jobs.append({
                        "target_item": item,
                        "edl_info": ctx.segment_flags[item.correction_source]
                    })

        if not correction_jobs:
            return ctx

        runner._log_message("--- Segmented Audio Correction Phase ---")

        extracted_audio_map = {
            f"{item.track.source}_{item.track.id}": item.extracted_path
            for item in ctx.extracted_items if item.track.type == TrackType.AUDIO
        }

        corrector = AudioCorrector(runner, ctx.tool_paths, ctx.settings_dict)

        for job in correction_jobs:
            target_item = job['target_item']
            edl_info = job['edl_info']

            analysis_track_path = extracted_audio_map.get(edl_info['analysis_track_key'])
            if not analysis_track_path:
                runner._log_message(f"[ERROR] Cannot correct '{target_item.track.props.name}': The analysis track {edl_info['analysis_track_key']} was not included in the final track selection.")
                continue

            ref_audio_path = ctx.sources.get("Source 1")

            corrected_path = corrector.run(
                ref_audio_path=str(ref_audio_path),
                target_audio_path=str(analysis_track_path),
                base_delay_ms=edl_info['base_delay'],
                temp_dir=ctx.temp_dir
            )

            if corrected_path:
                runner._log_message(f"[SUCCESS] Correction successful for {target_item.track.props.name}")

                target_item.extracted_path = corrected_path
                # This is a bit tricky, we need to modify the track property of a frozen dataclass
                # A proper solution would be to not use frozen dataclasses for PlanItem's track
                new_props = StreamProps(
                    codec_id="FLAC",
                    lang=target_item.track.props.lang,
                    name=f"{target_item.track.props.name} (Corrected)"
                )
                # Recreate the track object with new properties
                target_item.track = type(target_item.track)(**{**target_item.track.__dict__, 'props': new_props})
                target_item.is_default = True
                target_item.apply_track_name = True


                preserved_item = copy.deepcopy(target_item)
                preserved_item.is_preserved = True
                preserved_item.is_default = False

                original_props = StreamProps(
                    codec_id=edl_info['original_codec'], # We need to store this in the flag
                    lang=preserved_item.track.props.lang,
                    name=f"{edl_info['original_name']} (Original)"
                )
                preserved_item.track = type(preserved_item.track)(**{**preserved_item.track.__dict__, 'props': original_props})

                last_audio_idx = max([i for i, item in enumerate(ctx.extracted_items) if item.track.type == TrackType.AUDIO], default=-1)
                ctx.extracted_items.insert(last_audio_idx + 1, preserved_item)

        return ctx
