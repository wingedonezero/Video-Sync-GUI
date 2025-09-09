# vsg_core/orchestrator/steps/extract_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import PlanItem
from vsg_core.models.media import Track, StreamProps
from vsg_core.models.enums import TrackType
from vsg_core.extraction.tracks import extract_tracks

class ExtractStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.extracted_items = []
            return ctx

        all_extracted_tracks = []
        for source_key, source_path in ctx.sources.items():
            track_ids_to_extract = [t['id'] for t in ctx.manual_layout if t.get('source') == source_key]
            if track_ids_to_extract:
                runner._log_message(f"Preparing to extract {len(track_ids_to_extract)} track(s) from {source_key}...")
                extracted_for_source = extract_tracks(
                    str(source_path), ctx.temp_dir, runner, ctx.tool_paths,
                    role=source_key,
                    specific_tracks=track_ids_to_extract
                )
                all_extracted_tracks.extend(extracted_for_source)

        extracted_map: Dict[str, Dict[str, Any]] = {
            f"{t['source']}_{t['id']}": t
            for t in all_extracted_tracks
        }

        items: List[PlanItem] = []
        for sel in ctx.manual_layout:
            key = f"{sel.get('source', '')}_{sel['id']}"
            trk = extracted_map.get(key)
            if not trk:
                runner._log_message(f"[WARNING] Could not find extracted file for {key}. Skipping.")
                continue

            track_model = Track(
                source=sel['source'],
                id=int(trk['id']),
                type=TrackType(trk.get('type', 'video')),
                props=StreamProps(
                    codec_id=trk.get('codec_id', '') or '',
                    lang=trk.get('lang', 'und') or 'und',
                    name=trk.get('name', '') or ''
                )
            )

            items.append(
                PlanItem(
                    track=track_model,
                    extracted_path=Path(trk['path']),
                    is_default=bool(sel.get('is_default', False)),
                    is_forced_display=bool(sel.get('is_forced_display', False)),
                    apply_track_name=bool(sel.get('apply_track_name', False)),
                    convert_to_ass=bool(sel.get('convert_to_ass', False)),
                    rescale=bool(sel.get('rescale', False)),
                    size_multiplier=float(sel.get('size_multiplier', 1.0)),
                    style_patch=sel.get('style_patch'),
                    user_modified_path=sel.get('user_modified_path')
                )
            )

        ctx.extracted_items = items
        return ctx
