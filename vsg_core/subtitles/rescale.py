# vsg_core/subtitles/rescale.py
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path
import pysubs2
from ..io.runner import CommandRunner

def _scale_override_tags(text: str, scale_w: float, scale_h: float) -> str:
    """
    Scales all ASS override tags in subtitle text to match Aegisub's behavior.
    X coordinates scale by scale_w, Y coordinates by scale_h.
    """

    def scale_value(val: str, scale_factor: float) -> str:
        """Scale a numeric value and format it cleanly."""
        try:
            scaled = float(val) * scale_factor
            return f"{scaled:.3f}".rstrip('0').rstrip('.')
        except ValueError:
            return val

    def scale_tag(tag_name: str, args: str) -> str:
        """Scale tag arguments based on tag type."""
        if not args:
            return args

        tag_lower = tag_name.lower()
        parts = [p.strip() for p in args.split(',')]
        scaled_parts = []

        for i, part in enumerate(parts):
            # Tags that scale with WIDTH only
            if tag_lower in ('fscx', 'bord', 'xbord'):
                scaled_parts.append(scale_value(part, scale_w))

            # Tags that scale with HEIGHT only
            elif tag_lower in ('fscy', 'ybord', 'yshad', 'fs', 'blur', 'pbo', 'shad'):
                scaled_parts.append(scale_value(part, scale_h))

            # Tags with (x, y) pairs
            elif tag_lower in ('pos', 'org', 'clip') and i < 2:
                scaled_parts.append(scale_value(part, scale_w if i == 0 else scale_h))

            # move tag: (x1, y1, x2, y2, t1, t2)
            elif tag_lower == 'move':
                if i == 0 or i == 2:
                    scaled_parts.append(scale_value(part, scale_w))
                elif i == 1 or i == 3:
                    scaled_parts.append(scale_value(part, scale_h))
                else:
                    scaled_parts.append(part)

            # DON'T scale: time values, edge blur, rotations, shearing, factors
            else:
                scaled_parts.append(part)

        return ','.join(scaled_parts)

    def process_override_block(block_content: str) -> str:
        """Process all tags within a single {...} block."""
        # Match tags in format: \tag, \tag(args), or \tag123 (shorthand with number)
        tag_pattern = re.compile(r'\\([a-zA-Z]+)(\([^)]*\)|(?:\-?\d+(?:\.\d+)?))?')

        def replace_tag(match):
            tag_name = match.group(1)
            tag_lower = tag_name.lower()
            args_or_value = match.group(2)

            if args_or_value is None:
                # Tag with no args or value (like \i or \b by itself)
                return match.group(0)

            elif args_or_value.startswith('('):
                # Tag with parentheses: \tag(args)
                args = args_or_value[1:-1]  # Strip parentheses
                scaled_args = scale_tag(tag_name, args)
                return f'\\{tag_name}({scaled_args})'

            else:
                # Shorthand format: \blur2, \fs50, etc.
                value = args_or_value

                # Check if this tag type should be scaled
                if tag_lower in ('fs', 'blur', 'fscy', 'ybord', 'yshad', 'pbo', 'shad'):
                    scaled = scale_value(value, scale_h)
                    return f'\\{tag_name}{scaled}'
                elif tag_lower in ('fscx', 'bord', 'xbord'):
                    scaled = scale_value(value, scale_w)
                    return f'\\{tag_name}{scaled}'
                else:
                    # Don't scale: \be, \fax, \fay, \frx, \fry, \frz, \b, \i, \an, etc.
                    return match.group(0)

        return tag_pattern.sub(replace_tag, block_content)

    # Process each {...} block in the text
    def replace_block(match):
        block_content = match.group(1)
        scaled_content = process_override_block(block_content)
        return '{' + scaled_content + '}'

    return re.sub(r'\{([^}]*)\}', replace_block, text)


def rescale_subtitle(subtitle_path: str, video_path: str, runner: CommandRunner, tool_paths: dict) -> bool:
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() not in ['.ass', '.ssa']:
        return False

    # 1. Get target video resolution
    out = runner.run([
        tool_paths.get('ffprobe', 'ffprobe'), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'json', str(video_path)
    ], tool_paths)
    if not out:
        runner._log_message(f'[Rescale] WARN: Could not get video resolution for {Path(video_path).name}.')
        return False

    try:
        video_info = json.loads(out)['streams'][0]
        to_w, to_h = int(video_info['width']), int(video_info['height'])
    except Exception:
        runner._log_message(f'[Rescale] WARN: Failed to parse video resolution.')
        return False

    # 2. Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
        from_w = int(subs.info.get('PlayResX', 0))
        from_h = int(subs.info.get('PlayResY', 0))

        if from_w == 0 or from_h == 0:
            runner._log_message(f'[Rescale] INFO: {sub_path.name} has no PlayResX/Y tags to rescale.')
            return False

        if (from_w, from_h) == (to_w, to_h):
            runner._log_message(f'[Rescale] INFO: {sub_path.name} already matches video resolution ({to_w}x{to_h}).')
            return False

        # 3. Calculate scaling factors
        scale_w = to_w / from_w
        scale_h = to_h / from_h

        runner._log_message(f'[Rescale] Rescaling {sub_path.name} from {from_w}x{from_h} to {to_w}x{to_h} (W×{scale_w:.4f}, H×{scale_h:.4f}).')

        # 4. Update Script Info
        subs.info['PlayResX'] = str(to_w)
        subs.info['PlayResY'] = str(to_h)

        # 5. Scale all Style definitions
        for style in subs.styles.values():
            style.fontsize = int(style.fontsize * scale_h + 0.5)  # Round to nearest
            style.outline *= scale_h
            style.shadow *= scale_h
            style.marginl = int(style.marginl * scale_w + 0.5)
            style.marginr = int(style.marginr * scale_w + 0.5)
            style.marginv = int(style.marginv * scale_h + 0.5)

        # 6. Scale all inline override tags for every event
        for line in subs:
            line.text = _scale_override_tags(line.text, scale_w, scale_h)

        # 7. Save the rescaled subtitle file
        subs.save(subtitle_path, encoding='utf-8')

        runner._log_message(f'[Rescale] Successfully rescaled to {to_w}x{to_h}.')
        return True

    except Exception as e:
        runner._log_message(f'[Rescale] ERROR: Could not process {sub_path.name}: {e}')
        import traceback
        runner._log_message(f'[Rescale] Traceback: {traceback.format_exc()}')
        return False
