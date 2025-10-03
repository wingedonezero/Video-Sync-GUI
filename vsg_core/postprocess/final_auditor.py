# vsg_core/postprocess/final_auditor.py
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from vsg_core.orchestrator.steps.context import Context
from vsg_core.io.runner import CommandRunner
from vsg_core.models.enums import TrackType
from vsg_core.models.jobs import PlanItem

class FinalAuditor:
    """
    Comprehensive post-merge validation that only logs warnings.
    Does not attempt to fix issues - those indicate bugs in earlier pipeline steps.
    """
    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.tool_paths = ctx.tool_paths
        self.log = runner._log_message
        self._source_ffprobe_cache: Dict[str, Optional[Dict]] = {}
        self._source_mkvmerge_cache: Dict[str, Optional[Dict]] = {}

    def run(self, final_mkv_path: Path):
        """
        Comprehensive audit of the final file - checks everything but modifies nothing.
        """
        self.log("========================================")
        self.log("=== POST-MERGE FINAL AUDIT STARTING ===")
        self.log("========================================")

        # Get metadata from the final file
        final_mkvmerge_data = self._get_metadata(str(final_mkv_path), 'mkvmerge')
        if not final_mkvmerge_data or 'tracks' not in final_mkvmerge_data:
            self.log("[ERROR] Could not read metadata from final file. Aborting audit.")
            return

        final_tracks = final_mkvmerge_data.get('tracks', [])
        final_plan_items = self.ctx.extracted_items
        total_issues = 0

        # Track count check
        if len(final_tracks) != len(final_plan_items):
            self.log(f"[WARNING] Track count mismatch! Plan expected {len(final_plan_items)}, but final file has {len(final_tracks)}.")
            total_issues += 1

        # === EXISTING AUDITS ===
        self.log("\n--- Auditing Track Flags (Default/Forced) ---")
        flag_issues = self._audit_track_flags(final_tracks, final_plan_items)
        total_issues += flag_issues

        # Get detailed ffprobe data for advanced checks
        final_ffprobe_data = self._get_metadata(str(final_mkv_path), 'ffprobe')
        if final_ffprobe_data:
            final_streams = final_ffprobe_data.get('streams', [])

            # Check HDR/DV/Color metadata
            self.log("\n--- Auditing Video Core Metadata (HDR, 3D, Color) ---")
            video_issues = self._audit_video_metadata_detailed(final_streams, final_mkvmerge_data, final_plan_items)
            total_issues += video_issues

            # Check Dolby Vision
            self.log("\n--- Auditing Dolby Vision Metadata ---")
            dv_issues = self._audit_dolby_vision(final_streams, final_plan_items)
            total_issues += dv_issues

            # Check Object-Based Audio
            self.log("\n--- Auditing Object-Based Audio (Atmos/DTS:X) ---")
            audio_issues = self._audit_object_based_audio(final_streams, final_plan_items)
            total_issues += audio_issues

            # === NEW AUDITS ===
            self.log("\n--- Auditing Codec Integrity ---")
            codec_issues = self._audit_codec_integrity(final_streams, final_plan_items)
            total_issues += codec_issues

            self.log("\n--- Auditing Audio Channel Layouts ---")
            channel_issues = self._audit_audio_channels(final_streams, final_plan_items)
            total_issues += channel_issues

            self.log("\n--- Auditing Audio Quality Parameters ---")
            quality_issues = self._audit_audio_quality_params(final_streams, final_plan_items)
            total_issues += quality_issues

        # More new checks that don't require ffprobe
        self.log("\n--- Auditing Audio Sync Delays ---")
        sync_issues = self._audit_audio_sync(final_mkv_path, final_mkvmerge_data)
        total_issues += sync_issues

        self.log("\n--- Auditing Subtitle Formats ---")
        subtitle_issues = self._audit_subtitle_formats(final_mkvmerge_data, final_plan_items)
        total_issues += subtitle_issues

        self.log("\n--- Auditing Chapters ---")
        chapter_issues = self._audit_chapters(final_mkv_path)
        total_issues += chapter_issues

        self.log("\n--- Auditing Track Order ---")
        order_issues = self._audit_track_order(final_tracks, final_plan_items)
        total_issues += order_issues

        self.log("\n--- Auditing Language Tags ---")
        lang_issues = self._audit_language_tags(final_tracks, final_plan_items)
        total_issues += lang_issues

        self.log("\n--- Auditing Track Names ---")
        name_issues = self._audit_track_names(final_tracks, final_plan_items)
        total_issues += name_issues

        # Check attachments
        self.log("\n--- Auditing Attachments ---")
        self._audit_attachments(final_mkvmerge_data.get('attachments', []))

        # Final summary
        self.log("\n========================================")
        if total_issues == 0:
            self.log("✅ FINAL AUDIT PASSED - NO ISSUES FOUND")
        else:
            self.log(f"⚠️  FINAL AUDIT FOUND {total_issues} POTENTIAL ISSUE(S)")
            self.log("    Please review the warnings above.")
        self.log("========================================\n")

    # ========================================================================
    # NEW AUDIT METHODS
    # ========================================================================

    def _audit_audio_sync(self, final_mkv_path: Path, final_mkvmerge_data: Dict) -> int:
        """
        Verifies that audio sync delays in the final file match what was calculated.
        This is CRITICAL because sync issues are the most noticeable defect.
        """
        issues = 0
        final_tracks = final_mkvmerge_data.get('tracks', [])

        if not self.ctx.delays:
            self.log("✅ No delays were calculated (single source or analysis skipped).")
            return 0

        # Build a mapping of track index to plan item
        audio_plan_items = [item for item in self.ctx.extracted_items if item.track.type == TrackType.AUDIO]

        # Get audio tracks from final file
        final_audio_tracks = [t for t in final_tracks if t.get('type') == 'audio']

        if len(final_audio_tracks) != len(audio_plan_items):
            self.log(f"[WARNING] Audio track count mismatch! Expected {len(audio_plan_items)}, got {len(final_audio_tracks)}.")
            issues += 1
            return issues

        for i, (plan_item, final_track) in enumerate(zip(audio_plan_items, final_audio_tracks)):
            # Calculate what the delay SHOULD be
            expected_delay_ms = self._calculate_expected_delay(plan_item)

            # Get actual delay from container
            # In MKV, this is stored in codec_delay (in nanoseconds)
            props = final_track.get('properties', {})

            # Try to get the delay from various possible fields
            actual_delay_ns = props.get('codec_delay', 0)
            actual_delay_ms = actual_delay_ns / 1_000_000.0 if actual_delay_ns else 0.0

            # Also check minimum_timestamp which might contain the delay
            min_timestamp = props.get('minimum_timestamp', 0)
            if min_timestamp and not actual_delay_ms:
                actual_delay_ms = min_timestamp / 1_000_000.0

            # Allow 1ms tolerance for floating point rounding
            tolerance_ms = 1.0
            diff_ms = abs(expected_delay_ms - actual_delay_ms)

            if diff_ms > tolerance_ms:
                source = plan_item.track.source
                lang = plan_item.track.props.lang or 'und'
                name = plan_item.track.props.name or f"Track {plan_item.track.id}"

                self.log(f"[WARNING] Audio sync mismatch for '{name}' ({source}, {lang}):")
                self.log(f"          Expected delay: {expected_delay_ms:+.1f}ms")
                self.log(f"          Actual delay:   {actual_delay_ms:+.1f}ms")
                self.log(f"          Difference:     {diff_ms:.1f}ms")
                issues += 1
            else:
                source = plan_item.track.source
                name = plan_item.track.props.name or f"Track {plan_item.track.id}"
                self.log(f"  ✓ '{name}' ({source}): {actual_delay_ms:+.1f}ms (within tolerance)")

        if issues == 0:
            self.log("✅ All audio sync delays are correct.")

        return issues

    def _calculate_expected_delay(self, plan_item: PlanItem) -> float:
        """
        Calculates what the delay SHOULD be for a given track based on the pipeline logic.
        This mirrors the logic in options_builder.py
        """
        tr = plan_item.track

        # Source 1 tracks use their original container delays (except subtitles)
        if tr.source == "Source 1" and tr.type != TrackType.SUBTITLES:
            return float(plan_item.container_delay_ms)

        # For other sources, use the calculated correlation delay
        sync_key = plan_item.sync_to if tr.source == 'External' else tr.source
        delay = self.ctx.delays.source_delays_ms.get(sync_key, 0)

        return float(delay)

    def _audit_codec_integrity(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Ensures codecs weren't accidentally transcoded during muxing.
        Exceptions: FLAC tracks from audio correction are expected.
        """
        issues = 0

        for i, plan_item in enumerate(plan_items):
            if i >= len(actual_streams):
                continue

            actual_stream = actual_streams[i]
            expected_codec = plan_item.track.props.codec_id.upper()
            actual_codec = actual_stream.get('codec_name', '').upper()

            # Skip if this is a corrected audio track (intentionally converted to FLAC)
            if plan_item.is_corrected and 'FLAC' in expected_codec:
                self.log(f"  ✓ Track {i}: Corrected audio (FLAC) as expected")
                continue

            # Map codec IDs to their common names for comparison
            codec_map = {
                'V_MPEGH/ISO/HEVC': 'HEVC',
                'V_MPEG4/ISO/AVC': 'H264',
                'A_AC3': 'AC3',
                'A_EAC3': 'EAC3',
                'A_DTS': 'DTS',
                'A_TRUEHD': 'TRUEHD',
                'A_FLAC': 'FLAC',
                'A_AAC': 'AAC',
                'A_OPUS': 'OPUS',
                'A_PCM/INT/LIT': 'PCM',
                'S_HDMV/PGS': 'HDMV_PGS',
                'S_TEXT/UTF8': 'SUBRIP',
                'S_TEXT/ASS': 'ASS',
                'S_TEXT/SSA': 'SSA',
            }

            expected_normalized = codec_map.get(expected_codec, expected_codec)
            actual_normalized = actual_codec

            # Handle PCM variants
            if 'PCM' in expected_normalized:
                expected_normalized = 'PCM'
            if actual_codec.startswith('PCM'):
                actual_normalized = 'PCM'

            if expected_normalized not in actual_normalized and actual_normalized not in expected_normalized:
                track_name = plan_item.track.props.name or f"Track {i}"
                self.log(f"[WARNING] Codec mismatch for '{track_name}':")
                self.log(f"          Expected: {expected_codec}")
                self.log(f"          Actual:   {actual_codec}")
                issues += 1

        if issues == 0:
            self.log("✅ All codecs preserved correctly (no unintended transcoding).")

        return issues

    def _audit_audio_channels(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Verifies channel counts and layouts weren't altered during muxing.
        Detects downmixing (7.1 → 5.1, stereo → mono, etc.)
        """
        issues = 0
        audio_items = [item for item in plan_items if item.track.type == TrackType.AUDIO]

        for plan_item in audio_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            # Find the source audio stream
            source_audio_streams = [s for s in source_data.get('streams', []) if s.get('codec_type') == 'audio']
            if plan_item.track.id >= len(source_audio_streams):
                continue

            source_audio = source_audio_streams[plan_item.track.id]

            # Find corresponding stream in output
            actual_audio_streams = [s for s in actual_streams if s.get('codec_type') == 'audio']
            actual_audio = None
            audio_index = 0
            for item in plan_items:
                if item.track.type == TrackType.AUDIO:
                    if item == plan_item and audio_index < len(actual_audio_streams):
                        actual_audio = actual_audio_streams[audio_index]
                        break
                    audio_index += 1

            if not actual_audio:
                continue

            # Compare channel counts
            source_channels = source_audio.get('channels', 0)
            actual_channels = actual_audio.get('channels', 0)

            if source_channels != actual_channels:
                track_name = plan_item.track.props.name or f"Track {plan_item.track.id}"
                self.log(f"[WARNING] Channel count mismatch for '{track_name}' ({plan_item.track.source}):")
                self.log(f"          Source: {source_channels} channels")
                self.log(f"          Output: {actual_channels} channels")

                if actual_channels < source_channels:
                    self.log(f"          CRITICAL: Audio was downmixed!")

                issues += 1
            else:
                # Also check channel layout if available
                source_layout = source_audio.get('channel_layout', '')
                actual_layout = actual_audio.get('channel_layout', '')

                if source_layout and actual_layout and source_layout != actual_layout:
                    track_name = plan_item.track.props.name or f"Track {plan_item.track.id}"
                    self.log(f"[WARNING] Channel layout changed for '{track_name}':")
                    self.log(f"          Source: {source_layout}")
                    self.log(f"          Output: {actual_layout}")
                    issues += 1

        if issues == 0:
            self.log("✅ All audio channel layouts preserved correctly.")

        return issues

    def _audit_audio_quality_params(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Checks for audio quality degradation (sample rate, bit depth changes).
        """
        issues = 0
        audio_items = [item for item in plan_items if item.track.type == TrackType.AUDIO]

        for plan_item in audio_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            # Find the source audio stream
            source_audio_streams = [s for s in source_data.get('streams', []) if s.get('codec_type') == 'audio']
            if plan_item.track.id >= len(source_audio_streams):
                continue

            source_audio = source_audio_streams[plan_item.track.id]

            # Find corresponding stream in output
            actual_audio_streams = [s for s in actual_streams if s.get('codec_type') == 'audio']
            actual_audio = None
            audio_index = 0
            for item in plan_items:
                if item.track.type == TrackType.AUDIO:
                    if item == plan_item and audio_index < len(actual_audio_streams):
                        actual_audio = actual_audio_streams[audio_index]
                        break
                    audio_index += 1

            if not actual_audio:
                continue

            track_name = plan_item.track.props.name or f"Track {plan_item.track.id}"

            # Check sample rate
            source_sample_rate = source_audio.get('sample_rate')
            actual_sample_rate = actual_audio.get('sample_rate')

            if source_sample_rate and actual_sample_rate:
                source_rate = int(source_sample_rate)
                actual_rate = int(actual_sample_rate)

                if source_rate != actual_rate:
                    self.log(f"[WARNING] Sample rate changed for '{track_name}' ({plan_item.track.source}):")
                    self.log(f"          Source: {source_rate} Hz")
                    self.log(f"          Output: {actual_rate} Hz")

                    if actual_rate < source_rate:
                        self.log(f"          CRITICAL: Audio was downsampled!")

                    issues += 1

            # Check bit depth (if available)
            source_bits = source_audio.get('bits_per_raw_sample') or source_audio.get('bits_per_sample')
            actual_bits = actual_audio.get('bits_per_raw_sample') or actual_audio.get('bits_per_sample')

            if source_bits and actual_bits:
                source_depth = int(source_bits)
                actual_depth = int(actual_bits)

                if source_depth != actual_depth:
                    self.log(f"[WARNING] Bit depth changed for '{track_name}':")
                    self.log(f"          Source: {source_depth}-bit")
                    self.log(f"          Output: {actual_depth}-bit")

                    if actual_depth < source_depth:
                        self.log(f"          CRITICAL: Bit depth reduced!")

                    issues += 1

        if issues == 0:
            self.log("✅ All audio quality parameters preserved correctly.")

        return issues

    def _audit_subtitle_formats(self, final_mkvmerge_data: Dict, plan_items: List[PlanItem]) -> int:
        """
        Validates subtitle conversions and OCR results.
        """
        issues = 0
        subtitle_items = [item for item in plan_items if item.track.type == TrackType.SUBTITLES]
        final_tracks = final_mkvmerge_data.get('tracks', [])

        # Get subtitle tracks from final file
        final_subtitle_tracks = [t for t in final_tracks if t.get('type') == 'subtitles']

        for i, plan_item in enumerate(subtitle_items):
            if i >= len(final_subtitle_tracks):
                self.log(f"[WARNING] Subtitle track {i} missing from final file!")
                issues += 1
                continue

            final_track = final_subtitle_tracks[i]
            track_name = plan_item.track.props.name or f"Subtitle {i}"

            # If OCR was performed, verify it resulted in a text format
            if plan_item.perform_ocr:
                codec_id = final_track.get('properties', {}).get('codec_id', '')
                if 'TEXT' not in codec_id.upper():
                    self.log(f"[WARNING] OCR track '{track_name}' is not in text format!")
                    self.log(f"          Codec: {codec_id}")
                    issues += 1
                else:
                    self.log(f"  ✓ OCR track '{track_name}' successfully converted to text")

            # If ASS conversion was requested, verify format
            if plan_item.convert_to_ass:
                codec_id = final_track.get('properties', {}).get('codec_id', '')
                if 'ASS' not in codec_id.upper() and 'SSA' not in codec_id.upper():
                    self.log(f"[WARNING] Track '{track_name}' was not converted to ASS/SSA!")
                    self.log(f"          Codec: {codec_id}")
                    issues += 1
                else:
                    self.log(f"  ✓ Track '{track_name}' successfully converted to ASS")

        if issues == 0:
            self.log("✅ All subtitle formats are correct.")

        return issues

    def _audit_chapters(self, final_mkv_path: Path) -> int:
        """
        Verifies chapters were preserved correctly.
        """
        issues = 0

        # Check if chapters were expected
        if not self.ctx.chapters_xml:
            self.log("✅ No chapters were processed (none expected).")
            return 0

        # Extract chapters from final file
        try:
            xml_content = self.runner.run(['mkvextract', str(final_mkv_path), 'chapters', '-'], self.tool_paths)

            if not xml_content or 'No chapters found' in xml_content:
                self.log("[WARNING] Chapters were processed but are MISSING from the final file!")
                issues += 1
            else:
                # Count chapters
                import re
                chapter_count = len(re.findall(r'<ChapterAtom>', xml_content))
                self.log(f"✅ Chapters preserved successfully ({chapter_count} chapter(s) found).")

        except Exception as e:
            self.log(f"[WARNING] Could not verify chapters: {e}")
            issues += 1

        return issues

    def _audit_track_order(self, final_tracks: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Ensures tracks appear in the expected order (video → audio → subtitles).
        Also verifies that preserved tracks appear after their main counterparts.
        """
        issues = 0

        # Build expected order by type
        type_order = []
        for track in final_tracks:
            track_type = track.get('type', 'unknown')
            type_order.append(track_type)

        # Check that video comes before audio
        video_indices = [i for i, t in enumerate(type_order) if t == 'video']
        audio_indices = [i for i, t in enumerate(type_order) if t == 'audio']
        subtitle_indices = [i for i, t in enumerate(type_order) if t == 'subtitles']

        if video_indices and audio_indices:
            if max(video_indices) > min(audio_indices):
                self.log("[WARNING] Track order issue: Audio tracks appear before some video tracks!")
                issues += 1

        if audio_indices and subtitle_indices:
            if max(audio_indices) > min(subtitle_indices):
                self.log("[WARNING] Track order issue: Subtitle tracks appear before some audio tracks!")
                issues += 1

        # Verify preserved tracks come after main tracks
        for i, item in enumerate(plan_items):
            if item.is_preserved:
                # Find the main track (should be before this one)
                main_track_found = False
                for j in range(i):
                    other_item = plan_items[j]
                    if (other_item.track.source == item.track.source and
                        other_item.track.type == item.track.type and
                        not other_item.is_preserved):
                        main_track_found = True
                        break

                if not main_track_found:
                    track_name = item.track.props.name or f"Track {i}"
                    self.log(f"[WARNING] Preserved track '{track_name}' appears without a main track before it!")
                    issues += 1

        if issues == 0:
            self.log("✅ Track order is correct.")

        return issues

    def _audit_language_tags(self, final_tracks: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Verifies language tags were preserved correctly.
        """
        issues = 0

        for i, item in enumerate(plan_items):
            if i >= len(final_tracks):
                continue

            expected_lang = item.track.props.lang or 'und'
            actual_lang = final_tracks[i].get('properties', {}).get('language', 'und')

            if expected_lang != actual_lang:
                track_name = item.track.props.name or f"Track {i}"
                self.log(f"[WARNING] Language tag mismatch for '{track_name}':")
                self.log(f"          Expected: '{expected_lang}'")
                self.log(f"          Actual:   '{actual_lang}'")
                issues += 1

        if issues == 0:
            self.log("✅ All language tags are correct.")

        return issues

    def _audit_track_names(self, final_tracks: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Verifies track names match expectations when apply_track_name is enabled.
        """
        issues = 0

        for i, item in enumerate(plan_items):
            if not item.apply_track_name:
                continue

            if i >= len(final_tracks):
                continue

            expected_name = item.track.props.name or ''
            actual_name = final_tracks[i].get('properties', {}).get('track_name', '')

            if expected_name and expected_name != actual_name:
                self.log(f"[WARNING] Track name mismatch for track {i}:")
                self.log(f"          Expected: '{expected_name}'")
                self.log(f"          Actual:   '{actual_name}'")
                issues += 1

        if issues == 0:
            self.log("✅ All track names are correct.")

        return issues

    # ========================================================================
    # EXISTING AUDIT METHODS (PRESERVED EXACTLY AS-IS)
    # ========================================================================

    def _audit_track_flags(self, actual_tracks: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Compares expected vs actual flags and logs warnings.
        Returns the number of issues found.
        """
        issues = 0

        # Group tracks by type for proper default flag checking
        video_tracks = [(i, t) for i, t in enumerate(actual_tracks) if t.get('type') == 'video']
        audio_tracks = [(i, t) for i, t in enumerate(actual_tracks) if t.get('type') == 'audio']
        subtitle_tracks = [(i, t) for i, t in enumerate(actual_tracks) if t.get('type') == 'subtitles']

        # Check if there's exactly one default per type (where it matters)
        default_videos = sum(1 for _, t in video_tracks if t.get('properties', {}).get('default_track', False))
        default_audios = sum(1 for _, t in audio_tracks if t.get('properties', {}).get('default_track', False))
        default_subs = sum(1 for _, t in subtitle_tracks if t.get('properties', {}).get('default_track', False))

        if default_videos > 1:
            self.log(f"[WARNING] Multiple default video tracks found ({default_videos}). Players may behave unexpectedly.")
            issues += 1

        if default_audios == 0 and audio_tracks:
            self.log("[WARNING] No default audio track set. Some players may not play audio automatically.")
            issues += 1
        elif default_audios > 1:
            self.log(f"[WARNING] Multiple default audio tracks found ({default_audios}).")
            issues += 1

        if default_subs > 1:
            self.log(f"[WARNING] Multiple default subtitle tracks found ({default_subs}).")
            issues += 1

        # Check forced flags on subtitles
        forced_subs = sum(1 for _, t in subtitle_tracks if t.get('properties', {}).get('forced_track', False))
        if forced_subs > 1:
            self.log(f"[WARNING] Multiple forced subtitle tracks found ({forced_subs}). Only one should be forced.")
            issues += 1

        if issues == 0:
            self.log("✅ All track flags are correct.")

        return issues

    def _audit_video_metadata_detailed(self, actual_streams: List[Dict], actual_mkvmerge_data: Dict, plan_items: List[PlanItem]) -> int:
        """Comprehensive check of video metadata preservation."""
        issues = 0
        video_items = [item for item in plan_items if item.track.type == TrackType.VIDEO]

        for plan_item in video_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            # Get both mkvmerge and ffprobe data for the source
            source_mkv_data = self._get_metadata(source_file, 'mkvmerge')
            source_ffprobe_data = self._get_metadata(source_file, 'ffprobe')
            if not source_ffprobe_data:
                continue

            source_video = next((s for s in source_ffprobe_data.get('streams', []) if s.get('codec_type') == 'video'), None)
            actual_video = next((s for s in actual_streams if s.get('codec_type') == 'video'), None)

            if not source_video or not actual_video:
                continue

            # Check resolution
            if source_video.get('width') != actual_video.get('width') or source_video.get('height') != actual_video.get('height'):
                self.log(f"[WARNING] Resolution mismatch! Source: {source_video.get('width')}x{source_video.get('height')}, "
                        f"Output: {actual_video.get('width')}x{actual_video.get('height')}")
                issues += 1

            # Check interlacing/field order (CRITICAL for telecined content)
            source_field_order = source_video.get('field_order', 'progressive')
            actual_field_order = actual_video.get('field_order', 'progressive')

            if source_field_order != actual_field_order:
                self.log(f"[WARNING] Field order mismatch! Source: '{source_field_order}', Output: '{actual_field_order}'")
                if source_field_order in ['tt', 'bb', 'tb', 'bt'] and actual_field_order == 'progressive':
                    self.log("         CRITICAL: Interlaced content marked as progressive! This will cause playback issues.")
                issues += 1

            # Check for telecine patterns in codec level
            source_codec_tag = source_video.get('codec_tag_string', '')
            actual_codec_tag = actual_video.get('codec_tag_string', '')

            # Check MKV-specific field order from mkvmerge data
            if source_mkv_data:
                source_mkv_video = next((t for t in source_mkv_data.get('tracks', []) if t.get('type') == 'video'), None)
                actual_mkv_video = next((t for t in actual_mkvmerge_data.get('tracks', []) if t.get('type') == 'video'), None)

                if source_mkv_video and actual_mkv_video:
                    source_mkv_field = source_mkv_video.get('properties', {}).get('field_order')
                    actual_mkv_field = actual_mkv_video.get('properties', {}).get('field_order')

                    if source_mkv_field != actual_mkv_field:
                        self.log(f"[WARNING] MKV field_order flag mismatch! Source: {source_mkv_field}, Output: {actual_mkv_field}")
                        if source_mkv_field and not actual_mkv_field:
                            self.log("         Field order information was lost! May cause deinterlacing issues.")
                        issues += 1

                    # Check stereo mode (3D)
                    source_stereo = source_mkv_video.get('properties', {}).get('stereo_mode')
                    actual_stereo = actual_mkv_video.get('properties', {}).get('stereo_mode')

                    if source_stereo != actual_stereo:
                        self.log(f"[WARNING] Stereo mode (3D) mismatch! Source: {source_stereo}, Output: {actual_stereo}")
                        issues += 1

            # Check HDR metadata in detail
            source_color_transfer = source_video.get('color_transfer', '')
            actual_color_transfer = actual_video.get('color_transfer', '')

            if source_color_transfer and source_color_transfer != actual_color_transfer:
                self.log(f"[WARNING] Color transfer mismatch! Source: '{source_color_transfer}', Output: '{actual_color_transfer}'")
                if source_color_transfer == 'smpte2084':
                    self.log("         HDR10 metadata was lost!")
                elif source_color_transfer == 'arib-std-b67':
                    self.log("         HLG metadata was lost!")
                issues += 1

            # Check color primaries
            if source_video.get('color_primaries') != actual_video.get('color_primaries'):
                self.log(f"[WARNING] Color primaries mismatch! Source: '{source_video.get('color_primaries')}', "
                        f"Output: '{actual_video.get('color_primaries')}'")
                issues += 1

            # Check color space/matrix coefficients
            if source_video.get('color_space') != actual_video.get('color_space'):
                self.log(f"[WARNING] Color space mismatch! Source: '{source_video.get('color_space')}', "
                        f"Output: '{actual_video.get('color_space')}'")
                issues += 1

            # Check pixel format (important for HDR)
            if source_video.get('pix_fmt') != actual_video.get('pix_fmt'):
                self.log(f"[WARNING] Pixel format mismatch! Source: '{source_video.get('pix_fmt')}', "
                        f"Output: '{actual_video.get('pix_fmt')}'")
                if 'yuv420p10' in source_video.get('pix_fmt', '') and 'yuv420p' in actual_video.get('pix_fmt', ''):
                    self.log("         CRITICAL: 10-bit video downgraded to 8-bit!")
                issues += 1

            # Check color range (limited vs full)
            if source_video.get('color_range') != actual_video.get('color_range'):
                self.log(f"[WARNING] Color range mismatch! Source: '{source_video.get('color_range')}', "
                        f"Output: '{actual_video.get('color_range')}'")
                issues += 1

            # Check chroma location
            if source_video.get('chroma_location') != actual_video.get('chroma_location'):
                self.log(f"[WARNING] Chroma location mismatch! Source: '{source_video.get('chroma_location')}', "
                        f"Output: '{actual_video.get('chroma_location')}'")
                issues += 1

            # Check aspect ratios
            source_dar = source_video.get('display_aspect_ratio')
            actual_dar = actual_video.get('display_aspect_ratio')
            if source_dar != actual_dar:
                self.log(f"[WARNING] Display aspect ratio mismatch! Source: '{source_dar}', Output: '{actual_dar}'")
                issues += 1

            # Check frame rate (should match exactly)
            source_fps = source_video.get('avg_frame_rate')
            actual_fps = actual_video.get('avg_frame_rate')
            if source_fps != actual_fps:
                self.log(f"[WARNING] Frame rate mismatch! Source: '{source_fps}', Output: '{actual_fps}'")
                issues += 1

            # Check mastering display metadata
            source_mastering = self._get_mastering_display(source_video)
            actual_mastering = self._get_mastering_display(actual_video)

            if source_mastering and not actual_mastering:
                self.log("[WARNING] Mastering display metadata (HDR10) was lost during merge!")
                self.log(f"         Lost data: {source_mastering}")
                issues += 1
            elif source_mastering and actual_mastering:
                # Check if values match
                for key in ['red_x', 'red_y', 'green_x', 'green_y', 'blue_x', 'blue_y',
                           'white_point_x', 'white_point_y', 'max_luminance', 'min_luminance']:
                    if source_mastering.get(key) != actual_mastering.get(key):
                        self.log(f"[WARNING] Mastering display {key} mismatch!")
                        issues += 1

            # Check content light level
            source_cll = self._get_content_light_level(source_video)
            actual_cll = self._get_content_light_level(actual_video)

            if source_cll and not actual_cll:
                self.log("[WARNING] Content light level metadata (MaxCLL/MaxFALL) was lost during merge!")
                self.log(f"         Lost data: MaxCLL={source_cll.get('max_content')}, MaxFALL={source_cll.get('max_average')}")
                issues += 1
            elif source_cll and actual_cll:
                if source_cll.get('max_content') != actual_cll.get('max_content') or \
                   source_cll.get('max_average') != actual_cll.get('max_average'):
                    self.log(f"[WARNING] Content light level mismatch! "
                            f"Source: MaxCLL={source_cll.get('max_content')}/MaxFALL={source_cll.get('max_average')}, "
                            f"Output: MaxCLL={actual_cll.get('max_content')}/MaxFALL={actual_cll.get('max_average')}")
                    issues += 1

        if issues == 0:
            self.log("✅ All video metadata preserved correctly.")

        return issues

    def _audit_dolby_vision(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """Detailed Dolby Vision metadata check."""
        issues = 0
        video_items = [item for item in plan_items if item.track.type == TrackType.VIDEO]

        for plan_item in video_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            source_video = next((s for s in source_data.get('streams', []) if s.get('codec_type') == 'video'), None)
            actual_video = next((s for s in actual_streams if s.get('codec_type') == 'video'), None)

            if not source_video or not actual_video:
                continue

            source_has_dv = self._has_dolby_vision(source_video)
            actual_has_dv = self._has_dolby_vision(actual_video)

            if source_has_dv and not actual_has_dv:
                self.log("[WARNING] Dolby Vision metadata was present in source but is MISSING from the output!")
                self.log("         This is a significant quality loss for compatible displays.")
                issues += 1
            elif source_has_dv and actual_has_dv:
                self.log("✅ Dolby Vision metadata preserved successfully.")

        if not any(self._has_dolby_vision(next((s for s in self._get_metadata(self.ctx.sources.get(item.track.source), 'ffprobe').get('streams', [])
                                               if s.get('codec_type') == 'video'), {}))
                  for item in video_items if item.track.type == TrackType.VIDEO and self.ctx.sources.get(item.track.source)):
            self.log("✅ No Dolby Vision metadata to preserve.")

        return issues

    def _audit_object_based_audio(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """Detailed object-based audio check."""
        issues = 0
        audio_items = [item for item in plan_items if item.track.type == TrackType.AUDIO]

        for plan_item in audio_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            # Find the matching audio stream in source
            source_audio_streams = [s for s in source_data.get('streams', []) if s.get('codec_type') == 'audio']
            if plan_item.track.id < len(source_audio_streams):
                source_audio = source_audio_streams[plan_item.track.id]
            else:
                continue

            # Find corresponding stream in output
            actual_audio_streams = [s for s in actual_streams if s.get('codec_type') == 'audio']
            actual_audio = None
            for i, item in enumerate([it for it in plan_items if it.track.type == TrackType.AUDIO]):
                if item == plan_item and i < len(actual_audio_streams):
                    actual_audio = actual_audio_streams[i]
                    break

            if not actual_audio:
                continue

            source_profile = source_audio.get('profile', '')
            actual_profile = actual_audio.get('profile', '')

            # Check for Atmos
            if 'Atmos' in source_profile and 'Atmos' not in actual_profile:
                self.log(f"[WARNING] Dolby Atmos metadata was lost for audio track from {plan_item.track.source}!")
                issues += 1
            elif 'Atmos' in source_profile and 'Atmos' in actual_profile:
                self.log(f"✅ Dolby Atmos preserved for track from {plan_item.track.source}.")

            # Check for DTS:X
            if 'DTS:X' in source_profile and 'DTS:X' not in actual_profile:
                self.log(f"[WARNING] DTS:X metadata was lost for audio track from {plan_item.track.source}!")
                issues += 1
            elif 'DTS:X' in source_profile and 'DTS:X' in actual_profile:
                self.log(f"✅ DTS:X preserved for track from {plan_item.track.source}.")

        if issues == 0:
            self.log("✅ All object-based audio metadata preserved correctly.")

        return issues

    def _get_mastering_display(self, stream: Dict) -> Optional[Dict]:
        """Extracts mastering display metadata from a stream."""
        for side_data in stream.get('side_data_list', []):
            if side_data.get('side_data_type') == 'Mastering display metadata':
                return side_data
        return None

    def _get_content_light_level(self, stream: Dict) -> Optional[Dict]:
        """Extracts content light level metadata from a stream."""
        for side_data in stream.get('side_data_list', []):
            if side_data.get('side_data_type') == 'Content light level metadata':
                return side_data
        return None

    def _audit_attachments(self, actual_attachments: List[Dict]):
        """Checks if expected attachments are present."""
        if not self.ctx.attachments:
            if not actual_attachments:
                self.log("✅ No attachments were planned or found.")
            else:
                self.log(f"[INFO] File contains {len(actual_attachments)} attachment(s) (likely from source files).")
            return

        expected_count = len(self.ctx.attachments)
        actual_count = len(actual_attachments)

        if actual_count < expected_count:
            self.log(f"[WARNING] Expected {expected_count} attachments but only found {actual_count}.")
            self.log("         Some fonts may be missing, which could affect subtitle rendering.")
        else:
            self.log(f"✅ Found {actual_count} attachment(s) as expected.")

    def _has_hdr_metadata(self, stream: Dict) -> bool:
        """Checks if a video stream has HDR metadata."""
        # Check for HDR transfer characteristics
        color_transfer = stream.get('color_transfer', '')
        if color_transfer in ['smpte2084', 'arib-std-b67']:
            return True

        # Check for HDR side data
        for side_data in stream.get('side_data_list', []):
            if side_data.get('side_data_type') in ['Mastering display metadata', 'Content light level metadata']:
                return True

        return False

    def _has_dolby_vision(self, stream: Dict) -> bool:
        """Checks if a video stream has Dolby Vision metadata."""
        for side_data in stream.get('side_data_list', []):
            if 'DOVI configuration' in side_data.get('side_data_type', ''):
                return True
        return False

    def _get_metadata(self, file_path: str, tool: str) -> Optional[Dict]:
        """Gets metadata using either mkvmerge or ffprobe with caching."""
        cache = self._source_mkvmerge_cache if tool == 'mkvmerge' else self._source_ffprobe_cache

        if file_path in cache:
            return cache[file_path]

        try:
            if tool == 'mkvmerge':
                cmd = ['mkvmerge', '-J', str(file_path)]
            elif tool == 'ffprobe':
                cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                       '-show_streams', '-show_format', str(file_path)]
            else:
                return None

            out = self.runner.run(cmd, self.tool_paths)
            result = json.loads(out) if out else None
            cache[file_path] = result
            return result
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to get {tool} metadata: {e}")
            cache[file_path] = None
            return None
