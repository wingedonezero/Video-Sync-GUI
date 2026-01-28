# vsg_core/subtitles/operations/style_ops.py
# -*- coding: utf-8 -*-
"""
Style operations for SubtitleData.

Operations:
- apply_style_patch: Apply attribute changes to styles
- apply_font_replacement: Replace font names
- apply_size_multiplier: Scale font sizes
- apply_rescale: Rescale to target resolution (Aegisub "Add Borders" style)
- apply_style_filter: Filter events by style name (include/exclude)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Tuple, TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord


def _scale_override_tags(text: str, scale: float, scale_h: float, offset_x: float, offset_y: float) -> str:
    """
    Scales all ASS override tags using uniform scaling and adds border offsets.
    Maintains aspect ratio like Aegisub's "Add Borders" resampling.
    Uses vertical scaling (scale_h) for font sizes to match Aegisub behavior.

    Args:
        text: Event text with ASS override tags
        scale: Uniform scale factor (min of scale_x, scale_y)
        scale_h: Vertical scale factor for font/outline/shadow
        offset_x: Horizontal border offset for position tags
        offset_y: Vertical border offset for position tags

    Returns:
        Text with scaled override tags
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
                pos_offset = offset_x if i == 0 else offset_y
                scaled_parts.append(scale_value(part, scale, pos_offset))

            # Clip rectangles - need offsets
            elif tag_lower == 'clip' and i < 4:
                clip_offset = offset_x if i in [0, 2] else offset_y
                scaled_parts.append(scale_value(part, scale, clip_offset))

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


# Color attributes that need Qt->ASS conversion
_COLOR_ATTRIBUTES = {
    'primary_color', 'secondary_color', 'outline_color', 'back_color'
}

# Bool attributes that need bool->int conversion (-1 for True, 0 for False)
_BOOL_ATTRIBUTES = {
    'bold', 'italic', 'underline', 'strike_out'
}


def _convert_patch_value(attr_name: str, value: Any) -> Any:
    """
    Convert patch values to SubtitleStyle-compatible format.

    Handles:
    - Color: Qt #AARRGGBB -> ASS &HAABBGGRR
    - Bool: True/False -> -1/0
    """
    if attr_name in _COLOR_ATTRIBUTES:
        # Import here to avoid circular dependency
        from ..style_engine import qt_color_to_ass
        if isinstance(value, str) and value.startswith('#'):
            return qt_color_to_ass(value)
        return value

    if attr_name in _BOOL_ATTRIBUTES:
        if isinstance(value, bool):
            return -1 if value else 0
        return value

    return value


