# vsg_core/mux/options_builder.py
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from ..models.jobs import MergePlan, PlanItem
from ..models.settings import AppSettings
from ..models.enums import TrackType

if TYPE_CHECKING:
    from ..audit import AuditTrail

class MkvmergeOptionsBuilder:
    def build(self, plan: MergePlan, settings: AppSettings, audit: Optional['AuditTrail'] = None) -> List[str]:
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

            # Record delay calculation in audit trail
            sync_key = item.sync_to if tr.source == 'External' else tr.source
            stepping_adj = getattr(item, 'stepping_adjusted', False)
            frame_adj = getattr(item, 'frame_adjusted', False)

            # Determine reason for delay value
            if tr.source == "Source 1" and tr.type == TrackType.VIDEO:
                reason = "global_shift_only (video defines timeline)"
            elif tr.source == "Source 1" and tr.type == TrackType.AUDIO:
                reason = f"container_delay({round(item.container_delay_ms)}ms) + global_shift({plan.delays.global_shift_ms}ms)"
            elif tr.type == TrackType.SUBTITLES and stepping_adj:
                reason = "stepping_adjusted=True (delay embedded in subtitle file)"
            elif tr.type == TrackType.SUBTITLES and frame_adj:
                reason = "frame_adjusted=True (delay embedded in subtitle file)"
            else:
                reason = f"source_delays_ms[{sync_key}]"

            # DIAGNOSTIC: Log the delay calculation for subtitle tracks
            if tr.type == TrackType.SUBTITLES:
                raw_delay = plan.delays.source_delays_ms.get(sync_key, 0) if plan.delays else 0
                print(f"[MUX DEBUG] Subtitle track {tr.id} ({tr.source}):")
                print(f"[MUX DEBUG]   sync_key={sync_key}, raw_delay={raw_delay}ms")
                print(f"[MUX DEBUG]   stepping_adjusted={stepping_adj}, frame_adjusted={frame_adj}")
                print(f"[MUX DEBUG]   final_delay_to_mkvmerge={delay_ms}ms")
                print(f"[MUX DEBUG]   reason={reason}")

            # === AUDIT: Record mux track delay ===
            if audit:
                raw_delay_available = None
                if plan.delays and sync_key in plan.delays.raw_source_delays_ms:
                    raw_delay_available = plan.delays.raw_source_delays_ms.get(sync_key)

                audit.record_mux_track_delay(
                    track_idx=i,
                    source=tr.source,
                    track_type=tr.type.value,
                    track_id=tr.id,
                    final_delay_ms=delay_ms,
                    reason=reason,
                    raw_delay_available_ms=raw_delay_available,
                    stepping_adjusted=stepping_adj,
                    frame_adjusted=frame_adj,
                    sync_key=sync_key
                )

            is_default = (i == first_video_idx) or (i == default_audio_idx) or (i == default_sub_idx)

            # NEW: Use custom language if set, otherwise use original from track
            lang_code = item.custom_lang if item.custom_lang else (tr.props.lang or 'und')

            tokens += ['--language', f"0:{lang_code}"]

            # NEW: Use custom name if set, otherwise fall back to apply_track_name behavior
            if item.custom_name:
                tokens += ['--track-name', f"0:{item.custom_name}"]
            elif item.apply_track_name and (tr.props.name or '').strip():
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

            # NEW: Preserve original aspect ratio for video tracks
            if tr.type == TrackType.VIDEO and item.aspect_ratio:
                tokens += ['--aspect-ratio', f"0:{item.aspect_ratio}"]

            if not item.extracted_path:
                raise ValueError(f"Plan item at index {i} ('{tr.props.name}') missing extracted_path")

            tokens += ['(', str(item.extracted_path), ')']
            order_entries.append(f"{i}:0")

        for att in plan.attachments or []:
            tokens += ['--attach-file', str(att)]

        if order_entries:
            tokens += ['--track-order', ','.join(order_entries)]

        # === AUDIT: Record final tokens ===
        if audit:
            audit.record_mux_tokens(tokens)

        return tokens

    def _first_index(self, items: List[PlanItem], kind: str, predicate) -> int:
        for i, it in enumerate(items):
            if it.track.type.value == kind and predicate(it):
                return i
        return -1

    def _effective_delay_ms(self, plan: MergePlan, item: PlanItem) -> int:
        """
        Calculates the final sync delay for a track.

        CRITICAL: Video container delays from the source MKV should be IGNORED.
        Video defines the timeline and should only get the global shift.

        Source 1 VIDEO:
        - Ignore original container delays (playback artifacts, not real timing)
        - Only apply global shift to stay in sync with everything else

        Source 1 AUDIO:
        - Each track has its own container delay (real timing offset)
        - Preserve that delay and add global shift
        - This maintains Source 1's internal audio/video sync

        Source 1 SUBTITLES:
        - Use the correlation delay (which is 0 for Source 1 after initialization)
        - This delay already includes the global shift

        Other Sources (Source 2, Source 3, etc.):
        - Use the pre-calculated correlation delay
        - This delay already includes global shift from analysis

        External Subtitles:
        - Use the delay from the track they're synced to (sync_to field)
        """
        tr = item.track

        # Source 1 AUDIO: Preserve individual container delays + add global shift
        if tr.source == "Source 1" and tr.type == TrackType.AUDIO:
            # Use round() for proper rounding of negative values
            # int() truncates toward zero: int(-1001.825) = -1001 (wrong)
            # round() rounds to nearest: round(-1001.825) = -1002 (correct)
            container_delay = round(item.container_delay_ms)
            global_shift = plan.delays.global_shift_ms
            final_delay = container_delay + global_shift
            return final_delay

        # Source 1 VIDEO: ONLY apply global shift (IGNORE container delays)
        # Video defines the timeline - we don't preserve its container delays
        if tr.source == "Source 1" and tr.type == TrackType.VIDEO:
            return plan.delays.global_shift_ms

        # All other tracks: Use the correlation delay from analysis
        # This includes:
        # - Source 1 subtitles (delay is 0 + global shift)
        # - Audio/video from other sources (correlation delay + global shift)
        # - Subtitles from other sources (correlation delay + global shift)
        # - External subtitles (synced to a specific source)

        # SPECIAL CASE: Subtitles with stepping-adjusted timestamps
        # If subtitle timestamps were already adjusted for stepping corrections,
        # the base delay + stepping offsets are baked into the subtitle file.
        # Don't apply additional delay via mkvmerge to avoid double-applying.
        if tr.type == TrackType.SUBTITLES and item.stepping_adjusted:
            return 0

        # SPECIAL CASE: Subtitles with frame-perfect sync applied
        # If subtitle timestamps were already adjusted with frame-perfect sync,
        # the delay is baked into the subtitle file with frame-snapping applied.
        # Don't apply additional delay via mkvmerge to avoid double-applying.
        if tr.type == TrackType.SUBTITLES and getattr(item, 'frame_adjusted', False):
            return 0

        sync_key = item.sync_to if tr.source == 'External' else tr.source
        delay = plan.delays.source_delays_ms.get(sync_key, 0)
        # Use round() for proper rounding of negative values (safety for future refactoring)
        return round(delay)
