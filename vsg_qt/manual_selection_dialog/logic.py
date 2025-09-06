from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple

class ManualLogic:
    """
    Pure logic helpers used by the ManualSelectionDialog UI.
    Keeps the UI code small and testable.
    """

    # -------- Guardrails --------
    @staticmethod
    def is_blocked_video(track_data: dict) -> bool:
        try:
            return (
                (track_data.get('type', '').lower() == 'video') and
                (track_data.get('source', '').upper() in ('SEC', 'TER'))
            )
        except Exception:
            return False

    # -------- Pre-population (map previous abstract layout by (source,type,order)) --------
    @staticmethod
    def prepopulate(layout: List[dict], track_info: Dict[str, List[dict]]) -> List[dict]:
        """
        Given a previous abstract layout (no ids), produce a realized list of
        tracks from this file, matching by (source, type, order within that type).
        """
        if not layout:
            return []
        # pool: (SRC, TYPE, ORDER) -> track_dict
        pools = {}
        counters = {}
        for src in ('REF', 'SEC', 'TER'):
            for t in track_info.get(src, []):
                key = (src, t['type'], counters.get((src, t['type']), 0))
                pools[key] = t
                counters[(src, t['type'])] = counters.get((src, t['type']), 0) + 1

        # realize
        counters.clear()
        realized = []
        for prev in layout:
            src, ttype = prev.get('source'), prev.get('type')
            idx = counters.get((src, ttype), 0)
            counters[(src, ttype)] = idx + 1
            match = pools.get((src, ttype, idx))
            if not match:
                continue
            d = match.copy()
            d.update({
                'is_default': prev.get('is_default', False),
                'is_forced_display': prev.get('is_forced_display', False),
                'apply_track_name': prev.get('apply_track_name', False),
                'convert_to_ass': prev.get('convert_to_ass', False),
                'rescale': prev.get('rescale', False),
                'size_multiplier': prev.get('size_multiplier', 1.0),
            })
            realized.append(d)
        return realized

    # -------- Build final layout payload from TrackWidget instances --------
    @staticmethod
    def build_layout_from_widgets(widgets: List[Any]) -> List[dict]:
        out: List[dict] = []
        for w in widgets:
            td = dict(w.track_data)  # original dict from source list
            cfg = {}
            if hasattr(w, 'cb_default'):        cfg['is_default'] = w.cb_default.isChecked()
            if hasattr(w, 'cb_forced'):         cfg['is_forced_display'] = w.cb_forced.isChecked()
            if hasattr(w, 'cb_name'):           cfg['apply_track_name'] = w.cb_name.isChecked()
            if hasattr(w, 'cb_rescale'):        cfg['rescale'] = w.cb_rescale.isChecked()
            if hasattr(w, 'cb_convert'):        cfg['convert_to_ass'] = w.cb_convert.isChecked()
            if hasattr(w, 'size_multiplier'):    cfg['size_multiplier'] = w.size_multiplier.value()
            td.update(cfg)
            out.append(td)
        return out

    # -------- Normalization helpers --------
    @staticmethod
    def normalize_single_default_for_type(widgets: List[Any], ttype: str, prefer_widget=None):
        """
        Ensure only one 'Default' per type. If none, set first one true.
        """
        first = None
        for w in widgets:
            if getattr(w, 'track_type', None) != ttype:
                continue
            if not hasattr(w, 'cb_default'):
                continue
            if prefer_widget and w is prefer_widget:
                w.cb_default.setChecked(True)
                first = w
            elif w.cb_default.isChecked():
                if not first:
                    first = w
                else:
                    w.cb_default.setChecked(False)
            if hasattr(w, 'refresh_badges'):  w.refresh_badges()
            if hasattr(w, 'refresh_summary'): w.refresh_summary()

        if not first:
            # pick the first widget of that type as default
            for w in widgets:
                if getattr(w, 'track_type', None) == ttype and hasattr(w, 'cb_default'):
                    w.cb_default.setChecked(True)
                    if hasattr(w, 'refresh_badges'):  w.refresh_badges()
                    if hasattr(w, 'refresh_summary'): w.refresh_summary()
                    break

    @staticmethod
    def normalize_forced_subtitles(widgets: List[Any]):
        """
        Ensure only one subtitles track has 'Forced'.
        """
        first = None
        for w in widgets:
            if getattr(w, 'track_type', None) != 'subtitles':
                continue
            if not hasattr(w, 'cb_forced'):
                continue
            if w.cb_forced.isChecked():
                if not first:
                    first = w
                else:
                    w.cb_forced.setChecked(False)
            if hasattr(w, 'refresh_badges'):  w.refresh_badges()
            if hasattr(w, 'refresh_summary'): w.refresh_summary()
