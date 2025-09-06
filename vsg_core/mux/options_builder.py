# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List
from ..models.jobs import MergePlan, PlanItem
from ..models.settings import AppSettings
from ..models.enums import SourceRole
from ..models.media import Track
# No runner here: the builder only returns tokens; writing @opts.json stays in your pipeline.

class MkvmergeOptionsBuilder:
    def build(self, plan: MergePlan, settings: AppSettings, output_file: Path) -> List[str]:
        tokens: List[str] = ['--output', str(output_file)]

        # Chapters & global flags
        if plan.chapters_xml:
            tokens += ['--chapters', str(plan.chapters_xml)]
        if settings.disable_track_statistics_tags:
            tokens += ['--disable-track-statistics-tags']

        # Compute indices for default/forced flags exactly like today
        default_audio_idx = self._first_index(plan.items, kind='audio', predicate=lambda it: it.is_default)
        default_sub_idx   = self._first_index(plan.items, kind='subtitles', predicate=lambda it: it.is_default)
        first_video_idx   = self._first_index(plan.items, kind='video', predicate=lambda it: True)
        forced_sub_idx    = self._first_index(plan.items, kind='subtitles', predicate=lambda it: it.is_forced_display)

        # Build per-track groups, keeping order
        order_entries: List[str] = []
        for i, item in enumerate(plan.items):
            tr = item.track
            delay_ms = self._effective_delay_ms(plan, tr)
            is_default = (
                (i == first_video_idx) or
                (i == default_audio_idx) or
                (i == default_sub_idx)
            )
            # language
            tokens += ['--language', f"0:{tr.props.lang or 'und'}"]
            # name
            if item.apply_track_name and (tr.props.name or '').strip():
                tokens += ['--track-name', f"0:{tr.props.name}"]
            # sync
            tokens += ['--sync', f"0:{delay_ms:+d}"]
            # default flag
            tokens += ['--default-track-flag', f"0:{'yes' if is_default else 'no'}"]
            # forced flag (subs only)
            if (i == forced_sub_idx) and tr.type.value == 'subtitles':
                tokens += ['--forced-display-flag', '0:yes']
            # compression
            tokens += ['--compression', '0:none']

            # dialog normalization removal for AC3/E-AC3 (audio only)
            if settings.apply_dialog_norm_gain and tr.type.value == 'audio':
                cid = (tr.props.codec_id or '').upper()
                if 'AC3' in cid or 'EAC3' in cid:
                    tokens += ['--remove-dialog-normalization-gain', '0']

            # group the source path in parentheses
            if not item.extracted_path:
                raise ValueError(f"Plan item at index {i} missing extracted_path")
            tokens += ['(', str(item.extracted_path), ')']

            order_entries.append(f"{i}:0")

        # Attachments, if any (fonts, etc.)
        for att in plan.attachments or []:
            tokens += ['--attach-file', str(att)]

        # Track order (positional indices)
        if order_entries:
            tokens += ['--track-order', ','.join(order_entries)]

        return tokens

    # ---- helpers ----
    def _first_index(self, items: List[PlanItem], kind: str, predicate) -> int:
        for i, it in enumerate(items):
            if it.track.type.value == kind and predicate(it):
                return i
        return -1

    def _effective_delay_ms(self, plan: MergePlan, tr: Track) -> int:
        # Same math as README & your pipeline: global_shift plus role-specific delay
        # REF uses just global; SEC/TER add their delays.
        d = plan.delays.global_shift_ms
        if tr.source == SourceRole.SEC:
            d += plan.delays.secondary_ms or 0
        elif tr.source == SourceRole.TER:
            d += plan.delays.tertiary_ms or 0
        return int(d)