def apply_style_patch(
    data: 'SubtitleData',
    patches: Dict[str, Dict[str, Any]],
    runner=None
) -> 'OperationResult':
    """
    Apply attribute patches to styles.

    Args:
        data: SubtitleData to modify
        patches: Dict of style_name -> {attribute: value}
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationResult, OperationRecord

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    if not patches:
        return OperationResult(
            success=True,
            operation='style_patch',
            summary='No patches provided'
        )

    styles_affected = 0
    changes = []

    for style_name, attributes in patches.items():
        if style_name not in data.styles:
            log(f"[StylePatch] WARNING: Style '{style_name}' not found")
            continue

        style = data.styles[style_name]

        for attr, value in attributes.items():
            # Map common attribute names to SubtitleStyle field names
            attr_name = _map_style_attribute(attr)

            if hasattr(style, attr_name):
                old_value = getattr(style, attr_name)
                # Convert value to SubtitleStyle-compatible format
                converted_value = _convert_patch_value(attr_name, value)
                setattr(style, attr_name, converted_value)
                changes.append(f"{style_name}.{attr_name}: {old_value} -> {converted_value}")
            else:
                log(f"[StylePatch] WARNING: Unknown attribute '{attr}' for style '{style_name}'")

        styles_affected += 1

    # Record operation
    record = OperationRecord(
        operation='style_patch',
        timestamp=datetime.now(),
        parameters={'patches': {k: list(v.keys()) for k, v in patches.items()}},
        styles_affected=styles_affected,
        summary=f"Patched {styles_affected} style(s)"
    )
    data.operations.append(record)

    log(f"[StylePatch] Applied {len(changes)} change(s) to {styles_affected} style(s)")

    return OperationResult(
        success=True,
        operation='style_patch',
        styles_affected=styles_affected,
        summary=record.summary,
        details={'changes': changes}
    )


def apply_font_replacement(
    data: 'SubtitleData',
    replacements: Dict[str, str],
    runner=None
) -> 'OperationResult':
    """
    Replace font names in styles.

    Args:
        data: SubtitleData to modify
        replacements: Dict of old_font -> new_font
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationResult, OperationRecord

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    if not replacements:
        return OperationResult(
            success=True,
            operation='font_replacement',
            summary='No replacements provided'
        )

    styles_affected = 0
    changes = []

    for style in data.styles.values():
        old_font = style.fontname
        if old_font in replacements:
            new_font = replacements[old_font]
            style.fontname = new_font
            changes.append(f"{style.name}: {old_font} -> {new_font}")
            styles_affected += 1

    # Record operation
    record = OperationRecord(
        operation='font_replacement',
        timestamp=datetime.now(),
        parameters={'replacements': replacements},
        styles_affected=styles_affected,
        summary=f"Replaced fonts in {styles_affected} style(s)"
    )
    data.operations.append(record)

    log(f"[FontReplacement] Replaced {styles_affected} font(s)")

    return OperationResult(
        success=True,
        operation='font_replacement',
        styles_affected=styles_affected,
        summary=record.summary,
        details={'changes': changes}
    )


