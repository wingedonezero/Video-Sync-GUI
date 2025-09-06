# -*- coding: utf-8 -*-
from collections import Counter
from typing import Dict, List

def make_signature(track_info: Dict[str, List[dict]], *, strict: bool = False) -> Counter:
    """
    Build a signature of available tracks per source for auto-apply matching.
    Non-strict: counts by (source, type)
    Strict:     counts by (source, type, lang, codec_id)
    """
    if not strict:
        return Counter(
            f"{t['source']}_{t['type']}"
            for source_list in (track_info or {}).values()
            for t in source_list
        )
    return Counter(
        f"{t['source']}_{t['type']}_{(t.get('lang') or 'und').lower()}_{(t.get('codec_id') or '').lower()}"
        for source_list in (track_info or {}).values()
        for t in source_list
    )

def materialize_layout(abstract_layout: List[dict], track_info: Dict[str, List[dict]]) -> List[dict]:
    """
    Map a template layout (no per-file IDs) to the current file's tracks by (source,type) order.
    Returns a realized layout list with IDs and user flags carried over.
    """
    pools = {'REF': [], 'SEC': [], 'TER': []}
    for src in pools:
        pools[src] = [t for t in track_info.get(src, [])]

    counters = {}
    realized = []
    for item in abstract_layout or []:
        src = item.get('source'); ttype = item.get('type')
        idx = counters.get((src, ttype), 0)
        matching = [t for t in pools.get(src, []) if t.get('type') == ttype]
        if idx < len(matching):
            base = matching[idx].copy()
            base.update({
                'is_default': item.get('is_default', False),
                'is_forced_display': item.get('is_forced_display', False),
                'apply_track_name': item.get('apply_track_name', False),
                'convert_to_ass': item.get('convert_to_ass', False),
                'rescale': item.get('rescale', False),
                'size_multiplier': item.get('size_multiplier', 1.0),
            })
            realized.append(base)
        counters[(src, ttype)] = idx + 1
    return realized

def to_template(layout: List[dict]) -> List[dict]:
    """
    Strip per-file fields so we can reuse layout as a template across files (no persistence).
    """
    keep = {'source','type','is_default','is_forced_display','apply_track_name','convert_to_ass','rescale','size_multiplier'}
    return [{k: v for k, v in t.items() if k in keep} for t in (layout or [])]
