# vsg_core/subtitles/style_engine.py
# -*- coding: utf-8 -*-
import hashlib
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

import pysubs2

class StyleEngine:
    """
    Handles loading, parsing, manipulating, and saving subtitle styles
    using the pysubs2 library.
    """
    def __init__(self, subtitle_path: str):
        self.path = Path(subtitle_path)
        self.subs: Optional[pysubs2.SSAFile] = None
        self.load()

    def load(self):
        """Loads the subtitle file, converting SRT to ASS if necessary."""
        try:
            self.subs = pysubs2.load(str(self.path), encoding='utf-8')
        except Exception:
            self.subs = pysubs2.load(str(self.path))

    def save(self):
        """Saves any changes back to the original file path."""
        if self.subs:
            self.subs.save(str(self.path), encoding='utf-8', format_=self.path.suffix[1:])

    def get_style_names(self) -> List[str]:
        """Returns a list of all style names defined in the file."""
        return list(self.subs.styles.keys()) if self.subs else []

    def get_style_attributes(self, style_name: str) -> Dict[str, Any]:
        """Returns a dictionary of attributes for a given style."""
        if not self.subs or style_name not in self.subs.styles:
            return {}

        style = self.subs.styles[style_name]

        def to_qt_hex(c: pysubs2.Color) -> str:
            qt_alpha = 255 - c.a
            return f"#{qt_alpha:02X}{c.r:02X}{c.g:02X}{c.b:02X}"

        # FIX: Removed 'alignment' as it is not editable in the UI
        return {
            "fontname": style.fontname, "fontsize": style.fontsize,
            "primarycolor": to_qt_hex(style.primarycolor),
            "secondarycolor": to_qt_hex(style.secondarycolor),
            "outlinecolor": to_qt_hex(style.outlinecolor),
            "backcolor": to_qt_hex(style.backcolor),
            "bold": style.bold, "italic": style.italic,
            "underline": style.underline, "strikeout": style.strikeout,
            "outline": style.outline, "shadow": style.shadow,
            "marginl": style.marginl, "marginr": style.marginr,
            "marginv": style.marginv,
        }

    def update_style_attributes(self, style_name: str, attributes: Dict[str, Any]):
        """Updates attributes for a given style."""
        if not self.subs or style_name not in self.subs.styles:
            return

        def from_qt_hex(hex_str: str) -> pysubs2.Color:
            hex_str = hex_str.lstrip('#')
            a = int(hex_str[0:2], 16)
            r = int(hex_str[2:4], 16)
            g = int(hex_str[4:6], 16)
            b = int(hex_str[6:8], 16)
            pysubs2_a = 255 - a
            return pysubs2.Color(r, g, b, pysubs2_a)

        style = self.subs.styles[style_name]
        for key, value in attributes.items():
            if key == "alignment": # Explicitly ignore alignment if it ever slips through
                continue
            if "color" in key and isinstance(value, str):
                setattr(style, key, from_qt_hex(value))
            else:
                setattr(style, key, value)

    def get_events(self) -> List[Dict[str, Any]]:
        """Returns all subtitle events, ensuring plaintext is included."""
        if not self.subs: return []

        tag_pattern = re.compile(r'{[^}]+}')

        return [{
                    "line_num": i + 1, "start": event.start, "end": event.end,
                    "style": event.style, "text": event.text,
                    "plaintext": tag_pattern.sub('', event.text)
                }
                for i, event in enumerate(self.subs.events)]

    def get_raw_style_block(self) -> Optional[List[str]]:
        """Extracts the raw [V4+ Styles] block as a list of strings."""
        try:
            content = self.path.read_text(encoding='utf-8-sig')
            in_styles_block = False
            style_lines = []
            for line in content.splitlines():
                line_strip = line.strip()
                if line_strip == '[V4+ Styles]':
                    in_styles_block = True
                elif in_styles_block and line_strip.startswith(('Format:', 'Style:')):
                    style_lines.append(line)
                elif in_styles_block and line_strip == '[Events]':
                    break
            return style_lines if style_lines else None
        except Exception:
            return None

    def set_raw_style_block(self, style_lines: List[str]):
        """Overwrites the [V4+ Styles] block with the provided lines."""
        if not self.subs or not style_lines:
            return
        self.subs.styles.clear()
        temp_subs = pysubs2.SSAFile.from_string("\n".join(['[V4+ Styles]'] + style_lines))
        self.subs.styles = temp_subs.styles.copy()
        self.save()

    @staticmethod
    def merge_styles_from_template(target_path: str, template_path: str) -> bool:
        """
        Merges styles from a template file into a target file.
        Only styles with matching names are updated; unique styles in the target are preserved.
        """
        try:
            target_subs = pysubs2.load(target_path, encoding='utf-8')
            template_subs = pysubs2.load(template_path, encoding='utf-8')

            template_styles = {s.name: s for s in template_subs.styles.values()}
            updated_count = 0

            for style_name, style_object in target_subs.styles.items():
                if style_name in template_styles:
                    target_subs.styles[style_name] = template_styles[style_name].copy()
                    updated_count += 1

            if updated_count > 0:
                target_subs.save(target_path, encoding='utf-8')
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
                if line_strip == '[V4+ Styles]':
                    in_styles_block = True
                elif in_styles_block and line_strip.startswith('Style:'):
                    style_lines.append(line_strip)
                elif in_styles_block and not line_strip:
                    break
            if not style_lines: return None
            return hashlib.sha256('\n'.join(sorted(style_lines)).encode('utf-8')).hexdigest()
        except Exception:
            return None

    @staticmethod
    def get_name_signature(track_name: str) -> Optional[str]:
        """Generates a fallback signature from the track name (e.g., 'Signs [LostYears]')."""
        if not track_name: return None
        sanitized_name = re.sub(r'[\\/*?:"<>|]', "", track_name)
        sanitized_name = sanitized_name.strip()
        if not sanitized_name: return None
        return sanitized_name
