# vsg_core/mux/options_builder.py
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List
from ..models.jobs import MergePlan, PlanItem
from ..models.settings import AppSettings

class MkvmergeOptionsBuilder:
    def build(self, plan: MergePlan, settings: AppSettings) -> List[str]:
        tokens: List[str] = []

        if plan.chapters_xml:
            tokens += ['--chapters', str(plan.chapters_xml)]
        if settings.disable_track_statistics_tags:
            tokens += ['--disable-track-statistics-tags']

        # NEW: Handle corrected/preserved audio tracks for segmented correction
        corrected_tracks = [i for i, item in enumerate(plan.items) if 'Corrected' in (item.track.props.name or '')]
        preserved_tracks = [i for i, item in enumerate(plan.items) if 'Original' in (item.track.props.name or '')]

        default_audio_idx = self._first_index(plan.items, kind='audio', predicate=lambda it: it.is_default)
        default_sub_idx = self._first_index(plan.items, kind='subtitles', predicate=lambda it: it.is_default)
        first_video_idx = self._first_index(plan.items, kind='video', predicate=lambda it: True)
        forced_sub_idx = self._first_index(plan.items, kind='subtitles', predicate=lambda it: it.is_forced_display)

        # NEW: For segmented correction, ensure corrected tracks are default and preserved are not
        if corrected_tracks:
            # Make first corrected track the default audio
            for i, item in enumerate(plan.items):
                if item.track.type.value == 'audio':
                    if i in corrected_tracks:
                        item.is_default = (i == corrected_tracks[0])  # Only first corrected is default
                    elif i in preserved_tracks:
                        item.is_default = False  # Preserved tracks are never default

        order_entries: List[str] = []
        for i, item in enumerate(plan.items):
            tr = item.track
            delay_ms = self._effective_delay_ms(plan, item)

            # NEW: Corrected tracks get 0 delay (they're already perfectly synced)
            if 'Corrected' in (tr.props.name or ''):
                delay_ms = plan.delays.global_shift_ms  # Only apply global shift

            is_default = (i == first_video_idx) or (i == default_audio_idx) or (i == default_sub_idx)

            tokens += ['--language', f"0:{tr.props.lang or 'und'}"]
            if item.apply_track_name and (tr.props.name or '').strip():
                tokens += ['--track-name', f"0:{tr.props.name}"]

            tokens += ['--sync', f"0:{delay_ms:+d}"]
            tokens += ['--default-track-flag', f"0:{'yes' if is_default else 'no'}"]

            if (i == forced_sub_idx) and tr.type.value == 'subtitles':
                tokens += ['--forced-display-flag', '0:yes']

            tokens += ['--compression', '0:none']

            if settings.apply_dialog_norm_gain and tr.type.value == 'audio':
                cid = (tr.props.codec_id or '').upper()
                if 'AC3' in cid or 'EAC3' in cid:
                    tokens += ['--remove-dialog-normalization-gain', '0']

            if not item.extracted_path:
                raise ValueError(f"Plan item at index {i} ('{tr.props.name}') missing extracted_path")

            tokens += ['(', str(item.extracted_path), ')']
            order_entries.append(f"{i}:0")

        for att in plan.attachments or []:
            tokens += ['--attach-file', str(att)]

        if order_entries:
            tokens += ['--track-order', ','.join(order_entries)]

        return tokens

    def _first_index(self, items: List[PlanItem], kind: str, predicate) -> int:
        for i, it in enumerate(items):
            if it.track.type.value == kind and predicate(it):
                return i
        return -1

    def _effective_delay_ms(self, plan: MergePlan, item: PlanItem) -> int:
        tr = item.track
        d = plan.delays.global_shift_ms
        sync_key = item.sync_to if tr.source == 'External' else tr.source
        if sync_key and sync_key != "Source 1":
            d += plan.delays.source_delays_ms.get(sync_key, 0)
        return int(d)