def apply_size_multiplier(
    data: 'SubtitleData',
    multiplier: float,
    runner=None
) -> 'OperationResult':
    """
    Apply font size multiplier to all styles.

    Args:
        data: SubtitleData to modify
        multiplier: Size multiplier (e.g., 1.2 for 20% increase)
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationResult, OperationRecord

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    # Skip if multiplier is effectively 1.0
    if abs(multiplier - 1.0) < 1e-6:
        return OperationResult(
            success=True,
            operation='size_multiplier',
            summary='Multiplier is 1.0, no changes'
        )

    # Validate range
    if not (0.1 <= multiplier <= 10.0):
        return OperationResult(
            success=False,
            operation='size_multiplier',
            error=f"Multiplier {multiplier} out of range (0.1-10.0)"
        )

    styles_affected = 0
    changes = []

    for style in data.styles.values():
        old_size = style.fontsize
        new_size = old_size * multiplier
        style.fontsize = new_size
        changes.append(f"{style.name}: {old_size} -> {new_size:.1f}")
        styles_affected += 1

    # Record operation
    record = OperationRecord(
        operation='size_multiplier',
        timestamp=datetime.now(),
        parameters={'multiplier': multiplier},
        styles_affected=styles_affected,
        summary=f"Scaled {styles_affected} style(s) by {multiplier}x"
    )
    data.operations.append(record)

    log(f"[SizeMultiplier] Scaled {styles_affected} style(s) by {multiplier}x")

    return OperationResult(
        success=True,
        operation='size_multiplier',
        styles_affected=styles_affected,
        summary=record.summary,
        details={'changes': changes}
    )


def apply_rescale(
    data: 'SubtitleData',
    target_resolution: Tuple[int, int],
    runner=None
) -> 'OperationResult':
    """
    Rescale subtitle to target resolution using Aegisub "Add Borders" style.

    Uses uniform scaling (min of scale_x, scale_y) to maintain aspect ratio.
    Position tags get border offsets for centering. Font sizes use vertical
    scaling (scale_h) to match Aegisub behavior.

    Args:
        data: SubtitleData to modify
        target_resolution: (width, height) tuple
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationResult, OperationRecord

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    target_x, target_y = target_resolution

    # Get current resolution
    current_x = int(data.script_info.get('PlayResX', 0))
    current_y = int(data.script_info.get('PlayResY', 0))

    # If no resolution set, just set it
    if current_x == 0 or current_y == 0:
        data.script_info['PlayResX'] = str(target_x)
        data.script_info['PlayResY'] = str(target_y)

        record = OperationRecord(
            operation='rescale',
            timestamp=datetime.now(),
            parameters={'target': f'{target_x}x{target_y}'},
            summary=f"Set resolution to {target_x}x{target_y}"
        )
        data.operations.append(record)
        log(f"[Rescale] Set resolution to {target_x}x{target_y}")

        return OperationResult(
            success=True,
            operation='rescale',
            summary=record.summary
        )

    # If already at target, skip
    if (current_x, current_y) == (target_x, target_y):
        log(f"[Rescale] Already at target resolution {target_x}x{target_y}")
        return OperationResult(
            success=True,
            operation='rescale',
            summary='Already at target resolution'
        )

    # Calculate scale factors (Aegisub "Add Borders" style)
    scale_x = target_x / current_x
    scale_y = target_y / current_y
    scale = min(scale_x, scale_y)  # Uniform scale to maintain aspect ratio
    scale_h = scale_y  # Vertical scaling for font sizes (Aegisub convention)

    # Calculate effective size and border offsets for position tags
    new_w = int(current_x * scale + 0.5)
    new_h = int(current_y * scale + 0.5)
    offset_x = (target_x - new_w) / 2
    offset_y = (target_y - new_h) / 2

    log(
        f"[Rescale] Rescaling from {current_x}x{current_y} to {target_x}x{target_y} "
        f"(uniform scale: {scale:.4f}, font scale: {scale_h:.4f}, "
        f"borders: {offset_x:.1f}x, {offset_y:.1f}y)"
    )

    # Scale styles (margins are edge-relative, so no offsets needed)
    styles_affected = 0
    for style in data.styles.values():
        # Use vertical scaling for font size (Aegisub convention)
        style.fontsize = int(style.fontsize * scale_h + 0.5)

        # Outline and shadow scale with vertical factor
        style.outline *= scale_h
        style.shadow *= scale_h

        # Margins are edge-relative, scale uniformly without offsets
        style.margin_l = int(style.margin_l * scale + 0.5)
        style.margin_r = int(style.margin_r * scale + 0.5)
        style.margin_v = int(style.margin_v * scale + 0.5)

        styles_affected += 1

    # Scale event margins and inline override tags
    events_affected = 0
    for event in data.events:
        # Scale event margins (edge-relative, no offsets)
        if event.margin_l != 0:
            event.margin_l = int(event.margin_l * scale + 0.5)
        if event.margin_r != 0:
            event.margin_r = int(event.margin_r * scale + 0.5)
        if event.margin_v != 0:
            event.margin_v = int(event.margin_v * scale + 0.5)

        # Scale inline override tags (position tags get offsets)
        if '{' in event.text:
            event.text = _scale_override_tags(event.text, scale, scale_h, offset_x, offset_y)
            events_affected += 1

    # Update script info
    data.script_info['PlayResX'] = str(target_x)
    data.script_info['PlayResY'] = str(target_y)

    # Record operation
    record = OperationRecord(
        operation='rescale',
        timestamp=datetime.now(),
        parameters={
            'from': f'{current_x}x{current_y}',
            'to': f'{target_x}x{target_y}',
            'scale': scale,
            'scale_h': scale_h,
            'offset_x': offset_x,
            'offset_y': offset_y,
        },
        styles_affected=styles_affected,
        events_affected=events_affected,
        summary=f"Rescaled from {current_x}x{current_y} to {target_x}x{target_y}"
    )
    data.operations.append(record)

    log(f"[Rescale] Successfully rescaled to {target_x}x{target_y}")

    return OperationResult(
        success=True,
        operation='rescale',
        styles_affected=styles_affected,
        events_affected=events_affected,
        summary=record.summary,
        details={
            'scale': scale,
            'scale_h': scale_h,
            'offset_x': offset_x,
            'offset_y': offset_y,
        }
    )


