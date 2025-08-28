# vsg_core/subtitle_utils.py

# -*- coding: utf-8 -*-
"""
Utilities for advanced subtitle processing, including conversion, rescaling,
and style modification.
"""
import json
import re
from pathlib import Path

from .process import CommandRunner

def convert_srt_to_ass(subtitle_path: str, runner: CommandRunner, tool_paths: dict) -> str:
    # ... (This function is unchanged)
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() != '.srt':
        return subtitle_path
    output_path = sub_path.with_suffix('.ass')
    runner._log_message(f'[SubConvert] Converting {sub_path.name} to ASS format...')
    ffmpeg_path = tool_paths.get('ffmpeg', 'ffmpeg')
    cmd = [ffmpeg_path, '-y', '-i', str(sub_path), str(output_path)]
    runner.run(cmd, tool_paths)
    if output_path.exists():
        return str(output_path)
    else:
        runner._log_message(f'[SubConvert] WARN: Failed to convert {sub_path.name}.')
        return subtitle_path


def rescale_subtitle(subtitle_path: str, video_path: str, runner: CommandRunner, tool_paths: dict) -> bool:
    # ... (This function is unchanged)
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() not in ['.ass', '.ssa']:
        return False
    ffprobe_path = tool_paths.get('ffprobe', 'ffprobe')
    cmd = [
        ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'json', str(video_path)
    ]
    out = runner.run(cmd, tool_paths)
    if not out:
        runner._log_message(f'[Rescale] WARN: Could not get video resolution for {Path(video_path).name}.')
        return False
    try:
        video_info = json.loads(out)['streams'][0]
        vid_w, vid_h = int(video_info['width']), int(video_info['height'])
    except (json.JSONDecodeError, IndexError, KeyError, ValueError):
        runner._log_message(f'[Rescale] WARN: Failed to parse video resolution.')
        return False
    try:
        content = sub_path.read_text(encoding='utf-8')
        playresx_match = re.search(r'^\s*PlayResX:\s*(\d+)', content, re.MULTILINE)
        playresy_match = re.search(r'^\s*PlayResY:\s*(\d+)', content, re.MULTILINE)
        if not playresx_match or not playresy_match:
            runner._log_message(f'[Rescale] INFO: {sub_path.name} has no PlayResX/Y tags.')
            return False
        sub_w, sub_h = int(playresx_match.group(1)), int(playresy_match.group(1))
        if (sub_w, sub_h) == (vid_w, vid_h):
            runner._log_message(f'[Rescale] INFO: {sub_path.name} already matches video resolution ({vid_w}x{vid_h}).')
            return False
        runner._log_message(f'[Rescale] Rescaling {sub_path.name} from {sub_w}x{sub_h} to {vid_w}x{vid_h}.')
        content = re.sub(r'(^\s*PlayResX:\s*)(\d+)', f'\\g<1>{vid_w}', content, flags=re.MULTILINE)
        content = re.sub(r'(^\s*PlayResY:\s*)(\d+)', f'\\g<1>{vid_h}', content, flags=re.MULTILINE)
        sub_path.write_text(content, encoding='utf-8')
        return True
    except Exception as e:
        runner._log_message(f'[Rescale] ERROR: Could not process {sub_path.name}: {e}')
        return False

def multiply_font_size(subtitle_path: str, multiplier: float, runner: CommandRunner) -> bool:
    """
    Multiplies the font size in an ASS/SSA subtitle file's style definitions.
    This version parses line by line to avoid corrupting the file.
    """
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() not in ['.ass', '.ssa'] or multiplier == 1.0:
        return False

    runner._log_message(f'[Font Size] Applying {multiplier:.2f}x size multiplier to {sub_path.name}.')
    try:
        # Use utf-8-sig to correctly handle potential BOM from ffmpeg
        lines = sub_path.read_text(encoding='utf-8-sig').splitlines()
        new_lines = []
        modified_count = 0

        for line in lines:
            if line.strip().lower().startswith('style:'):
                parts = line.split(',', 3) # Format: Style: Name,Fontname,Fontsize,PrimaryColour...
                if len(parts) >= 4:
                    try:
                        style_prefix = f"{parts[0]},{parts[1]}" # e.g., "Style: Default,Arial"
                        original_size = float(parts[2])
                        style_suffix = parts[3]

                        new_size = int(round(original_size * multiplier))
                        new_lines.append(f"{style_prefix},{new_size},{style_suffix}")
                        modified_count += 1
                        continue # Skip to next line
                    except (ValueError, IndexError):
                        pass # Fallback to appending original line if parsing fails

            new_lines.append(line)

        if modified_count > 0:
            # Rejoin and write back with standard utf-8
            sub_path.write_text('\n'.join(new_lines), encoding='utf-8')
            runner._log_message(f'[Font Size] Modified {modified_count} style definition(s).')
            return True
        else:
            runner._log_message(f'[Font Size] WARN: No style definitions found to modify in {sub_path.name}.')
            return False

    except Exception as e:
        runner._log_message(f'[Font Size] ERROR: Could not process {sub_path.name}: {e}')
        return False
