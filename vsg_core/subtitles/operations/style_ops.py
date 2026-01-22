# vsg_core/subtitles/operations/style_ops.py
# -*- coding: utf-8 -*-
"""
Style operations for SubtitleData.

Operations:
- apply_style_patch: Apply attribute changes to styles
- apply_font_replacement: Replace font names
- apply_size_multiplier: Scale font sizes
- apply_rescale: Rescale to target resolution
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord


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
            # Map common attribute names
            attr_name = _map_style_attribute(attr)

            if hasattr(style, attr_name):
                old_value = getattr(style, attr_name)
                setattr(style, attr_name, value)
                changes.append(f"{style_name}.{attr_name}: {old_value} -> {value}")
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
    Rescale subtitle to target resolution.

    Scales font sizes, margins, outline, shadow proportionally.

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

    # Calculate scale factors
    scale_x = target_x / current_x
    scale_y = target_y / current_y

    # Scale styles
    styles_affected = 0
    for style in data.styles.values():
        # Font size scales with Y
        style.fontsize *= scale_y

        # Outline and shadow scale with Y
        style.outline *= scale_y
        style.shadow *= scale_y

        # Margins scale with respective axis
        style.margin_l = int(style.margin_l * scale_x)
        style.margin_r = int(style.margin_r * scale_x)
        style.margin_v = int(style.margin_v * scale_y)

        styles_affected += 1

    # Scale event margins too
    events_affected = 0
    for event in data.events:
        if event.margin_l != 0:
            event.margin_l = int(event.margin_l * scale_x)
            events_affected += 1
        if event.margin_r != 0:
            event.margin_r = int(event.margin_r * scale_x)
            events_affected += 1
        if event.margin_v != 0:
            event.margin_v = int(event.margin_v * scale_y)
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
            'scale_x': scale_x,
            'scale_y': scale_y,
        },
        styles_affected=styles_affected,
        events_affected=events_affected,
        summary=f"Rescaled from {current_x}x{current_y} to {target_x}x{target_y}"
    )
    data.operations.append(record)

    log(f"[Rescale] {record.summary}")

    return OperationResult(
        success=True,
        operation='rescale',
        styles_affected=styles_affected,
        events_affected=events_affected,
        summary=record.summary,
        details={
            'scale_x': scale_x,
            'scale_y': scale_y,
        }
    )


def _map_style_attribute(attr: str) -> str:
    """Map common attribute names to SubtitleStyle field names."""
    mapping = {
        # Common variations
        'font': 'fontname',
        'font_name': 'fontname',
        'size': 'fontsize',
        'font_size': 'fontsize',
        'color': 'primary_color',
        'colour': 'primary_color',
        'primary': 'primary_color',
        'secondary': 'secondary_color',
        'outline_colour': 'outline_color',
        'back_colour': 'back_color',
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
