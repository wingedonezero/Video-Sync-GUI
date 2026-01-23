# vsg_core/subtitles/style_engine.py
# -*- coding: utf-8 -*-
"""
Style engine using SubtitleData for subtitle manipulation.

Provides the same API as before but uses the unified SubtitleData
system instead of pysubs2 directly.
"""
import hashlib
import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from .data import SubtitleData, SubtitleStyle
from vsg_core.config import AppConfig


# =============================================================================
# Color Conversion Helpers
# =============================================================================

def ass_color_to_qt(ass_color: str) -> str:
    """
    Convert ASS color format to Qt hex format.

    ASS format: &HAABBGGRR (alpha, blue, green, red)
    Qt format:  #AARRGGBB (alpha, red, green, blue)

    Note: ASS alpha is inverted (00 = opaque, FF = transparent)
          Qt alpha is normal (FF = opaque, 00 = transparent)
    """
    # Remove &H prefix and ensure 8 characters
    color = ass_color.lstrip('&Hh').upper()
    color = color.zfill(8)

    # Parse AABBGGRR
    ass_alpha = int(color[0:2], 16)
    blue = color[2:4]
    green = color[4:6]
    red = color[6:8]

    # Convert ASS alpha (inverted) to Qt alpha (normal)
    qt_alpha = 255 - ass_alpha

    return f"#{qt_alpha:02X}{red}{green}{blue}"


def qt_color_to_ass(qt_color: str) -> str:
    """
    Convert Qt hex format to ASS color format.

    Qt format:  #AARRGGBB (alpha, red, green, blue)
    ASS format: &HAABBGGRR (alpha, blue, green, red)

    Note: Qt alpha is normal (FF = opaque, 00 = transparent)
          ASS alpha is inverted (00 = opaque, FF = transparent)
    """
    # Remove # prefix
    color = qt_color.lstrip('#').upper()
    color = color.zfill(8)

    # Parse AARRGGBB
    qt_alpha = int(color[0:2], 16)
    red = color[2:4]
    green = color[4:6]
    blue = color[6:8]

    # Convert Qt alpha to ASS alpha (inverted)
    ass_alpha = 255 - qt_alpha

    return f"&H{ass_alpha:02X}{blue}{green}{red}"


# =============================================================================
# Style Engine
# =============================================================================

