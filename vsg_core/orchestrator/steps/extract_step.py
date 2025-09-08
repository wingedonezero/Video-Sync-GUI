# vsg_core/orchestrator/steps/extract_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import PlanItem
from vsg_core.models.media import Track, StreamProps
from vsg_core.models.enums import SourceRole, TrackType
from vsg_core.extraction.tracks import extract_tracks  # ← direct import


class ExtractStep:
    """
    Extracts selected tracks per manual layout and produces PlanItem list
    with extracted_path + per-track rules.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.extracted_items = []
            return ctx

        ref_ids = [t['id'] for t in ctx.manual_layout if t.get('source', '').upper() == 'REF']
        sec_ids = [t['id'] for t in ctx.manual_layout if t.get('source', '').upper() == 'SEC']
        ter_ids = [t['id'] for t in ctx.manual_layout if t.get('source', '').upper() == 'TER']

        runner._log_message(
            f"Manual selection: preparing to extract {len(ref_ids)} REF, "
            f"{len(sec_ids)} SEC, {len(ter_ids)} TER tracks."
        )

        ref_tracks_ext = extract_tracks(ctx.ref_file, ctx.temp_dir, runner, ctx.tool_paths, 'ref', specific_tracks=ref_ids)
        sec_tracks_ext = extract_tracks(ctx.sec_file, ctx.temp_dir, runner, ctx.tool_paths, 'sec', specific_tracks=sec_ids) if (ctx.sec_file and sec_ids) else []
        ter_tracks_ext = extract_tracks(ctx.ter_file, ctx.temp_dir, runner, ctx.tool_paths, 'ter', specific_tracks=ter_ids) if (ctx.ter_file and ter_ids) else []

        extracted_map: Dict[str, Dict[str, Any]] = {
            f"{t['source'].upper()}_{t['id']}": t
            for t in (ref_tracks_ext + sec_tracks_ext + ter_tracks_ext)
        }

        items: List[PlanItem] = []
        for sel in ctx.manual_layout:
            key = f"{sel.get('source','').upper()}_{sel['id']}"
            trk = extracted_map.get(key)
            if not trk:
                runner._log_message(f"[WARNING] Could not find extracted file for {key}. Skipping.")
                continue

            try:
                src_role = SourceRole[trk.get('source', 'REF').upper()]
            except Exception:
                src_role = SourceRole.REF
            try:
                ttype = TrackType(trk.get('type', 'video'))
            except Exception:
                ttype = TrackType.VIDEO

            track_model = Track(
                source=src_role,
                id=int(trk['id']),
                type=ttype,
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
                    user_modified_path=sel.get('user_modified_path') # NEW: Pass the modified path
                )
            )

        ctx.extracted_items = items
        return ctx
