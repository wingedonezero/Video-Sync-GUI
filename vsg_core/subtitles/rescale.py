# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
from ..io.runner import CommandRunner

def rescale_subtitle(subtitle_path: str, video_path: str, runner: CommandRunner, tool_paths: dict) -> bool:
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() not in ['.ass', '.ssa']:
        return False
    out = runner.run([
        tool_paths.get('ffprobe', 'ffprobe'), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'json', str(video_path)
    ], tool_paths)
    if not out:
        runner._log_message(f'[Rescale] WARN: Could not get video resolution for {Path(video_path).name}.')
        return False
    try:
        video_info = json.loads(out)['streams'][0]
        vid_w, vid_h = int(video_info['width']), int(video_info['height'])
    except Exception:
        runner._log_message(f'[Rescale] WARN: Failed to parse video resolution.')
        return False

    try:
        content = sub_path.read_text(encoding='utf-8')
        rx = re.search(r'^\s*PlayResX:\s*(\d+)', content, re.MULTILINE)
        ry = re.search(r'^\s*PlayResY:\s*(\d+)', content, re.MULTILINE)
        if not rx or not ry:
            runner._log_message(f'[Rescale] INFO: {sub_path.name} has no PlayResX/Y tags.')
            return False
        sub_w, sub_h = int(rx.group(1)), int(ry.group(1))
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