class StyleEngine:
    """
    Handles loading, parsing, manipulating, and saving subtitle styles
    using the SubtitleData system.
    """

    def __init__(self, subtitle_path: str, temp_dir: Optional[Path] = None):
        """
        Initialize the style engine.

        Args:
            subtitle_path: Path to the subtitle file
            temp_dir: Optional temp directory for preview files.
                      If not provided, uses config's style_editor_temp directory.
        """
        self.path = Path(subtitle_path)
        self.data: Optional[SubtitleData] = None
        self._temp_file: Optional[Path] = None

        # Use provided temp_dir or get from config
        if temp_dir:
            self._temp_dir = Path(temp_dir)
        else:
            config = AppConfig()
            self._temp_dir = config.get_style_editor_temp_dir()

        self.load()

    def load(self):
        """Loads the subtitle file into SubtitleData."""
        self.data = SubtitleData.from_file(self.path)

    def save(self):
        """Saves changes to a temp file for preview, not the original."""
        if self.data:
            # Write to temp file for FFmpeg preview
            # Use a unique name based on source file and timestamp
            if self._temp_file is None:
                source_stem = self.path.stem
                unique_id = int(time.time() * 1000) % 1000000
                self._temp_file = self._temp_dir / f"preview_{source_stem}_{unique_id}.ass"
            self.data.save_ass(self._temp_file)

    def save_to_original(self):
        """Saves changes back to the original file."""
        if self.data:
            self.data.save(self.path)

    def get_preview_path(self) -> str:
        """Get path to temp file for preview. Creates/updates it if needed."""
        self.save()
        return str(self._temp_file) if self._temp_file else str(self.path)

    def cleanup(self):
        """Clean up resources - remove temp file and release data."""
        # Remove temp preview file
        if self._temp_file and self._temp_file.exists():
            try:
                self._temp_file.unlink()
            except OSError:
                pass
            self._temp_file = None

        # Release SubtitleData to free memory
        self.data = None

    def get_style_names(self) -> List[str]:
        """Returns a list of all style names defined in the file."""
        return list(self.data.styles.keys()) if self.data else []

    def get_style_attributes(self, style_name: str) -> Dict[str, Any]:
        """Returns a dictionary of attributes for a given style."""
        if not self.data or style_name not in self.data.styles:
            return {}

        style = self.data.styles[style_name]

        return {
            "fontname": style.fontname,
            "fontsize": style.fontsize,
            "primarycolor": ass_color_to_qt(style.primary_color),
            "secondarycolor": ass_color_to_qt(style.secondary_color),
            "outlinecolor": ass_color_to_qt(style.outline_color),
            "backcolor": ass_color_to_qt(style.back_color),
            "bold": style.bold != 0,  # Convert -1/0 to bool
            "italic": style.italic != 0,
            "underline": style.underline != 0,
            "strikeout": style.strike_out != 0,
            "outline": style.outline,
            "shadow": style.shadow,
            "marginl": style.margin_l,
            "marginr": style.margin_r,
            "marginv": style.margin_v,
        }

    def update_style_attributes(self, style_name: str, attributes: Dict[str, Any]):
        """Updates attributes for a given style."""
        if not self.data or style_name not in self.data.styles:
            return

        style = self.data.styles[style_name]

        for key, value in attributes.items():
            if key == "alignment":
                # Explicitly ignore alignment if it ever slips through
                continue
            elif key == "fontname":
                style.fontname = value
            elif key == "fontsize":
                style.fontsize = float(value)
            elif key == "primarycolor":
                style.primary_color = qt_color_to_ass(value)
            elif key == "secondarycolor":
                style.secondary_color = qt_color_to_ass(value)
            elif key == "outlinecolor":
                style.outline_color = qt_color_to_ass(value)
            elif key == "backcolor":
                style.back_color = qt_color_to_ass(value)
            elif key == "bold":
                style.bold = -1 if value else 0
            elif key == "italic":
                style.italic = -1 if value else 0
            elif key == "underline":
                style.underline = -1 if value else 0
            elif key == "strikeout":
                style.strike_out = -1 if value else 0
            elif key == "outline":
                style.outline = float(value)
            elif key == "shadow":
                style.shadow = float(value)
            elif key == "marginl":
                style.margin_l = int(value)
            elif key == "marginr":
                style.margin_r = int(value)
            elif key == "marginv":
                style.margin_v = int(value)

    def get_events(self) -> List[Dict[str, Any]]:
        """Returns all subtitle events."""
        if not self.data:
            return []

        tag_pattern = re.compile(r'{[^}]+}')

        return [
            {
                "line_num": i + 1,
                "start": int(event.start_ms),
                "end": int(event.end_ms),
                "style": event.style,
                "text": event.text,
                "plaintext": tag_pattern.sub('', event.text),
            }
            for i, event in enumerate(self.data.events)
            if not event.is_comment
        ]

    def get_raw_style_block(self) -> Optional[List[str]]:
        """Extracts the raw [V4+ Styles] block as a list of strings."""
        try:
            content = self.path.read_text(encoding='utf-8-sig')
            in_styles_block = False
            style_lines = []
            for line in content.splitlines():
                line_strip = line.strip()
                if line_strip.lower() in ('[v4+ styles]', '[v4 styles]'):
                    in_styles_block = True
                elif in_styles_block and line_strip.startswith(('Format:', 'Style:')):
                    style_lines.append(line)
                elif in_styles_block and line_strip.startswith('['):
                    break
            return style_lines if style_lines else None
        except Exception:
            return None

    def set_raw_style_block(self, style_lines: List[str]):
        """Overwrites the [V4+ Styles] block with the provided lines."""
        if not self.data or not style_lines:
            return

        # Parse the style lines
        format_line = None
        styles = []

        for line in style_lines:
            line = line.strip()
            if line.startswith('Format:'):
                format_line = [f.strip() for f in line[7:].split(',')]
            elif line.startswith('Style:'):
                values = line[6:].split(',')
                if format_line:
                    style = SubtitleStyle.from_format_line(format_line, values)
                    styles.append(style)

        # Update data
        if format_line:
            self.data.styles_format = format_line
        self.data.styles.clear()
        for style in styles:
            self.data.styles[style.name] = style

        self.save()

    def reset_style(self, style_name: str):
        """Reset a single style to its original state by reloading from disk."""
        if not self.data:
            return

        # Reload original file to get the original style
        try:
            original_data = SubtitleData.from_file(self.path)
            if style_name in original_data.styles:
                self.data.styles[style_name] = original_data.styles[style_name]
        except Exception:
            pass  # If reload fails, keep current state

    def reset_all_styles(self):
        """Reset all styles to original state by reloading from disk."""
        if not self.data:
            return

        # Reload original file to get all original styles
        try:
            original_data = SubtitleData.from_file(self.path)
            self.data.styles = original_data.styles
        except Exception:
            pass  # If reload fails, keep current state

    # =========================================================================
    # Script Info Access (for resample dialog)
    # =========================================================================

    @property
    def info(self) -> Dict[str, Any]:
        """Access to script info for compatibility."""
        if self.data:
            return self.data.script_info
        return {}

    def set_info(self, key: str, value: Any):
        """Set script info value."""
        if self.data:
            self.data.script_info[key] = value

    # =========================================================================
    # Static Methods
    # =========================================================================

    @staticmethod
    def merge_styles_from_template(target_path: str, template_path: str) -> bool:
        """
        Merges styles from a template file into a target file.
        Only styles with matching names are updated; unique styles in the target are preserved.
        """
        from copy import deepcopy  # Local import - only needed here
        try:
            target_data = SubtitleData.from_file(target_path)
            template_data = SubtitleData.from_file(template_path)

            updated_count = 0
            for style_name in target_data.styles:
                if style_name in template_data.styles:
                    target_data.styles[style_name] = deepcopy(template_data.styles[style_name])
                    updated_count += 1

            if updated_count > 0:
                target_data.save(target_path)
                return True
            return False
        except Exception as e:
            print(f"Error merging styles: {e}")
            return False

    @staticmethod
    def get_content_signature(subtitle_path: str) -> Optional[str]:
        """Generates a unique hash of the [V4+ Styles] block for content matching."""
        try:
            content = Path(subtitle_path).read_text(encoding='utf-8-sig')
            in_styles_block = False
            style_lines = []
            for line in content.splitlines():
                line_strip = line.strip()
                if line_strip.lower() in ('[v4+ styles]', '[v4 styles]'):
                    in_styles_block = True
                elif in_styles_block and line_strip.startswith('Style:'):
                    style_lines.append(line_strip)
                elif in_styles_block and not line_strip:
                    break
            if not style_lines:
                return None
            return hashlib.sha256('\n'.join(sorted(style_lines)).encode('utf-8')).hexdigest()
        except Exception:
            return None

    @staticmethod
    def get_name_signature(track_name: str) -> Optional[str]:
        """Generates a fallback signature from the track name (e.g., 'Signs [LostYears]')."""
        if not track_name:
            return None
        sanitized_name = re.sub(r'[\\/*?:"<>|]', "", track_name)
        sanitized_name = sanitized_name.strip()
        if not sanitized_name:
            return None
        return sanitized_name
