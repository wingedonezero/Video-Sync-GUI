# vsg_qt/main_window/helpers.py
# -*- coding: utf-8 -*-
from collections import Counter
from typing import Dict, List, Any

def get_style_signature(track_data: Dict[str, Any], track_index_in_type: int) -> str:
    track_name = (track_data.get('name') or '').strip()
    if track_name:
        # Sanitize name to be a valid key
        sanitized_name = track_name.replace(" ", "_")
        return f"name:{sanitized_name}"

    # Fallback for unnamed tracks
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
    """
    Map a previous abstract layout (no IDs) onto the current file
    by (source,type) order.
    """
    # DYNAMIC FIX: Build the pools dictionary dynamically from the sources present in the job.
    pools: Dict[str, List[Dict]] = {key: list(val) for key, val in track_info.items()}

    counters = {}
    realized = []
    for item in (abstract_layout or []):
        src = item.get('source'); ttype = item.get('type')
        if not src or not ttype:
            continue

        idx = counters.get((src, ttype), 0)

        # Find the next available track of the correct type from the correct source pool
        matching_tracks = [t for t in pools.get(src, []) if t.get('type') == ttype]

        if idx < len(matching_tracks):
            base = matching_tracks[idx].copy()
            base.update({
                'is_default': item.get('is_default', False),
                'is_forced_display': item.get('is_forced_display', False),
                'apply_track_name': item.get('apply_track_name', False),
                'convert_to_ass': item.get('convert_to_ass', False),
                'rescale': item.get('rescale', False),
                'size_multiplier': item.get('size_multiplier', 1.0),
                'style_patch': item.get('style_patch'),
                'user_modified_path': item.get('user_modified_path'),
            })
            realized.append(base)
        counters[(src, ttype)] = idx + 1
    return realized

def layout_to_template(layout: list[dict]) -> list[dict]:
    """Strip per-file fields (no IDs) for in-memory carry-over only."""
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
