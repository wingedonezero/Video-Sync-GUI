# vsg_core/subtitles/operations/style_ops.py
"""
Style operations for SubtitleData.

Operations:
- apply_style_patch: Apply attribute changes to styles
- apply_font_replacement: Replace font names
- apply_size_multiplier: Scale font sizes
- apply_rescale: Rescale to target resolution (Aegisub resampler, aspect mode
  chosen from the two videos' displayed shapes)
- apply_style_filter: Filter events by style name (include/exclude)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..data import OperationResult, SubtitleData


def _find_matching_paren(text: str, open_pos: int) -> int:
    """Find the position of the matching closing paren.

    Args:
        text: The text to search.
        open_pos: Position of the opening '('.

    Returns:
        Position of matching ')' or -1 if not found.
    """
    depth = 1
    pos = open_pos + 1
    while pos < len(text):
        if text[pos] == "(":
            depth += 1
        elif text[pos] == ")":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return -1


def _split_transform_args(content: str) -> tuple[str, str]:
    """Split \\t() content into timing/accel params and the tag block.

    In ASS, \\t() format is: \\t([t1,t2,][accel,]\\tags...)
    The tag block always starts with '\\'.  Everything before that
    first backslash (minus any trailing comma/whitespace) is the
    numeric timing/acceleration parameters.

    Args:
        content: The content inside \\t(...), excluding outer parens.

    Returns:
        Tuple of (timing_params, tag_block).  Either may be empty.
    """
    # Scan for the first backslash — that's where tags begin
    for i, ch in enumerate(content):
        if ch == "\\":
            timing = content[:i].rstrip(", ")
            tags = content[i:]
            return timing, tags
    # No backslash found — everything is timing/accel, no tags
    return content, ""


# Matches \p<N> drawing-mode tags (\p1, \p2, ...) — but not \pos/\pbo,
# since those have no digit directly after the 'p'.
_DRAWING_MODE_RE = re.compile(r"\\p(\d+)")


def _scale_drawing(
    drawing: str,
    scale_x: float,
    scale_y: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> str:
    """Scale coordinates in an ASS drawing command string (m/n/l/b/s/p/c).

    Mirrors Aegisub's transform_drawing: numbers alternate x/y, and any
    command letter resets the alternation to x.  Offsets are only passed
    for vector clips (absolute script coordinates); drawings after \\p
    are anchor-relative, so their offsets stay 0.
    """
    out: list[str] = []
    is_x = True
    for token in re.split(r"(\s+)", drawing):
        if not token or token.isspace():
            out.append(token)
            continue
        try:
            value = float(token)
        except ValueError:
            out.append(token)
            is_x = True
            continue
        if is_x:
            scaled = value * scale_x + offset_x
        else:
            scaled = value * scale_y + offset_y
        is_x = not is_x
        out.append(f"{scaled:.3f}".rstrip("0").rstrip("."))
    return "".join(out)


@dataclass(frozen=True, slots=True)
class RescaleGeometry:
    """Where script coordinates land in the target script.

    A source point (x, y) lands at (x * scale_x + offset_x, y * scale_y + offset_y)
    target pixels; the offsets are the border width when the two pictures have
    different shapes. Sizes scale by ``scale_y`` (Aegisub's convention: glyph
    sizes follow the vertical factor), except the explicitly horizontal
    \\xbord / \\xshad, which take ``scale_x``. ``text_x`` multiplies style ScaleX
    and \\fscx so glyphs keep their displayed shape when the pixel aspect of a
    script pixel changes (anamorphic source or target); it is 1 otherwise.

    Some sizes are not in script pixels but in LayoutRes pixels (the video's
    stored pixels when the script has no LayoutRes): \\blur and \\be always,
    borders and shadows when ScaledBorderAndShadow is off, and the camera
    distance of \\frx/\\fry. ``layout_res`` is the LayoutRes that keeps them
    all the same relative to the text (Aegisub's rule), so those tags only
    take ``video_x`` / ``video_y``, the tiny correction for it being whole
    pixels. None means no layout reference is kept: they follow ``scale_x`` /
    ``scale_y`` like script-pixel sizes.
    """

    scale_x: float
    scale_y: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    text_x: float = 1.0
    video_x: float | None = None
    video_y: float | None = None
    scaled_borders: bool = True
    layout_res: tuple[int, int] | None = None

    def size_factor(self, tag: str) -> float | None:
        """Factor for a size tag (lowercase name, no backslash); None if not one."""
        video_x = self.scale_x if self.video_x is None else self.video_x
        video_y = self.scale_y if self.video_y is None else self.video_y
        if tag in ("blur", "be"):
            return video_y
        if tag in ("bord", "ybord", "shad", "yshad"):
            return self.scale_y if self.scaled_borders else video_y
        if tag in ("xbord", "xshad"):
            return self.scale_x if self.scaled_borders else video_x
        if tag in ("fs", "fsp", "pbo"):
            return self.scale_y
        return None

    @property
    def is_identity(self) -> bool:
        """Nothing in the script moves or resizes (LayoutRes checked apart)."""
        return (
            self.scale_x == 1.0
            and self.scale_y == 1.0
            and self.offset_x == 0.0
            and self.offset_y == 0.0
            and self.text_x == 1.0
            and self.video_x in (None, 1.0)
            and self.video_y in (None, 1.0)
        )


def rescale_geometry(
    play_res: tuple[int, int],
    target: tuple[int, int],
    source_dar: Fraction | None = None,
    target_sar: Fraction = Fraction(1),
    layout_res: tuple[int, int] | None = None,
    source_size: tuple[int, int] | None = None,
    scaled_borders: bool = True,
) -> RescaleGeometry:
    """Map a script covering one picture onto another, by displayed shape.

    ``source_dar`` is the display aspect of the picture the script was made
    for (its own video); None means unknown, so the PlayRes grid is taken as
    square pixels. ``target_sar`` is the pixel aspect of the target's stored
    pixels (853:720 for a 16:9 NTSC DVD). Borders are added only where the two
    displayed shapes really differ (Aegisub "Add borders": the source plus
    borders has the target's shape), computed exactly in fractions so
    square same-shape jobs reduce to plain ``target / PlayRes`` factors.

    ``layout_res`` is the script's LayoutResX/Y: libass draws glyphs against
    it instead of the player's pixel aspect, so it sets the source's glyph
    aspect when present. It is also the unit of \\blur, \\be, unscaled
    borders and the 3D camera distance; without it libass uses the video's
    stored size (``source_size``), else we fall back to PlayRes. The target
    LayoutRes keeps that unit the same size relative to the text: the same
    height (plus any top/bottom border, as Aegisub), with PlayRes's shape so
    the glyph aspect stays the one ``text_x`` was computed for.
    """
    px, py = play_res
    tw, th = target
    play_ar = Fraction(px, py)
    src_dar = source_dar if source_dar is not None else play_ar
    tgt_dar = Fraction(tw, th) * target_sar
    # Display width of one script x unit, in script y units.
    unit_aspect = src_dar / play_ar
    glyph_aspect = src_dar / Fraction(*layout_res) if layout_res else unit_aspect

    border_x = border_y = Fraction(0)
    if tgt_dar > src_dar:  # target wider: bars left and right
        border_x = py * (tgt_dar - src_dar) / (2 * unit_aspect)
    elif tgt_dar < src_dar:  # target taller: bars top and bottom
        border_y = (px * unit_aspect / tgt_dar - py) / 2

    scale_x = Fraction(tw) / (px + 2 * border_x)
    scale_y = Fraction(th) / (py + 2 * border_y)

    unit_h = (layout_res or source_size or play_res)[1]
    layout_y = unit_h * (py + 2 * border_y) / py
    layout_x = layout_y * Fraction(tw, th)
    target_layout = (round(layout_x), round(layout_y))
    return RescaleGeometry(
        scale_x=float(scale_x),
        scale_y=float(scale_y),
        offset_x=float(border_x * scale_x),
        offset_y=float(border_y * scale_y),
        text_x=float(glyph_aspect / target_sar),
        video_x=float(target_layout[0] / layout_x),
        video_y=float(target_layout[1] / layout_y),
        scaled_borders=scaled_borders,
        layout_res=target_layout,
    )


def _scale_override_tags(text: str, geom: RescaleGeometry) -> str:
    """
    Scales all ASS override tags onto the target and adds border offsets.

    Matches Aegisub's resolution resampler behaviour:
    - \\fscx/\\fscy are NOT rescaled by the resolution (\\fs already is);
      \\fscx only takes ``text_x``, the pixel-aspect correction, when that
      is not 1 — the same factor as style ScaleX, which an inline \\fscx
      would otherwise override.
    - \\t() transform blocks are recursively processed so pixel-based
      tags inside animations are correctly rescaled.
    - \\iclip is handled identically to \\clip.
    - Vector drawings after \\p1..\\pN are scaled (no offset — the anchor
      already carries it, and x divided by ``text_x`` because \\fscx
      stretches drawings too); vector clips are scaled with offsets, since
      their coordinates are absolute script pixels.
    - A tag whose closing paren is missing ends at the end of its {...}
      block, as libass reads it; the paren stays missing.

    Args:
        text: Event text with ASS override tags
        geom: Where script coordinates land in the target

    Returns:
        Text with scaled override tags
    """

    # Size tags and their factors: RescaleGeometry.size_factor
    # Position tags with (x, y) that need offsets
    _POS_TAGS = frozenset(("pos", "org"))
    # Clip tags with (x1, y1, x2, y2) that need offsets
    _CLIP_TAGS = frozenset(("clip", "iclip"))

    def scale_value(val: str, scale_factor: float, offset: float = 0) -> str:
        """Scale a numeric value, add offset, and format cleanly."""
        try:
            scaled = float(val) * scale_factor + offset
            return f"{scaled:.3f}".rstrip("0").rstrip(".")
        except ValueError:
            return val

    def scale_tag(tag_name: str, args: str) -> str:
        """Scale parenthesised tag arguments based on tag type."""
        if not args:
            return args

        tag_lower = tag_name.lower()
        parts = [p.strip() for p in args.split(",")]

        # Vector clips: \clip(<drawing>) or \clip(<scale>, <drawing>).
        # Coordinates are absolute script pixels, so they get scale AND
        # border offsets — same treatment Aegisub gives them (rect clips
        # keep going through the numeric path below).
        if (
            tag_lower in _CLIP_TAGS
            and len(parts) <= 2
            and re.search(r"[a-zA-Z]", parts[-1])
        ):
            scaled_drawing = _scale_drawing(
                parts[-1], geom.scale_x, geom.scale_y, geom.offset_x, geom.offset_y
            )
            return ",".join([*parts[:-1], scaled_drawing])

        scaled_parts = []

        size = geom.size_factor(tag_lower)
        for i, part in enumerate(parts):
            if size is not None:
                scaled_parts.append(scale_value(part, size))

            # Position-like (x, y) pairs — need offsets: \pos/\org (x, y),
            # \clip/\iclip (x1, y1, x2, y2), \move (x1, y1, x2, y2, t1, t2)
            elif (
                (tag_lower in _POS_TAGS and i < 2)
                or (tag_lower in _CLIP_TAGS and i < 4)
                or (tag_lower == "move" and i < 4)
            ):
                if i % 2 == 0:
                    scaled_parts.append(scale_value(part, geom.scale_x, geom.offset_x))
                else:
                    scaled_parts.append(scale_value(part, geom.scale_y, geom.offset_y))

            # Everything else (time-based, percentages, etc.) — preserve
            else:
                scaled_parts.append(part)

        return ",".join(scaled_parts)

    def process_override_block(block_content: str) -> str:
        """Process all tags within a single {...} block.

        Handles \\t() transform blocks with balanced-paren matching
        and recursive tag processing.  All other tags are processed
        via the existing regex path.
        """
        # --- Phase 1: extract \\t() blocks with balanced parens ---
        segments: list[str] = []
        last_end = 0
        i = 0

        while i < len(block_content):
            # Look for \t( — the transform tag with opening paren
            if (
                block_content[i] == "\\"
                and i + 2 < len(block_content)
                and block_content[i + 1] == "t"
                and block_content[i + 2] == "("
            ):
                # Process everything before this \t with the regex pass
                if i > last_end:
                    segments.append(_process_simple_tags(block_content[last_end:i]))

                close = _find_matching_paren(block_content, i + 2)
                # No closing paren: libass ends the tag at the block's end.
                end = close if close > 0 else len(block_content)
                closer = ")" if close > 0 else ""
                t_content = block_content[i + 3 : end]
                timing, tags = _split_transform_args(t_content)

                if tags:
                    # Recursively process tags inside the transform
                    processed_tags = process_override_block(tags)
                    if timing:
                        segments.append(f"\\t({timing},{processed_tags}{closer}")
                    else:
                        segments.append(f"\\t({processed_tags}{closer}")
                else:
                    # No tags, just timing/accel — preserve as-is
                    segments.append(f"\\t({timing}{closer}")

                i = end + 1
                last_end = i
            else:
                i += 1

        # Process remaining content after the last \t() block
        if last_end < len(block_content):
            segments.append(_process_simple_tags(block_content[last_end:]))

        return "".join(segments)

    def _process_simple_tags(content: str) -> str:
        """Process non-\\t tags via regex."""
        # A paren group runs to ')' or, when that is missing, to the end of
        # the block (libass's reading).
        tag_pattern = re.compile(
            r"\\([a-zA-Z]+)(\([^)]*(?:\)|$)|(?:\-?\d+(?:\.\d+)?))?"
        )

        def replace_tag(match: re.Match[str]) -> str:
            tag_name = match.group(1)
            tag_lower = tag_name.lower()
            args_or_value = match.group(2)

            if args_or_value is None:
                return match.group(0)

            elif args_or_value.startswith("("):
                # Tag with parentheses — scale args
                closed = args_or_value.endswith(")")
                args = args_or_value[1:-1] if closed else args_or_value[1:]
                scaled_args = scale_tag(tag_name, args)
                return f"\\{tag_name}({scaled_args}{')' if closed else ''}"

            else:
                # Shorthand numeric value
                value = args_or_value

                size = geom.size_factor(tag_lower)
                # \fs+N / \fs-N are relative steps (10% each), not sizes
                if size is not None and not (
                    tag_lower == "fs" and value.startswith("-")
                ):
                    scaled = scale_value(value, size)
                    return f"\\{tag_name}{scaled}"
                elif tag_lower == "fscx" and geom.text_x != 1.0:
                    scaled = scale_value(value, geom.text_x)
                    return f"\\{tag_name}{scaled}"
                else:
                    return match.group(0)

        return tag_pattern.sub(replace_tag, content)

    # Walk alternating override blocks / text runs, tracking \p drawing
    # mode: text after \p1..\pN is a vector drawing whose coordinates
    # must be scaled too.  Aegisub resamples these with zero shift — the
    # anchor position (\pos / margins) already carries the border offset.
    segments = re.split(r"(\{[^}]*\})", text)
    drawing_mode = 0
    result: list[str] = []
    for segment in segments:
        if segment.startswith("{") and segment.endswith("}"):
            result.append("{" + process_override_block(segment[1:-1]) + "}")
            for p_match in _DRAWING_MODE_RE.finditer(segment):
                drawing_mode = int(p_match.group(1))
        elif drawing_mode > 0:
            result.append(
                _scale_drawing(segment, geom.scale_x / geom.text_x, geom.scale_y)
            )
        else:
            result.append(segment)
    return "".join(result)


# Color attributes that need Qt->ASS conversion
_COLOR_ATTRIBUTES = {"primary_color", "secondary_color", "outline_color", "back_color"}

# Bool attributes that need bool->int conversion (-1 for True, 0 for False)
_BOOL_ATTRIBUTES = {"bold", "italic", "underline", "strike_out"}


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

        if isinstance(value, str) and value.startswith("#"):
            return qt_color_to_ass(value)
        return value

    if attr_name in _BOOL_ATTRIBUTES:
        if isinstance(value, bool):
            return -1 if value else 0
        return value

    return value


def apply_style_patch(
    data: SubtitleData, patches: dict[str, dict[str, Any]], runner=None
) -> OperationResult:
    """
    Apply attribute patches to styles.

    Args:
        data: SubtitleData to modify
        patches: Dict of style_name -> {attribute: value}
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationRecord, OperationResult

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    if not patches:
        return OperationResult(
            success=True, operation="style_patch", summary="No patches provided"
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
                changes.append(
                    f"{style_name}.{attr_name}: {old_value} -> {converted_value}"
                )
            else:
                log(
                    f"[StylePatch] WARNING: Unknown attribute '{attr}' for style '{style_name}'"
                )

        styles_affected += 1

    # Record operation
    record = OperationRecord(
        operation="style_patch",
        timestamp=datetime.now(),
        parameters={"patches": {k: list(v.keys()) for k, v in patches.items()}},
        styles_affected=styles_affected,
        summary=f"Patched {styles_affected} style(s)",
    )
    data.operations.append(record)

    log(f"[StylePatch] Applied {len(changes)} change(s) to {styles_affected} style(s)")

    return OperationResult(
        success=True,
        operation="style_patch",
        styles_affected=styles_affected,
        summary=record.summary,
        details={"changes": changes},
    )


def apply_font_replacement(
    data: SubtitleData, replacements: dict[str, str], runner=None
) -> OperationResult:
    """
    Replace font names in styles.

    Args:
        data: SubtitleData to modify
        replacements: Dict of old_font -> new_font
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationRecord, OperationResult

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    if not replacements:
        return OperationResult(
            success=True,
            operation="font_replacement",
            summary="No replacements provided",
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
        operation="font_replacement",
        timestamp=datetime.now(),
        parameters={"replacements": replacements},
        styles_affected=styles_affected,
        summary=f"Replaced fonts in {styles_affected} style(s)",
    )
    data.operations.append(record)

    log(f"[FontReplacement] Replaced {styles_affected} font(s)")

    return OperationResult(
        success=True,
        operation="font_replacement",
        styles_affected=styles_affected,
        summary=record.summary,
        details={"changes": changes},
    )


def apply_size_multiplier(
    data: SubtitleData, multiplier: float, runner=None
) -> OperationResult:
    """
    Apply font size multiplier to all styles.

    Args:
        data: SubtitleData to modify
        multiplier: Size multiplier (e.g., 1.2 for 20% increase)
        runner: CommandRunner for logging

    Returns:
        OperationResult
    """
    from ..data import OperationRecord, OperationResult

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    # Skip if multiplier is effectively 1.0
    if abs(multiplier - 1.0) < 1e-6:
        return OperationResult(
            success=True,
            operation="size_multiplier",
            summary="Multiplier is 1.0, no changes",
        )

    # Validate range
    if not (0.1 <= multiplier <= 10.0):
        return OperationResult(
            success=False,
            operation="size_multiplier",
            error=f"Multiplier {multiplier} out of range (0.1-10.0)",
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
        operation="size_multiplier",
        timestamp=datetime.now(),
        parameters={"multiplier": multiplier},
        styles_affected=styles_affected,
        summary=f"Scaled {styles_affected} style(s) by {multiplier}x",
    )
    data.operations.append(record)

    log(f"[SizeMultiplier] Scaled {styles_affected} style(s) by {multiplier}x")

    return OperationResult(
        success=True,
        operation="size_multiplier",
        styles_affected=styles_affected,
        summary=record.summary,
        details={"changes": changes},
    )


def apply_rescale(
    data: SubtitleData,
    target_resolution: tuple[int, int],
    runner=None,
    *,
    source_dar: Fraction | None = None,
    target_sar: Fraction = Fraction(1),
    source_size: tuple[int, int] | None = None,
) -> OperationResult:
    """
    Rescale subtitle to target resolution, matching pictures by displayed shape.

    Aegisub's resampler with the aspect mode chosen from the two videos
    (``rescale_geometry``): same displayed shape → plain scale ("Stretch" when
    a pixel aspect differs), different shape → "Add borders" with the border
    added to positions and margins. When the target has non-square pixels the
    script gets LayoutResX/Y = the target's stored size, so libass in every
    player (mpv, Kodi, Jellyfin) draws the glyphs at the shape ScaleX was
    corrected for, instead of following each player's own pixel-aspect setting.

    Args:
        data: SubtitleData to modify
        target_resolution: Target's stored (width, height)
        runner: CommandRunner for logging
        source_dar: Display aspect of the script's own video; None = unknown
            (PlayRes taken as square pixels)
        target_sar: Pixel aspect of the target's stored pixels
        source_size: Stored size of the script's own video (None = unknown);
            \\blur, \\be and unscaled borders are in its pixels

    Returns:
        OperationResult
    """
    from ..data import OperationRecord, OperationResult

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    target_x, target_y = target_resolution

    # Get current resolution
    current_x = int(data.script_info.get("PlayResX", 0))
    current_y = int(data.script_info.get("PlayResY", 0))

    # If no resolution set, just set it
    if current_x == 0 or current_y == 0:
        data.script_info["PlayResX"] = str(target_x)
        data.script_info["PlayResY"] = str(target_y)

        record = OperationRecord(
            operation="rescale",
            timestamp=datetime.now(),
            parameters={"target": f"{target_x}x{target_y}"},
            summary=f"Set resolution to {target_x}x{target_y}",
        )
        data.operations.append(record)
        log(f"[Rescale] Set resolution to {target_x}x{target_y}")

        return OperationResult(
            success=True, operation="rescale", summary=record.summary
        )

    layout_res = _layout_res(data)
    geom = rescale_geometry(
        (current_x, current_y),
        (target_x, target_y),
        source_dar=source_dar,
        target_sar=target_sar,
        layout_res=layout_res,
        source_size=source_size,
        scaled_borders=_scaled_borders(data),
    )
    anamorphic_target = target_sar != 1
    new_layout = geom.layout_res or (target_x, target_y)
    # LayoutRes is written when the script had one, when the target is
    # anamorphic (libass then takes the glyph aspect from it instead of each
    # player's own setting), or when the layout unit differs from the
    # target's stored pixels (what libass falls back to without it).
    write_layout = (
        layout_res is not None
        or anamorphic_target
        or new_layout != (target_x, target_y)
    )

    # Nothing to convert
    if geom.is_identity and new_layout == (layout_res or (target_x, target_y)):
        log(f"[Rescale] Already at target resolution {target_x}x{target_y}")
        return OperationResult(
            success=True, operation="rescale", summary="Already at target resolution"
        )

    log(
        _describe_rescale(
            (current_x, current_y),
            (target_x, target_y),
            source_dar,
            target_sar,
            geom,
            layout_res=new_layout if write_layout else None,
        )
    )

    styles_affected = 0
    for style in data.styles.values():
        # Glyph sizes follow the vertical factor (Aegisub convention). Kept
        # fractional: Aegisub rounds to whole sizes, which visibly changes
        # 35 -> 52.5 -> 53; libass and VSFilter read decimals.
        style.fontsize = round(style.fontsize * geom.scale_y, 3)
        style.outline *= geom.size_factor("bord") or geom.scale_y
        style.shadow *= geom.size_factor("shad") or geom.scale_y
        # Spacing is drawn in glyph space (multiplied by ScaleX), so it takes
        # the vertical factor too (Aegisub: spacing *= ry)
        style.spacing *= geom.scale_y
        if geom.text_x != 1.0:
            style.scale_x *= geom.text_x

        # Margins are distances from the frame edge: the border goes in
        # first, as Aegisub does ((margin + border) * scale)
        style.margin_l = int(style.margin_l * geom.scale_x + geom.offset_x + 0.5)
        style.margin_r = int(style.margin_r * geom.scale_x + geom.offset_x + 0.5)
        style.margin_v = int(style.margin_v * geom.scale_y + geom.offset_y + 0.5)

        styles_affected += 1

    # Scale event margins and inline override tags
    events_affected = 0
    for event in data.events:
        # Event margins: 0 means "use the style's", so only set ones move
        if event.margin_l != 0:
            event.margin_l = int(event.margin_l * geom.scale_x + geom.offset_x + 0.5)
        if event.margin_r != 0:
            event.margin_r = int(event.margin_r * geom.scale_x + geom.offset_x + 0.5)
        if event.margin_v != 0:
            event.margin_v = int(event.margin_v * geom.scale_y + geom.offset_y + 0.5)

        if event.effect:
            event.effect = _scale_effect(event.effect, geom)

        # Scale inline override tags (position tags get offsets)
        if "{" in event.text:
            event.text = _scale_override_tags(event.text, geom)
            events_affected += 1

    # Update script info
    data.script_info["PlayResX"] = str(target_x)
    data.script_info["PlayResY"] = str(target_y)

    if write_layout:
        data.script_info["LayoutResX"] = str(new_layout[0])
        data.script_info["LayoutResY"] = str(new_layout[1])

    # Record operation
    record = OperationRecord(
        operation="rescale",
        timestamp=datetime.now(),
        parameters={
            "from": f"{current_x}x{current_y}",
            "to": f"{target_x}x{target_y}",
            "scale_x": geom.scale_x,
            "scale_y": geom.scale_y,
            "offset_x": geom.offset_x,
            "offset_y": geom.offset_y,
            "text_x": geom.text_x,
        },
        styles_affected=styles_affected,
        events_affected=events_affected,
        summary=f"Rescaled from {current_x}x{current_y} to {target_x}x{target_y}",
    )
    data.operations.append(record)

    log(f"[Rescale] Successfully rescaled to {target_x}x{target_y}")

    return OperationResult(
        success=True,
        operation="rescale",
        styles_affected=styles_affected,
        events_affected=events_affected,
        summary=record.summary,
        details={
            "scale_x": geom.scale_x,
            "scale_y": geom.scale_y,
            "offset_x": geom.offset_x,
            "offset_y": geom.offset_y,
            "text_x": geom.text_x,
        },
    )


def _scaled_borders(data: SubtitleData) -> bool:
    """ScaledBorderAndShadow: borders in script pixels (yes) or video pixels.

    Missing means no, as in libass and VSFilter.
    """
    value = str(data.script_info.get("ScaledBorderAndShadow", "no")).strip()
    return value.lower() in ("yes", "1", "true")


def _scale_effect(effect: str, geom: RescaleGeometry) -> str:
    """Scale the PlayRes-pixel parameters of Scroll up/down and Banner.

    ``Scroll up;y1;y2;delay[;fade]``: y1/y2 are positions, fade a height;
    ``Banner;delay[;left-to-right[;fade]]``: fade is a width. The delay is
    milliseconds per PlayRes pixel, so it shrinks as pixels get smaller to
    keep the speed. Renderers read these as integers, so they are rounded.
    """
    parts = effect.split(";")
    name = parts[0].strip().lower()

    def num(i: int, factor: float, offset: float = 0.0, *, delay: bool = False) -> None:
        if i >= len(parts):
            return
        try:
            value = int(parts[i])
        except ValueError:
            return
        if delay:
            parts[i] = str(max(round(value / factor), 1)) if value else "0"
        else:
            parts[i] = str(round(value * factor + offset))

    if name in ("scroll up", "scroll down"):
        num(1, geom.scale_y, geom.offset_y)
        num(2, geom.scale_y, geom.offset_y)
        num(3, geom.scale_y, delay=True)
        num(4, geom.scale_y)
    elif name == "banner":
        num(1, geom.scale_x, delay=True)
        num(3, geom.scale_x)
    return ";".join(parts)


def _layout_res(data: SubtitleData) -> tuple[int, int] | None:
    """The script's LayoutResX/Y, when both are valid positive integers."""
    try:
        lx = int(data.script_info.get("LayoutResX", 0))
        ly = int(data.script_info.get("LayoutResY", 0))
    except ValueError:
        return None
    return (lx, ly) if lx > 0 and ly > 0 else None


def _describe_rescale(
    play_res: tuple[int, int],
    target: tuple[int, int],
    source_dar: Fraction | None,
    target_sar: Fraction,
    geom: RescaleGeometry,
    *,
    layout_res: tuple[int, int] | None,
) -> str:
    """One log line: what the two pictures are and what the rescale does."""
    px, py = play_res
    tw, th = target
    src = (
        f"picture {source_dar.numerator}:{source_dar.denominator}"
        if source_dar is not None
        else "no source video, PlayRes taken as square pixels"
    )
    tgt = f"shown {round(tw * target_sar)}x{th}" if target_sar != 1 else "square pixels"
    parts = [f"x {geom.scale_x:.4f}, y {geom.scale_y:.4f}"]
    if geom.offset_x:
        parts.append(f"side bars {geom.offset_x:.1f} px")
    elif geom.offset_y:
        parts.append(f"top/bottom bars {geom.offset_y:.1f} px")
    else:
        parts.append("same picture shape, no bars")
    if geom.text_x != 1.0:
        parts.append(f"text width x{geom.text_x:.4f}")
    if layout_res:
        parts.append(f"LayoutRes {layout_res[0]}x{layout_res[1]}")
    return f"[Rescale] {px}x{py} ({src}) -> {tw}x{th} ({tgt}): " + ", ".join(parts)


def _map_style_attribute(attr: str) -> str:
    """Map common attribute names to SubtitleStyle field names."""
    mapping = {
        # Font
        "font": "fontname",
        "font_name": "fontname",
        "size": "fontsize",
        "font_size": "fontsize",
        # Colors - Style Editor uses no-underscore names
        "primarycolor": "primary_color",
        "secondarycolor": "secondary_color",
        "outlinecolor": "outline_color",
        "backcolor": "back_color",
        # Alternative variations
        "color": "primary_color",
        "colour": "primary_color",
        "primary": "primary_color",
        "secondary": "secondary_color",
        "outline_colour": "outline_color",
        "back_colour": "back_color",
        # Other attributes
        "strikeout": "strike_out",
        "border": "border_style",
        "align": "alignment",
        "marginl": "margin_l",
        "marginr": "margin_r",
        "marginv": "margin_v",
        "scalex": "scale_x",
        "scaley": "scale_y",
    }
    return mapping.get(attr.lower(), attr.lower().replace("-", "_"))


def apply_style_filter(
    data: SubtitleData,
    styles: list,
    mode: str = "exclude",
    forced_include: list[int] | None = None,
    forced_exclude: list[int] | None = None,
    runner=None,
) -> OperationResult:
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
    from ..data import OperationRecord, OperationResult

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    forced_include_set = set(forced_include or [])
    forced_exclude_set = set(forced_exclude or [])

    if not styles and not forced_include_set and not forced_exclude_set:
        return OperationResult(
            success=True,
            operation="style_filter",
            summary="No styles specified for filtering",
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
    if mode == "include":
        # Keep only events with styles in the list or forced includes.
        filtered_events = []
        for idx, event in enumerate(original_events):
            if idx in forced_exclude_set:
                continue
            if idx in forced_include_set or event.style in styles_set:
                filtered_events.append(event)
        data.events = filtered_events
        mode_desc = "included"
    else:  # mode == 'exclude'
        # Remove events with styles in the list unless forced to include.
        filtered_events = []
        for idx, event in enumerate(original_events):
            if idx in forced_exclude_set:
                continue
            if idx in forced_include_set or event.style not in styles_set:
                filtered_events.append(event)
        data.events = filtered_events
        mode_desc = "excluded"

    filtered_count = len(data.events)
    removed_count = original_count - filtered_count

    # Check for missing styles
    missing_styles = styles_set - found_styles

    log(
        f"[StyleFilter] {mode_desc.capitalize()} {len(found_styles)} style(s), "
        f"removed {removed_count}/{original_count} events"
    )

    if missing_styles:
        log(
            f"[StyleFilter] WARNING: Styles not found in file: {', '.join(sorted(missing_styles))}"
        )

    # Record operation
    record = OperationRecord(
        operation="style_filter",
        timestamp=datetime.now(),
        parameters={
            "styles": list(styles),
            "mode": mode,
            "forced_include": sorted(forced_include_set),
            "forced_exclude": sorted(forced_exclude_set),
        },
        events_affected=removed_count,
        summary=f"{mode_desc.capitalize()} styles: {', '.join(sorted(found_styles)) or 'none'}, "
        f"removed {removed_count} events",
    )
    data.operations.append(record)

    return OperationResult(
        success=True,
        operation="style_filter",
        events_affected=removed_count,
        summary=record.summary,
        details={
            "original_count": original_count,
            "filtered_count": filtered_count,
            "removed_count": removed_count,
            "styles_found": list(found_styles),
            "styles_missing": list(missing_styles),
        },
    )
