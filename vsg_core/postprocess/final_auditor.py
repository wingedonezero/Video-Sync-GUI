# vsg_core/postprocess/final_auditor.py
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from vsg_core.orchestrator.steps.context import Context
from vsg_core.io.runner import CommandRunner
from vsg_core.models.enums import TrackType
from vsg_core.models.jobs import PlanItem

# --- Helper functions for formatters ---
def _format_mastering_display(stream: Dict, temp_dir: Path) -> Optional[str]:
    md = next((s for s in stream.get('side_data_list', []) if s.get('side_data_type') == 'Mastering display metadata'), None)
    if not md or not all(k in md for k in ['red_x', 'green_x', 'blue_x', 'white_point_x', 'max_luminance']):
        return None
    return (f"G({md['green_x']},{md['green_y']})B({md['blue_x']},{md['blue_y']})R({md['red_x']},{md['red_y']})"
            f"WP({md['white_point_x']},{md['white_point_y']})L({md['max_luminance']},{md['min_luminance']})")

def _format_max_cll(stream: Dict, temp_dir: Path) -> Optional[str]:
    cll = next((s for s in stream.get('side_data_list', []) if s.get('side_data_type') == 'Content light level metadata'), None)
    if cll and 'max_content' in cll and 'max_average' in cll:
        return f"{cll['max_content']},{cll['max_average']}"
    return None

# --- Main "Blueprint" of all metadata fields we will check AND FIX ---
METADATA_CHECKS = [
    {'type': TrackType.VIDEO, 'tool': 'mkvmerge', 'source_keys': ['properties', 'field_order'], 'propedit_key': 'field-order', 'formatter': lambda val, path: str(int(val))},
    {'type': TrackType.VIDEO, 'tool': 'mkvmerge', 'source_keys': ['properties', 'stereo_mode'], 'propedit_key': 'stereo-mode', 'formatter': lambda val, path: str(int(val))},
    {'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': ['color_primaries'], 'propedit_key': 'colour-primaries', 'formatter': lambda val, path: val},
    {'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': ['color_transfer'], 'propedit_key': 'transfer-characteristics', 'formatter': lambda val, path: val},
    {'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': ['color_space'], 'propedit_key': 'matrix-coefficients', 'formatter': lambda val, path: val},
    {'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': [], 'propedit_key': 'mastering-display', 'formatter': _format_mastering_display},
    {'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': [], 'propedit_key': 'max-frame-light', 'formatter': _format_max_cll},
]

