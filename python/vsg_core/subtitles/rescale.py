# vsg_core/subtitles/rescale.py
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path
import pysubs2
from ..io.runner import CommandRunner
from .metadata_preserver import SubtitleMetadata

def _scale_override_tags(text: str, scale: float, scale_h: float, offset_x: float, offset_y: float) -> str:
    """
    Scales all ASS override tags using uniform scaling and adds border offsets.
    Maintains aspect ratio like Aegisub's "Add Borders" resampling.
    Uses vertical scaling (scale_h) for font sizes to match Aegisub behavior.
    """

    def scale_value(val: str, scale_factor: float, offset: float = 0) -> str:
        """Scale a numeric value, add offset, and format cleanly."""
        try:
            scaled = float(val) * scale_factor + offset
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
            # Width/X measurements (no offset needed for size measurements)
            if tag_lower in ('fscx', 'bord', 'xbord'):
                scaled_parts.append(scale_value(part, scale))

            # Height/Y measurements and font size (use vertical scaling, no offset for size measurements)
            elif tag_lower in ('fscy', 'ybord', 'yshad', 'fs', 'blur', 'pbo', 'shad'):
                scaled_parts.append(scale_value(part, scale_h))

            # Position tags (x, y) - need offsets
            elif tag_lower in ('pos', 'org') and i < 2:
                offset = offset_x if i == 0 else offset_y
                scaled_parts.append(scale_value(part, scale, offset))

            # Clip rectangles - need offsets
            elif tag_lower == 'clip' and i < 4:
                offset = offset_x if i in [0, 2] else offset_y
                scaled_parts.append(scale_value(part, scale, offset))

            # move tag: (x1, y1, x2, y2, t1, t2) - positions need offsets
            elif tag_lower == 'move':
                if i in [0, 2]:  # x coordinates
                    scaled_parts.append(scale_value(part, scale, offset_x))
                elif i in [1, 3]:  # y coordinates
                    scaled_parts.append(scale_value(part, scale, offset_y))
                else:  # time values
                    scaled_parts.append(part)

            # Time-based tags, factors, coefficients - don't scale
            else:
                scaled_parts.append(part)

        return ','.join(scaled_parts)

    def process_override_block(block_content: str) -> str:
        """Process all tags within a single {...} block."""
        tag_pattern = re.compile(r'\\([a-zA-Z]+)(\([^)]*\)|(?:\-?\d+(?:\.\d+)?))?')

        def replace_tag(match):
            tag_name = match.group(1)
            tag_lower = tag_name.lower()
            args_or_value = match.group(2)

            if args_or_value is None:
                return match.group(0)

            elif args_or_value.startswith('('):
                # Tag with parentheses
                args = args_or_value[1:-1]
                scaled_args = scale_tag(tag_name, args)
                return f'\\{tag_name}({scaled_args})'

            else:
                # Shorthand format
                value = args_or_value

                # Scale size measurements (use vertical scaling for font/outline/shadow)
                if tag_lower in ('fs', 'blur', 'fscy', 'ybord', 'yshad', 'pbo', 'shad'):
                    scaled = scale_value(value, scale_h)
                    return f'\\{tag_name}{scaled}'
                elif tag_lower in ('fscx', 'bord', 'xbord'):
                    scaled = scale_value(value, scale)
                    return f'\\{tag_name}{scaled}'
                else:
                    return match.group(0)

        return tag_pattern.sub(replace_tag, block_content)

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

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

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

        # 3. Calculate uniform scaling factor (Aegisub "Add Borders" style)
        scale_w = to_w / from_w
        scale_h = to_h / from_h
        scale = min(scale_w, scale_h)  # Use smaller ratio to maintain aspect ratio

        # 4. Calculate effective size and border offsets
        new_w = int(from_w * scale + 0.5)
        new_h = int(from_h * scale + 0.5)
        offset_x = (to_w - new_w) / 2
        offset_y = (to_h - new_h) / 2

        runner._log_message(
            f'[Rescale] Rescaling {sub_path.name} from {from_w}x{from_h} to {to_w}x{to_h} '
            f'(uniform scale: {scale:.4f}, font scale: {scale_h:.4f}, borders: {offset_x:.1f}x, {offset_y:.1f}y).'
        )

        # 5. Update Script Info
        subs.info['PlayResX'] = str(to_w)
        subs.info['PlayResY'] = str(to_h)

        # 6. Scale all Style definitions (margins scale without offsets as they're edge-relative)
        for style in subs.styles.values():
            # Use vertical scaling for font size (Aegisub convention)
            style.fontsize = int(style.fontsize * scale_h + 0.5)
            style.outline *= scale_h
            style.shadow *= scale_h
            # Margins are edge-relative, so they scale without offsets
            # (offsets only apply to absolute coordinates like \pos tags)
            style.marginl = int(style.marginl * scale + 0.5)
            style.marginr = int(style.marginr * scale + 0.5)
            style.marginv = int(style.marginv * scale + 0.5)

        # 7. Scale all inline override tags with offsets
        for line in subs:
            line.text = _scale_override_tags(line.text, scale, scale_h, offset_x, offset_y)

        # 8. Save the rescaled subtitle file
        subs.save(subtitle_path, encoding='utf-8')

        # Validate and restore lost metadata
        metadata.validate_and_restore(runner)

        runner._log_message(f'[Rescale] Successfully rescaled to {to_w}x{to_h}.')
        return True

    except Exception as e:
        runner._log_message(f'[Rescale] ERROR: Could not process {sub_path.name}: {e}')
        import traceback
        runner._log_message(f'[Rescale] Traceback: {traceback.format_exc()}')
        return False