def _map_style_attribute(attr: str) -> str:
    """Map common attribute names to SubtitleStyle field names."""
    mapping = {
        # Font
        'font': 'fontname',
        'font_name': 'fontname',
        'size': 'fontsize',
        'font_size': 'fontsize',

        # Colors - Style Editor uses no-underscore names
        'primarycolor': 'primary_color',
        'secondarycolor': 'secondary_color',
        'outlinecolor': 'outline_color',
        'backcolor': 'back_color',
        # Alternative variations
        'color': 'primary_color',
        'colour': 'primary_color',
        'primary': 'primary_color',
        'secondary': 'secondary_color',
        'outline_colour': 'outline_color',
        'back_colour': 'back_color',

        # Other attributes
        'strikeout': 'strike_out',
        'border': 'border_style',
        'align': 'alignment',
        'marginl': 'margin_l',
        'marginr': 'margin_r',
        'marginv': 'margin_v',
        'scalex': 'scale_x',
        'scaley': 'scale_y',
    }
    return mapping.get(attr.lower(), attr.lower().replace('-', '_'))


def apply_style_filter(
    data: 'SubtitleData',
    styles: list,
    mode: str = 'exclude',
    forced_include: Optional[List[int]] = None,
    forced_exclude: Optional[List[int]] = None,
    runner=None
) -> 'OperationResult':
    """
    Filter events by style name.

    Args:
        data: SubtitleData to modify
        styles: List of style names to filter
        mode: 'exclude' (remove these styles) or 'include' (keep only these styles)
        runner: CommandRunner for logging

    Returns:
        OperationResult with filtering statistics
    """
    from ..data import OperationResult, OperationRecord

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    forced_include_set = set(forced_include or [])
    forced_exclude_set = set(forced_exclude or [])

    if not styles and not forced_include_set and not forced_exclude_set:
        return OperationResult(
            success=True,
            operation='style_filter',
            summary='No styles specified for filtering'
        )

    original_count = len(data.events)
    styles_set = set(styles)

    # Track which styles were found
    found_styles = set()
    for event in data.events:
        if event.style in styles_set:
            found_styles.add(event.style)

    # Filter events
    original_events = list(data.events)
    if mode == 'include':
        # Keep only events with styles in the list or forced includes.
        filtered_events = []
        for idx, event in enumerate(original_events):
            if idx in forced_exclude_set:
                continue
            if idx in forced_include_set or event.style in styles_set:
                filtered_events.append(event)
        data.events = filtered_events
        mode_desc = 'included'
    else:  # mode == 'exclude'
        # Remove events with styles in the list unless forced to include.
        filtered_events = []
        for idx, event in enumerate(original_events):
            if idx in forced_exclude_set:
                continue
            if idx in forced_include_set or event.style not in styles_set:
                filtered_events.append(event)
        data.events = filtered_events
        mode_desc = 'excluded'

    filtered_count = len(data.events)
    removed_count = original_count - filtered_count

    # Check for missing styles
    missing_styles = styles_set - found_styles

    log(f"[StyleFilter] {mode_desc.capitalize()} {len(found_styles)} style(s), "
        f"removed {removed_count}/{original_count} events")

    if missing_styles:
        log(f"[StyleFilter] WARNING: Styles not found in file: {', '.join(sorted(missing_styles))}")

    # Record operation
    record = OperationRecord(
        operation='style_filter',
        timestamp=datetime.now(),
        parameters={
            'styles': list(styles),
            'mode': mode,
            'forced_include': sorted(forced_include_set),
            'forced_exclude': sorted(forced_exclude_set),
        },
        events_affected=removed_count,
        summary=f"{mode_desc.capitalize()} styles: {', '.join(sorted(found_styles)) or 'none'}, "
                f"removed {removed_count} events"
    )
    data.operations.append(record)

    return OperationResult(
        success=True,
        operation='style_filter',
        events_affected=removed_count,
        summary=record.summary,
        details={
            'original_count': original_count,
            'filtered_count': filtered_count,
            'removed_count': removed_count,
            'styles_found': list(found_styles),
            'styles_missing': list(missing_styles),
        }
    )
