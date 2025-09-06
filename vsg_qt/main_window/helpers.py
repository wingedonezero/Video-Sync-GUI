# -*- coding: utf-8 -*-
from collections import Counter

def generate_track_signature(track_info: dict, *, strict: bool = False) -> Counter:
    """
    Build a signature for auto-apply matching.
    - non-strict: counts by (source, type)
    - strict: counts by (source, type, lang, codec)
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

def materialize_layout(abstract_layout: list[dict], track_info: dict) -> list[dict]:
    """
    Map a previous abstract layout (no IDs) onto the current file
    by (source,type) order.
    """
    pools = {'REF': [], 'SEC': [], 'TER': []}
    for src in pools.keys():
        pools[src] = [t for t in track_info.get(src, [])]

    counters = {}
    realized = []
    for item in (abstract_layout or []):
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

def layout_to_template(layout: list[dict]) -> list[dict]:
    """Strip per-file fields (no IDs) for in-memory carry-over only."""
    kept = {
        'source', 'type', 'is_default', 'is_forced_display',
        'apply_track_name', 'convert_to_ass', 'rescale', 'size_multiplier'
    }
    return [{k: v for k, v in t.items() if k in kept} for t in (layout or [])]
