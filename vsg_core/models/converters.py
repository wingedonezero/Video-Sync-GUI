# -*- coding: utf-8 -*-
from collections import Counter
from typing import Dict, List
from .enums import SourceRole, TrackType
from .media import Track, StreamProps
from .jobs import PlanItem

def _role_from_str(s: str) -> SourceRole:
    return SourceRole[s.upper()]

def _type_from_str(s: str) -> TrackType:
    return TrackType(s.lower())

def tracks_from_dialog_info(track_info: Dict[str, List[dict]]) -> Dict[SourceRole, List[Track]]:
    """
    Input shape matches mkv_utils.get_track_info_for_dialog():
      { 'REF':[...], 'SEC':[...], 'TER':[...]}
    """
    out: Dict[SourceRole, List[Track]] = {SourceRole.REF: [], SourceRole.SEC: [], SourceRole.TER: []}
    for src_key, items in (track_info or {}).items():
        role = _role_from_str(src_key)
        for t in items:
            out[role].append(
                Track(
                    source=role,
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
    track_info_by_role: Dict[SourceRole, List[Track]]
) -> List[PlanItem]:
    """
    Manual layout entries come from UI TrackWidget copies (dicts with 'source','id', etc.).
    We bind them to typed Tracks by (source,id); if not found, we skip (UI already guards).
    """
    # Build quick lookup
    idx = {
        (tr.source, tr.id): tr
        for role, tracks in track_info_by_role.items()
        for tr in tracks
    }
    realized: List[PlanItem] = []
    for sel in manual_layout or []:
        role = _role_from_str(sel['source'])
        tid  = int(sel['id'])
        maybe = idx.get((role, tid))
        if not maybe:
            # UI should have prevented this; ignore gracefully
            continue
        realized.append(
            PlanItem(
                track=maybe,
                extracted_path=None,
                is_default=bool(sel.get('is_default', False)),
                is_forced_display=bool(sel.get('is_forced_display', False)),
                apply_track_name=bool(sel.get('apply_track_name', False)),
                convert_to_ass=bool(sel.get('convert_to_ass', False)),
                rescale=bool(sel.get('rescale', False)),
                size_multiplier=float(sel.get('size_multiplier', 1.0))
            )
        )
    return realized

def signature_for_auto_apply(track_info: Dict[SourceRole, List[Track]], strict: bool = False) -> Counter:
    """
    Mirrors your current signature logic from MainWindow._generate_track_signature()
    """
    if not strict:
        return Counter(
            f"{tr.source.name}_{tr.type.value}"
            for tracks in track_info.values() for tr in tracks
        )
    return Counter(
        f"{tr.source.name}_{tr.type.value}_{(tr.props.lang or 'und').lower()}_{(tr.props.codec_id or '').lower()}"
        for tracks in track_info.values() for tr in tracks
    )
