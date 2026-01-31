from pathlib import Path

from ..io.runner import CommandRunner


def convert_srt_to_ass(subtitle_path: str, runner: CommandRunner, tool_paths: dict) -> str:
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() != '.srt':
        return subtitle_path
    output_path = sub_path.with_suffix('.ass')
    runner._log_message(f'[SubConvert] Converting {sub_path.name} to ASS format...')
    cmd = [tool_paths.get('ffmpeg', 'ffmpeg'), '-y', '-i', str(sub_path), str(output_path)]
    runner.run(cmd, tool_paths)
    return str(output_path) if output_path.exists() else subtitle_path