class FinalAuditor:
    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.tool_paths = ctx.tool_paths
        self.log = runner._log_message
        self._source_ffprobe_cache: Dict[str, Optional[Dict]] = {}
        self._source_mkvmerge_cache: Dict[str, Optional[Dict]] = {}

    def run(self, final_mkv_path: Path):
        final_mkvmerge_data = self._get_source_metadata(str(final_mkv_path), 'mkvmerge')
        if not final_mkvmerge_data or 'tracks' not in final_mkvmerge_data:
            self.log("[ERROR] Could not read metadata from final file. Aborting audit.")
            return

        final_tracks = final_mkvmerge_data.get('tracks', [])
        final_plan_items = self.ctx.extracted_items
        patch_commands: List[str] = []

        if len(final_tracks) != len(final_plan_items):
            self.log(f"[WARNING] Track count mismatch! Plan expected {len(final_plan_items)}, but final file has {len(final_tracks)}.")

        self.log("--- Auditing Track Flags (Default/Forced) ---")
        patch_commands.extend(self._audit_track_flags(final_tracks, final_plan_items))

        final_ffprobe_streams = self._get_source_metadata(str(final_mkv_path), 'ffprobe')
        if final_ffprobe_streams:
            self.log("--- Auditing Video Core Metadata (HDR, 3D, Color) ---")
            patch_commands.extend(self._audit_video_metadata(final_ffprobe_streams.get('streams', []), final_tracks, final_plan_items))
            self._audit_dolby_vision(final_ffprobe_streams.get('streams', []), final_plan_items)
            self._audit_object_based_audio(final_ffprobe_streams.get('streams', []), final_plan_items)

        self.log("--- Auditing Attachments ---")
        self._audit_attachments(final_mkvmerge_data.get('attachments', []))

        if not patch_commands:
            self.log("✅ Final audit passed. No patchable issues found.")
        else:
            self.log(f"Found {len(patch_commands) // 3} patchable discrepancies. Applying fixes...")
            full_command = ['mkvpropedit', str(final_mkv_path)] + patch_commands
            self.runner.run(full_command, self.tool_paths)

    def _audit_track_flags(self, actual_tracks: List[Dict], plan_items: List[PlanItem]) -> List[str]:
        commands = []
        for i, plan_item in enumerate(plan_items):
            if i >= len(actual_tracks): break
            mkv_track_id = i + 1
            actual_track = actual_tracks[i]

            expected_default = plan_item.is_default
            actual_default = actual_track['properties'].get('default_track', False)
            if expected_default != actual_default:
                self.log(f"  - Track {mkv_track_id}: Fixing Default flag (Plan: {expected_default}, Final: {actual_default})")
                commands.extend(['--edit', f'track:{mkv_track_id}', '--set', f"flag-default={'1' if expected_default else '0'}"])

            if plan_item.track.type == TrackType.SUBTITLES:
                expected_forced = plan_item.is_forced_display
                actual_forced = actual_track['properties'].get('forced_track', False)
                if expected_forced != actual_forced:
                    self.log(f"  - Track {mkv_track_id}: Fixing Forced flag (Plan: {expected_forced}, Final: {actual_forced})")
                    commands.extend(['--edit', f'track:{mkv_track_id}', '--set', f"flag-forced={'1' if expected_forced else '0'}"])
        return commands

    def _audit_video_metadata(self, actual_ffprobe: List[Dict], actual_mkvmerge: List[Dict], plan_items: List[PlanItem]) -> List[str]:
        commands = []
        video_items = [(i, item) for i, item in enumerate(plan_items) if item.track.type == TrackType.VIDEO]

        for video_track_idx, (mkv_track_idx, plan_item) in enumerate(video_items):
            mkv_prop_id = mkv_track_idx + 1
            for check in METADATA_CHECKS:
                if check['type'] != TrackType.VIDEO: continue

                tool = check['tool']
                source_data = self._get_source_metadata(plan_item.track.source, tool)
                if not source_data: continue
                source_streams = source_data.get('tracks' if tool == 'mkvmerge' else 'streams', [])

                source_stream = self._find_source_stream(source_streams, plan_item, tool)
                if not source_stream: continue

                actual_streams = actual_mkvmerge if tool == 'mkvmerge' else actual_ffprobe
                actual_stream = self._find_actual_stream_by_index(actual_streams, TrackType.VIDEO, video_track_idx)
                if not actual_stream: continue

                expected_val_source = self._get_nested_key(source_stream, check['source_keys']) if check['source_keys'] else source_stream
                if expected_val_source is None: continue

                expected_val = check['formatter'](expected_val_source, self.ctx.temp_dir)
                if expected_val is None: continue

                actual_val_source = self._get_nested_key(actual_stream, check['source_keys']) if check['source_keys'] else actual_stream
                actual_val = check['formatter'](actual_val_source, self.ctx.temp_dir)

                if str(expected_val) != str(actual_val):
                    self.log(f"  - Video Track {mkv_prop_id}: Patching '{check['propedit_key']}'")
                    commands.extend(['--edit', f'track:v{video_track_idx + 1}', '--set', f"{check['propedit_key']}={expected_val}"])
        return commands

    def _audit_attachments(self, actual_attachments: List[Dict]):
        if not self.ctx.attachments:
            self.log("✅ No attachments were planned. Check passed.")
            return
        expected_filenames = {Path(p).name for p in self.ctx.attachments}
        actual_filenames = {a['file_name'] for a in actual_attachments}
        missing = expected_filenames - actual_filenames
        if missing:
            for filename in missing:
                self.log(f"[WARNING] Attachment '{filename}' was planned but is MISSING from the final file.")
        else:
            self.log("✅ All planned attachments are present.")

    def _audit_dolby_vision(self, actual_streams: List[Dict], plan_items: List[PlanItem]):
        self.log("--- Auditing Dolby Vision Metadata ---")
        has_warned = False
        video_items = [(i, item) for i, item in enumerate(plan_items) if item.track.type == TrackType.VIDEO]
        for video_track_idx, (mkv_track_idx, plan_item) in enumerate(video_items):
            mkv_prop_id = mkv_track_idx + 1
            source_data = self._get_source_metadata(plan_item.track.source, 'ffprobe')
            if not source_data: continue
            source_stream = self._find_source_stream(source_data.get('streams', []), plan_item, 'ffprobe')
            if not source_stream: continue

            actual_stream = self._find_actual_stream_by_index(actual_streams, TrackType.VIDEO, video_track_idx)
            if not actual_stream: continue

            source_has_dv = any(s.get('side_data_type') == 'DOVI configuration record' for s in source_stream.get('side_data_list', []))
            actual_has_dv = any(s.get('side_data_type') == 'DOVI configuration record' for s in actual_stream.get('side_data_list', []))

            if source_has_dv and not actual_has_dv:
                self.log(f"[WARNING] Dolby Vision metadata was present in source for video track {mkv_prop_id} but appears MISSING from the final file.")
                has_warned = True
        if not has_warned:
            self.log("✅ Dolby Vision metadata check passed.")

    def _audit_object_based_audio(self, actual_streams: List[Dict], plan_items: List[PlanItem]):
        self.log("--- Auditing Object-Based Audio (Atmos/DTS:X) ---")
        has_warned = False
        audio_items = [(i, item) for i, item in enumerate(plan_items) if item.track.type == TrackType.AUDIO]
        def _has_object_audio(stream: Dict) -> Optional[str]:
            profile = stream.get('profile', '')
            if 'Atmos' in profile: return "Dolby Atmos"
            if 'DTS:X' in profile: return "DTS:X"
            return None

        for audio_track_idx, (mkv_track_idx, plan_item) in enumerate(audio_items):
            mkv_prop_id = mkv_track_idx + 1
            source_data = self._get_source_metadata(plan_item.track.source, 'ffprobe')
            if not source_data: continue
            source_stream = self._find_source_stream(source_data.get('streams', []), plan_item, 'ffprobe')
            if not source_stream: continue

            actual_stream = self._find_actual_stream_by_index(actual_streams, TrackType.AUDIO, audio_track_idx)
            if not actual_stream: continue

            source_format = _has_object_audio(source_stream)
            actual_format = _has_object_audio(actual_stream)

            if source_format and not actual_format:
                self.log(f"[WARNING] {source_format} metadata was present in source for audio track {mkv_prop_id} but appears MISSING from the final file.")
                has_warned = True
        if not has_warned:
            self.log("✅ Object-based audio check passed.")

    def _find_source_stream(self, source_streams: List[Dict], plan_item: PlanItem, tool: str) -> Optional[Dict]:
        if tool == 'mkvmerge':
            return next((s for s in source_streams if s.get('id') == plan_item.track.id), None)
        elif tool == 'ffprobe':
            type_streams = [s for s in source_streams if s.get('codec_type') == plan_item.track.type.value]
            track_idx_of_type = plan_item.track.id
            if track_idx_of_type < len(type_streams):
                return type_streams[track_idx_of_type]
        return None

    def _find_actual_stream_by_index(self, actual_streams: List[Dict], track_type: TrackType, type_index: int) -> Optional[Dict]:
        """Finds the Nth stream of a given type in ffprobe's output."""
        streams_of_type = [s for s in actual_streams if s.get('codec_type') == track_type.value]
        if type_index < len(streams_of_type):
            return streams_of_type[type_index]
        return None

    def _get_source_metadata(self, source_key_or_path: str, tool: str) -> Optional[Dict]:
        is_path = Path(source_key_or_path).is_file()
        cache = self._source_ffprobe_cache if tool == 'ffprobe' else self._source_mkvmerge_cache

        key = str(source_key_or_path)
        if key not in cache:
            path = Path(key) if is_path else self.ctx.sources.get(key)
            cache[key] = self._gather_metadata(path, tool) if path and Path(path).exists() else None
        return cache[key]

    def _gather_metadata(self, file_path: Path, tool: str) -> Optional[Dict]:
        try:
            if tool == 'mkvmerge': cmd = ['mkvmerge', '-J', str(file_path)]
            elif tool == 'ffprobe': cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format', str(file_path)]
            else: return None
            out = self.runner.run(cmd, self.tool_paths)
            return json.loads(out) if out else None
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to gather {tool} metadata from '{file_path.name}': {e}")
            return None

    def _get_nested_key(self, data: Dict, keys: List) -> Any:
        for key in keys:
            if isinstance(data, dict): data = data.get(key)
            elif isinstance(data, list) and isinstance(key, int) and len(data) > key: data = data[key]
            else: return None
        return data
