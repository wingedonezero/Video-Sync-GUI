# vsg_qt/main_window/helpers.py
# -*- coding: utf-8 -*-
from collections import Counter
from typing import Dict, List, Any

def get_style_signature(track_data: Dict[str, Any], track_index_in_type: int) -> str:
    track_name = (track_data.get('name') or '').strip()
    if track_name:
        sanitized_name = track_name.replace(" ", "_")
        return f"name:{sanitized_name}"
    source = track_data.get('source', 'UNK')
    track_type = track_data.get('type', 'subtitles')
    return f"order:{source}_{track_type}_{track_index_in_type}"

def generate_track_signature(track_info: dict, *, strict: bool = False) -> Counter:
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
                # --- FIX: Ensure style editor data is carried over ---
                'style_patch': item.get('style_patch'),
                'user_modified_path': item.get('user_modified_path'),
            })
            realized.append(base)
        counters[(src, ttype)] = idx + 1
    return realized

def layout_to_template(layout: list[dict]) -> list[dict]:
    kept = {
        'source', 'type', 'is_default', 'is_forced_display',
        'apply_track_name', 'convert_to_ass', 'rescale', 'size_multiplier',
        'style_patch', 'user_modified_path'
    }
    clean_layout = []
    for t in (layout or []):
        new_t = {k: v for k, v in t.items() if k in kept}
        clean_layout.append(new_t)
    return clean_layout
