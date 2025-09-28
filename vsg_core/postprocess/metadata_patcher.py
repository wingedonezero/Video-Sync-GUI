# vsg_core/postprocess/metadata_patcher.py
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from vsg_core.orchestrator.steps.context import Context
from vsg_core.io.runner import CommandRunner
from vsg_core.models.enums import TrackType

# --- Helper functions for formatting complex metadata ---

def _format_mastering_display(stream: Dict, temp_dir: Path) -> Optional[str]:
    """Formats ffprobe's mastering display metadata for mkvpropedit."""
    md = next((s for s in stream.get('side_data_list', []) if s.get('side_data_type') == 'Mastering display metadata'), None)
    if not md or not all(k in md for k in ['red_x', 'green_x', 'blue_x', 'white_point_x', 'max_luminance']):
        return None

    return (
        f"G({md['green_x']},{md['green_y']})"
        f"B({md['blue_x']},{md['blue_y']})"
        f"R({md['red_x']},{md['red_y']})"
        f"WP({md['white_point_x']},{md['white_point_y']})"
        f"L({md['max_luminance']},{md['min_luminance']})"
    )

def _format_max_cll(stream: Dict, temp_dir: Path) -> Optional[str]:
    """Formats ffprobe's content light level metadata for mkvpropedit."""
    cll = next((s for s in stream.get('side_data_list', []) if s.get('side_data_type') == 'Content light level metadata'), None)
    if cll and 'max_content' in cll and 'max_average' in cll:
        return f"{cll['max_content']},{cll['max_average']}"
    return None

# --- Main "Blueprint" of all metadata fields we will check AND FIX ---

METADATA_CHECKS = [
    {
        'type': TrackType.VIDEO, 'tool': 'mkvmerge', 'source_keys': ['properties', 'field_order'],
        'propedit_key': 'field-order', 'formatter': lambda val, path: str(int(val)),
    },
    {
        'type': TrackType.VIDEO, 'tool': 'mkvmerge', 'source_keys': ['properties', 'stereo_mode'],
        'propedit_key': 'stereo-mode', 'formatter': lambda val, path: str(int(val)),
    },
    {
        'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': ['color_primaries'],
        'propedit_key': 'colour-primaries', 'formatter': lambda val, path: val,
    },
    {
        'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': ['color_transfer'],
        'propedit_key': 'transfer-characteristics', 'formatter': lambda val, path: val,
    },
    {
        'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': ['color_space'],
        'propedit_key': 'matrix-coefficients', 'formatter': lambda val, path: val,
    },
    {
        'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': [], # Special case
        'propedit_key': 'mastering-display', 'formatter': _format_mastering_display,
    },
    {
        'type': TrackType.VIDEO, 'tool': 'ffprobe', 'source_keys': [], # Special case
        'propedit_key': 'max-frame-light', 'formatter': _format_max_cll,
    },
]

