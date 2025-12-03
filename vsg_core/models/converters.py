# vsg_core/models/converters.py
# -*- coding: utf-8 -*-
from collections import Counter
from typing import Dict, List

from .enums import TrackType
from .media import Track, StreamProps
from .jobs import PlanItem

def _type_from_str(s: str) -> TrackType:
    return TrackType(s.lower())

def tracks_from_dialog_info(track_info: Dict[str, List[dict]]) -> Dict[str, List[Track]]:
    """
    Converts the raw track info dictionary (keyed by "Source 1", etc.)
    into a dictionary of typed Track objects.
    """
    out: Dict[str, List[Track]] = {key: [] for key in track_info}
    for source_key, items in (track_info or {}).items():
        for t in items:
            out[source_key].append(
                Track(
                    source=source_key,
                    id=int(t['id']),
                    type=_type_from_str(t['type']),
                    props=StreamProps(
                        codec_id=t.get('codec_id','') or '',
                        lang=(t.get('lang') or 'und'),
                        name=(t.get('name') or '')
                    )
                )
            )
    return out

def realize_plan_from_manual_layout(
    manual_layout: List[dict],
    track_info_by_source: Dict[str, List[Track]]
) -> List[PlanItem]:
    """
    Binds the user's manual layout selections to the typed Track models for a job.
    """
    # Build a quick lookup map: (source_key, track_id) -> Track
    idx = {
        (tr.source, tr.id): tr
        for tracks in track_info_by_source.values()
        for tr in tracks
    }
    realized: List[PlanItem] = []
    for sel in manual_layout or []:
        source_key = sel['source']
        tid  = int(sel['id'])
        track_model = idx.get((source_key, tid))
        if not track_model:
            continue

        realized.append(
            PlanItem(
                track=track_model,
                extracted_path=None,
                is_default=bool(sel.get('is_default', False)),
                is_forced_display=bool(sel.get('is_forced_display', False)),
                apply_track_name=bool(sel.get('apply_track_name', False)),
                convert_to_ass=bool(sel.get('convert_to_ass', False)),
                rescale=bool(sel.get('rescale', False)),
                size_multiplier=float(sel.get('size_multiplier', 1.0)),
                custom_lang=sel.get('custom_lang', ''),
                custom_name=sel.get('custom_name', '')
            )
        )
    return realized

def signature_for_auto_apply(track_info: Dict[str, List[Track]], strict: bool = False) -> Counter:
    """
    Generates a track signature for a job, used for auto-applying layouts.
    """
    if not strict:
        return Counter(
            f"{tr.source}_{tr.type.value}"
            for tracks in track_info.values() for tr in tracks
        )
    return Counter(
        f"{tr.source}_{tr.type.value}_{(tr.props.lang or 'und').lower()}_{(tr.props.codec_id or '').lower()}"
        for tracks in track_info.values() for tr in tracks
    )
