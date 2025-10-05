# vsg_core/mux/options_builder.py
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List
from ..models.jobs import MergePlan, PlanItem
from ..models.settings import AppSettings
from ..models.enums import TrackType

class MkvmergeOptionsBuilder:
    def build(self, plan: MergePlan, settings: AppSettings) -> List[str]:
        tokens: List[str] = []

        if plan.chapters_xml:
            tokens += ['--chapters', str(plan.chapters_xml)]
        if settings.disable_track_statistics_tags:
            tokens += ['--disable-track-statistics-tags']

        # Separate final tracks from preserved original tracks
        final_items = [item for item in plan.items if not item.is_preserved]
        preserved_audio = [item for item in plan.items if item.is_preserved and item.track.type == TrackType.AUDIO]
        preserved_subs = [item for item in plan.items if item.is_preserved and item.track.type == TrackType.SUBTITLES]

        # Insert preserved audio tracks after the last main audio track
        if preserved_audio:
            last_audio_idx = -1
            for i, item in enumerate(final_items):
                if item.track.type == TrackType.AUDIO:
                    last_audio_idx = i
            # Correctly insert the list of preserved items
            if last_audio_idx != -1:
                final_items[last_audio_idx + 1:last_audio_idx + 1] = preserved_audio
            else:
                final_items.extend(preserved_audio)

        # Insert preserved subtitle tracks after the last main subtitle track
        if preserved_subs:
            last_sub_idx = -1
            for i, item in enumerate(final_items):
                if item.track.type == TrackType.SUBTITLES:
                    last_sub_idx = i
            # Correctly insert the list of preserved items
            if last_sub_idx != -1:
                final_items[last_sub_idx + 1:last_sub_idx + 1] = preserved_subs
            else:
                final_items.extend(preserved_subs)

        default_audio_idx = self._first_index(final_items, kind='audio', predicate=lambda it: it.is_default)
        default_sub_idx = self._first_index(final_items, kind='subtitles', predicate=lambda it: it.is_default)
        first_video_idx = self._first_index(final_items, kind='video', predicate=lambda it: True)
        forced_sub_idx = self._first_index(final_items, kind='subtitles', predicate=lambda it: it.is_forced_display)

        order_entries: List[str] = []
        for i, item in enumerate(final_items):
            tr = item.track

            delay_ms = self._effective_delay_ms(plan, item)
            is_default = (i == first_video_idx) or (i == default_audio_idx) or (i == default_sub_idx)

            # NEW: Use custom language if set, otherwise use original from track
            lang_code = item.custom_lang if item.custom_lang else (tr.props.lang or 'und')

            tokens += ['--language', f"0:{lang_code}"]
            if item.apply_track_name and (tr.props.name or '').strip():
                tokens += ['--track-name', f"0:{tr.props.name}"]

            tokens += ['--sync', f"0:{delay_ms:+d}"]
            tokens += ['--default-track-flag', f"0:{'yes' if is_default else 'no'}"]

            if (i == forced_sub_idx) and tr.type.value == 'subtitles':
                tokens += ['--forced-display-flag', '0:yes']

            if settings.disable_header_compression:
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
        """
        Calculates the final sync delay for a track.

        IMPORTANT: The delays in plan.delays.source_delays_ms already include:
        1. The raw correlation delay
        2. The Source 1 audio container delay (for chain correction)
        3. The global shift (to eliminate negative delays)

        For Source 1 tracks:
        - Each track has its own container delay (can be different per track)
        - We add the global shift to maintain sync with everything else

        For other sources:
        - Use the pre-calculated delay from plan.delays (already includes global shift)

        For subtitles:
        - Never use container delays (they're not meaningful timing offsets)
        """
        tr = item.track

        # Source 1 tracks get their original container delays PLUS global shift
        # BUT: Only for audio/video, never for subtitles
        if tr.source == "Source 1" and tr.type != TrackType.SUBTITLES:
            # Each Source 1 track may have a different container delay
            # We preserve that individual delay and add the global shift
            container_delay = int(item.container_delay_ms)
            global_shift = plan.delays.global_shift_ms
            final_delay = container_delay + global_shift

            # This preserves Source 1's internal sync while shifting everything
            # to eliminate negative delays from other sources
            return final_delay

        # For all other sources (Source 2, Source 3, External, etc.)
        # OR for any subtitle tracks (even from Source 1)
        # Use the delay calculated during analysis (already includes global shift)
        sync_key = item.sync_to if tr.source == 'External' else tr.source
        delay = plan.delays.source_delays_ms.get(sync_key, 0)

        return int(delay)
