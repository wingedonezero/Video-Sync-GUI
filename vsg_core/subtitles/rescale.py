# vsg_core/subtitles/rescale.py
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path
import pysubs2
from ..io.runner import CommandRunner

def _scale_override_tags(text: str, scale_w: float, scale_h: float) -> str:
    """
    Parses a subtitle line's text and scales all ASS override tags,
    replicating Aegisub's comprehensive scaling logic.
    """
    # This regex is designed to find all valid ASS tags.
    # It correctly handles tags with and without parentheses.
    tag_pattern = re.compile(r"\\([a-zA-Z]+)(?:\(((?:[^()]*|\([^)]*\))*)\))?")

    def scale_args(tag, args_str):
        if args_str is None:
            # Handle tags without arguments or with implicit numeric values (eg. \blur2)
            try:
                # Attempt to extract a numeric value directly after the tag
                implicit_val_match = re.match(r"(\d+(?:\.\d+)?)", tag[len(match.group(1)):])
                if implicit_val_match:
                    val = float(implicit_val_match.group(1))
                    if tag.lower() in ('fs', 'blur', 'be'):
                        return f"{val * scale_h:.3f}".rstrip('0').rstrip('.')
                return None # No scalable value
            except (ValueError, TypeError):
                return None

        # Tags with explicit arguments inside parentheses
        args = [a.strip() for a in args_str.split(',')]
        scaled_args = []

        tag_lower = tag.lower()

        for i, arg in enumerate(args):
            try:
                val = float(arg)
                # Apply scaling based on tag type (X, Y, or both)
                if tag_lower in ('fscx', 'bord', 'xbord', 'shad', 'xshad', 'fax', 'frx', 'fax'):
                    scaled_args.append(f"{val * scale_w:.3f}".rstrip('0').rstrip('.'))
                elif tag_lower in ('fscy', 'ybord', 'yshad', 'fay', 'fry', 'fay'):
                    scaled_args.append(f"{val * scale_h:.3f}".rstrip('0').rstrip('.'))
                elif tag_lower in ('fs', 'be', 'blur'): # Fontsize and blurs scale with height
                    scaled_args.append(f"{val * scale_h:.3f}".rstrip('0').rstrip('.'))
                elif tag_lower in ('pos', 'org'): # (x, y)
                    scaled_args.append(f"{val * (scale_w if i % 2 == 0 else scale_h):.3f}".rstrip('0').rstrip('.'))
                elif tag_lower == 'move': # (x1, y1, x2, y2, t1, t2)
                    if i in [0, 2]:
                        scaled_args.append(f"{val * scale_w:.3f}".rstrip('0').rstrip('.'))
                    elif i in [1, 3]:
                        scaled_args.append(f"{val * scale_h:.3f}".rstrip('0').rstrip('.'))
                    else: # t1, t2 are not scaled
                        scaled_args.append(arg)
                elif tag_lower == 'pbo': # Baseline offset
                     scaled_args.append(f"{val * scale_h:.0f}")
                else:
                    scaled_args.append(arg)
            except ValueError:
                scaled_args.append(arg)

        return ",".join(scaled_args)


    def replacer(match):
        full_tag, tag, args_str = match.groups()

        # Handle simple tags like \b1, \i1 etc. that have a single digit
        if args_str is None and re.match(r'^\d+(\.\d+)?$', tag[len(match.group(1)):]):
             val_str = tag[len(match.group(1)):]
             try:
                 val = float(val_str)
                 scaled_val = None
                 if match.group(1).lower() in ('fs', 'blur', 'be'):
                     scaled_val = f"{val * scale_h:.3f}".rstrip('0').rstrip('.')

                 if scaled_val is not None:
                     return f"\\{match.group(1)}{scaled_val}"
             except ValueError:
                 pass


        scaled_args = scale_args(tag, args_str)

        if scaled_args is not None:
            return f"\\{tag}({scaled_args})"
        else:
            return f"\\{full_tag}" # Return original tag if no scaling was applied


    # Find all {...} blocks and apply the replacer to their contents
    return re.sub(r"\{([^}]*)\}", lambda m: "{" + tag_pattern.sub(
        lambda match: f"\\{match.group(1)}({scale_args(match.group(1), match.group(2))})" if match.group(2) is not None else (f"\\{match.group(1)}{scale_args(match.group(1), None)}" if scale_args(match.group(1), None) is not None else f"\\{match.group(1)}"),
        m.group(1)) + "}", text)



def rescale_subtitle(subtitle_path: str, video_path: str, runner: CommandRunner, tool_paths: dict) -> bool:
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() not in ['.ass', '.ssa']:
        return False

    # 1. Get target video resolution from Source 1
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

    # 2. Load subtitle file with pysubs2 and get its current resolution
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

        runner._log_message(f'[Rescale] Rescaling {sub_path.name} from {from_w}x{from_h} to {to_w}x{to_h} (Wx{scale_w:.3f}, Hx{scale_h:.3f}).')

        # 4. Update Script Info
        subs.info['PlayResX'] = str(to_w)
        subs.info['PlayResY'] = str(to_h)

        # 5. Scale all Style definitions
        for style in subs.styles.values():
            style.fontsize *= scale_h
            style.outline *= scale_h
            style.shadow *= scale_h
            style.marginl = int(style.marginl * scale_w)
            style.marginr = int(style.marginr * scale_w)
            style.marginv = int(style.marginv * scale_h)

        # 6. Scale all inline override tags for every event
        for line in subs:
            line.text = _scale_override_tags(line.text, scale_w, scale_h)

        # 7. Save the fully rescaled subtitle file
        subs.save(subtitle_path, encoding='utf-8')

        runner._log_message(f'[Rescale] Successfully rescaled resolution, styles, and all inline tags.')
        return True

    except Exception as e:
        runner._log_message(f'[Rescale] ERROR: Could not process {sub_path.name}: {e}')
        # Log traceback for debugging if available
        import traceback
        runner._log_message(f'[Rescale] Traceback: {traceback.format_exc()}')
        return False