class MetadataPatcher:
    """Audits and corrects metadata of a final MKV file against its sources."""

    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.tool_paths = ctx.tool_paths
        self.log = runner._log_message
        self._source_ffprobe_cache: Dict[str, List] = {}
        self._source_mkvmerge_cache: Dict[str, List] = {}

    def run(self, final_mkv_path: Path):
        """Main method to execute the validation and patch process."""
        final_ffprobe_streams = self._gather_metadata(final_mkv_path, 'ffprobe')
        final_mkvmerge_tracks = self._gather_metadata(final_mkv_path, 'mkvmerge')

        if not final_ffprobe_streams or not final_mkvmerge_tracks:
            self.log("[WARN] Could not read metadata from final file. Aborting patch.")
            return

        final_plan_items = [item for item in self.ctx.extracted_items if not item.is_preserved]
        patch_commands: List[str] = []

        for mkv_track_id, plan_item in enumerate(final_plan_items, 1):
            for check in METADATA_CHECKS:
                if check['type'] != plan_item.track.type:
                    continue
                # (Logic for standard fields remains the same)
                tool = check['tool']
                source_streams = self._get_source_metadata(plan_item.track.source, tool)
                source_stream = self._find_source_stream(source_streams, plan_item, tool)
                if not source_stream: continue

                actual_streams = final_ffprobe_streams if tool == 'ffprobe' else final_mkvmerge_tracks
                actual_stream = actual_streams[mkv_track_id - 1] if mkv_track_id <= len(actual_streams) else {}

                expected_val = check['formatter'](source_stream, self.ctx.temp_dir)
                if expected_val is None: continue

                actual_val = check['formatter'](actual_stream, self.ctx.temp_dir)

                if str(expected_val) != str(actual_val):
                    self.log(f"  - Track {mkv_track_id} ({plan_item.track.type.value}): Patching '{check['propedit_key']}'")
                    patch_commands.extend(['--edit', f'track:{mkv_track_id}', '--set', f"{check['propedit_key']}={expected_val}"])

        if not patch_commands:
            self.log("✅ Standard metadata validation passed. No patches needed.")
        else:
            self.log(f"Found {len(patch_commands) // 3} standard metadata discrepancies. Applying patches...")
            full_command = ['mkvpropedit', str(final_mkv_path)] + patch_commands
            self.runner.run(full_command, self.tool_paths)

        # --- New, separate "Warn-Only" check for Dolby Vision ---
        self._audit_dolby_vision(final_ffprobe_streams, final_plan_items)

    def _audit_dolby_vision(self, actual_streams: List[Dict], plan_items: List[Any]):
        """Performs a read-only check for Dolby Vision metadata consistency."""
        self.log("--- Auditing Dolby Vision Metadata ---")
        has_warned = False
        for mkv_track_id, plan_item in enumerate(plan_items, 1):
            if plan_item.track.type != TrackType.VIDEO:
                continue

            source_streams = self._get_source_metadata(plan_item.track.source, 'ffprobe')
            source_stream = self._find_source_stream(source_streams, plan_item, 'ffprobe')
            if not source_stream: continue

            actual_stream = actual_streams[mkv_track_id - 1] if mkv_track_id <= len(actual_streams) else {}

            source_has_dv = any(s.get('side_data_type') == 'DOVI configuration record' for s in source_stream.get('side_data_list', []))
            actual_has_dv = any(s.get('side_data_type') == 'DOVI configuration record' for s in actual_stream.get('side_data_list', []))

            if source_has_dv and not actual_has_dv:
                self.log(f"[WARNING] Dolby Vision metadata was present in the source for video track {mkv_track_id} but appears to be MISSING from the final file.")
                has_warned = True

        if not has_warned:
            self.log("✅ Dolby Vision metadata check passed (or was not present in source).")

    def _find_source_stream(self, source_streams: List[Dict], plan_item: Any, tool: str) -> Optional[Dict]:
        """Finds the corresponding stream in the source metadata for a given PlanItem."""
        if tool == 'mkvmerge':
            return next((s for s in source_streams if s.get('id') == plan_item.track.id), None)
        elif tool == 'ffprobe':
            # This is a simplification; it assumes ffprobe stream order matches mkvmerge track order for a given type
            type_streams = [s for s in source_streams if s.get('codec_type') == plan_item.track.type.value]
            source_track_num = plan_item.track.id # This is the mkvmerge track ID, which is 0-indexed for its type
            if source_track_num < len(type_streams):
                return type_streams[source_track_num]
        return None

    def _get_source_metadata(self, source_key: str, tool: str) -> List[Dict]:
        """Caches and returns metadata for a source file using the specified tool."""
        cache = self._source_ffprobe_cache if tool == 'ffprobe' else self._source_mkvmerge_cache
        if source_key not in cache:
            source_path = self.ctx.sources.get(source_key)
            cache[source_key] = self._gather_metadata(Path(source_path), tool) if source_path else []
        return cache[source_key]

    def _gather_metadata(self, file_path: Path, tool: str) -> List[Dict]:
        """Runs the specified tool and returns its structured output."""
        try:
            if tool == 'mkvmerge':
                cmd = ['mkvmerge', '-J', str(file_path)]
                key = 'tracks'
            elif tool == 'ffprobe':
                cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(file_path)]
                key = 'streams'
            else: return []
            out = self.runner.run(cmd, self.tool_paths)
            return json.loads(out).get(key, []) if out else []
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to gather {tool} metadata from '{file_path.name}': {e}")
            return []

    def _get_nested_key(self, data: Dict, keys: List) -> Any:
        """Accesses a nested key within a dictionary."""
        for key in keys:
            if isinstance(data, dict): data = data.get(key)
            elif isinstance(data, list) and isinstance(key, int) and len(data) > key: data = data[key]
            else: return None
        return data
