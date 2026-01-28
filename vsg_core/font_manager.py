# vsg_core/font_manager.py
# -*- coding: utf-8 -*-
"""
Font Manager

Handles font scanning, parsing, and replacement tracking for subtitle files.
"""
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Set, Any
import re

try:
    from fontTools.ttLib import TTFont
    FONTTOOLS_AVAILABLE = True
except ImportError:
    FONTTOOLS_AVAILABLE = False


class FontInfo:
    """Information about a font file."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.filename = file_path.name
        self.family_name: str = ""
        self.subfamily: str = ""  # Regular, Bold, Italic, etc.
        self.full_name: str = ""
        self.postscript_name: str = ""
        self.is_valid: bool = False
        self.error: Optional[str] = None

        self._parse_font()

    def _parse_font(self):
        """Parse font file to extract metadata."""
        if not FONTTOOLS_AVAILABLE:
            # Fallback: use filename
            self.family_name = self.file_path.stem
            self.full_name = self.file_path.stem
            self.is_valid = True
            return

        try:
            font = TTFont(str(self.file_path), fontNumber=0)
            name_table = font.get('name')

            if name_table:
                # Name IDs: 1=Family, 2=Subfamily, 4=Full Name, 6=PostScript Name
                for record in name_table.names:
                    try:
                        text = record.toUnicode()
                    except (UnicodeDecodeError, AttributeError):
                        continue

                    if record.nameID == 1 and not self.family_name:
                        self.family_name = text
                    elif record.nameID == 2 and not self.subfamily:
                        self.subfamily = text
                    elif record.nameID == 4 and not self.full_name:
                        self.full_name = text
                    elif record.nameID == 6 and not self.postscript_name:
                        self.postscript_name = text

            font.close()

            # Fallback to filename if no family name found
            if not self.family_name:
                self.family_name = self.file_path.stem

            if not self.full_name:
                self.full_name = self.family_name

            self.is_valid = True

        except Exception as e:
            self.error = str(e)
            self.family_name = self.file_path.stem
            self.full_name = self.file_path.stem
            self.is_valid = False

    def __repr__(self):
        return f"FontInfo(family='{self.family_name}', style='{self.subfamily}', file='{self.filename}')"


class FontScanner:
    """Scans directories for font files."""

    # Include both lowercase and uppercase extensions
    FONT_EXTENSIONS = {'.ttf', '.otf', '.ttc', '.woff', '.woff2',
                       '.TTF', '.OTF', '.TTC', '.WOFF', '.WOFF2'}

    def __init__(self, fonts_dir: Path):
        self.fonts_dir = Path(fonts_dir)
        self._font_cache: Dict[str, FontInfo] = {}

    def scan(self, include_subdirs: bool = True) -> List[FontInfo]:
        """
        Scan the fonts directory for font files.

        Args:
            include_subdirs: Whether to scan subdirectories

        Returns:
            List of FontInfo objects
        """
        if not self.fonts_dir.exists():
            return []

        fonts = []
        pattern = '**/*' if include_subdirs else '*'

        # Collect all font files
        seen_paths = set()
        for ext in self.FONT_EXTENSIONS:
            for font_path in self.fonts_dir.glob(f"{pattern}{ext}"):
                if font_path.is_file():
                    # Normalize path to avoid duplicates from case variations
                    path_key = str(font_path.resolve())
                    if path_key in seen_paths:
                        continue
                    seen_paths.add(path_key)

                    # Use cache if available
                    if path_key not in self._font_cache:
                        self._font_cache[path_key] = FontInfo(font_path)
                    fonts.append(self._font_cache[path_key])

        return fonts

    def get_font_by_family(self, family_name: str) -> List[FontInfo]:
        """Get all fonts matching a family name."""
        fonts = self.scan()
        return [f for f in fonts if f.family_name.lower() == family_name.lower()]

    def get_font_families(self) -> Dict[str, List[FontInfo]]:
        """Get fonts grouped by family name."""
        fonts = self.scan()
        families: Dict[str, List[FontInfo]] = {}

        for font in fonts:
            family = font.family_name
            if family not in families:
                families[family] = []
            families[family].append(font)

        return families

    def clear_cache(self):
        """Clear the font cache."""
        self._font_cache.clear()


class SubtitleFontAnalyzer:
    """Analyzes fonts used in subtitle files."""

    def __init__(self, subtitle_path: str):
        self.subtitle_path = Path(subtitle_path)
        self._fonts_by_style: Dict[str, Set[str]] = {}
        self._inline_fonts: Set[str] = set()

    def analyze(self) -> Dict[str, Any]:
        """
        Analyze the subtitle file to find all fonts used.

        Returns:
            Dictionary with font usage information
        """
        from vsg_core.subtitles.data import SubtitleData

        try:
            data = SubtitleData.from_file(self.subtitle_path)
        except Exception as e:
            return {'error': str(e), 'fonts': {}, 'inline_fonts': []}

        # Analyze style fonts
        self._fonts_by_style.clear()
        fonts_to_styles: Dict[str, List[str]] = {}

        for style_name, style in data.styles.items():
            font_name = style.fontname
            if font_name not in fonts_to_styles:
                fonts_to_styles[font_name] = []
            fonts_to_styles[font_name].append(style_name)

            # Track which styles use which fonts
            if style_name not in self._fonts_by_style:
                self._fonts_by_style[style_name] = set()
            self._fonts_by_style[style_name].add(font_name)

        # Analyze inline font overrides (\fn tags)
        self._inline_fonts.clear()
        fn_pattern = re.compile(r'\\fn([^\\}]+)')

        for event in data.events:
            matches = fn_pattern.findall(event.text)
            for font_name in matches:
                self._inline_fonts.add(font_name.strip())

        # Build font info with usage details
        fonts_info = {}
        for font_name, styles in fonts_to_styles.items():
            fonts_info[font_name] = {
                'styles': styles,
                'style_count': len(styles),
                'has_bold_styles': any(
                    data.styles[s].bold != 0 for s in styles if s in data.styles
                ),
                'has_italic_styles': any(
                    data.styles[s].italic != 0 for s in styles if s in data.styles
                ),
            }

        return {
            'fonts': fonts_info,
            'inline_fonts': list(self._inline_fonts),
            'total_styles': len(data.styles),
            'total_events': len(data.events),
        }

    def get_styles_using_font(self, font_name: str) -> List[str]:
        """Get list of styles that use a specific font."""
        styles = []
        for style_name, fonts in self._fonts_by_style.items():
            if font_name in fonts:
                styles.append(style_name)
        return styles


class FontReplacementManager:
    """Manages font replacement operations (keyed by style name)."""

    def __init__(self, fonts_dir: Path):
        self.fonts_dir = Path(fonts_dir)
        self.scanner = FontScanner(fonts_dir)
        self._replacements: Dict[str, Dict[str, Any]] = {}

    def add_replacement(
        self,
        style_name: str,
        original_font: str,
        new_font_name: str,
        font_file_path: Optional[Path]
    ) -> str:
        """
        Add a font replacement for a specific style.

        Args:
            style_name: The style name to replace the font for
            original_font: The original font name in the style
            new_font_name: The new font name (internal font name)
            font_file_path: Path to the replacement font file

        Returns:
            The style name as the key
        """
        self._replacements[style_name] = {
            'original_font': original_font,
            'new_font_name': new_font_name,
            'font_file_path': str(font_file_path) if font_file_path else None,
        }
        return style_name

    def remove_replacement(self, style_name: str) -> bool:
        """Remove a font replacement by style name."""
        if style_name in self._replacements:
            del self._replacements[style_name]
            return True
        return False

    def get_replacements(self) -> Dict[str, Dict[str, Any]]:
        """Get all current replacements."""
        return self._replacements.copy()

    def clear_replacements(self):
        """Clear all replacements."""
        self._replacements.clear()

    def apply_to_track_data(self, track_data: Dict) -> Dict:
        """
        Apply font replacements to track data for job processing.

        Args:
            track_data: The track data dictionary

        Returns:
            Updated track data with font_replacements key
        """
        if self._replacements:
            track_data['font_replacements'] = self._replacements.copy()
        return track_data

    def validate_replacement_files(self) -> List[str]:
        """
        Validate that all replacement font files exist.

        Returns:
            List of error messages (empty if all valid)
        """
        errors = []
        for style_name, replacement in self._replacements.items():
            font_path = replacement.get('font_file_path')
            if font_path and not Path(font_path).exists():
                errors.append(
                    f"Font file not found for style '{style_name}': {font_path}"
                )
        return errors

    def copy_fonts_to_temp(self, temp_dir: Path) -> List[Path]:
        """
        Copy all replacement font files to a temp directory.

        Args:
            temp_dir: The temp directory to copy to

        Returns:
            List of paths to copied font files
        """
        fonts_temp_dir = temp_dir / 'replacement_fonts'
        fonts_temp_dir.mkdir(parents=True, exist_ok=True)

        copied_files = []
        for replacement in self._replacements.values():
            font_path = replacement.get('font_file_path')
            if font_path:
                src_path = Path(font_path)
                if src_path.exists():
                    dst_path = fonts_temp_dir / src_path.name
                    shutil.copy2(src_path, dst_path)
                    copied_files.append(dst_path)

        return copied_files


def validate_font_replacements(
    replacements: Dict[str, Dict[str, Any]],
    subtitle_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate font replacements (keyed by style name).

    Args:
        replacements: Dictionary of font replacements keyed by style name
        subtitle_path: Optional path to subtitle file for style validation

    Returns:
        Dictionary with:
        - 'valid': bool - True if all validations pass
        - 'missing_files': List of missing font file paths
        - 'missing_styles': List of styles not found in subtitle file
        - 'warnings': List of warning messages (non-blocking)
        - 'errors': List of error messages (blocking)
    """
    result = {
        'valid': True,
        'missing_files': [],
        'missing_styles': [],
        'warnings': [],
        'errors': []
    }

    if not replacements:
        return result

    # Check font files exist
    for style_name, repl_data in replacements.items():
        font_file = repl_data.get('font_file_path')
        if font_file:
            if not Path(font_file).exists():
                result['missing_files'].append(font_file)
                result['errors'].append(f"Font file not found for style '{style_name}': {Path(font_file).name}")
                result['valid'] = False

    # Check if styles exist in subtitle file (non-blocking warning)
    if subtitle_path and Path(subtitle_path).exists():
        try:
            from vsg_core.subtitles.data import SubtitleData
            data = SubtitleData.from_file(subtitle_path)
            existing_styles = set(data.styles.keys())

            for style_name in replacements.keys():
                if style_name not in existing_styles:
                    result['missing_styles'].append(style_name)
                    result['warnings'].append(
                        f"Style '{style_name}' not found in subtitle file"
                    )
        except Exception as e:
            result['warnings'].append(f"Could not analyze subtitle file: {e}")

    return result


def apply_font_replacements_to_subtitle(
    subtitle_path: str,
    replacements: Dict[str, Dict[str, Any]]
) -> int:
    """
    Apply font replacements to a subtitle file.

    Args:
        subtitle_path: Path to the subtitle file
        replacements: Dictionary of font replacements keyed by style name:
            {
                "StyleName": {
                    "original_font": "OriginalFontName",
                    "new_font_name": "NewFontName",
                    "font_file_path": "..." (optional)
                }
            }

    Returns:
        Number of styles modified
    """
    from vsg_core.subtitles.data import SubtitleData

    data = SubtitleData.from_file(subtitle_path)
    modified_count = 0

    # Apply replacements by style name
    for style_name, style in data.styles.items():
        if style_name in replacements:
            repl_data = replacements[style_name]
            new_font = repl_data['new_font_name']
            style.fontname = new_font
            modified_count += 1

    # Build font mapping for inline \fn tags
    # Map original_font -> new_font_name for any replacement
    font_mapping = {}
    for repl_data in replacements.values():
        original = repl_data.get('original_font')
        new_font = repl_data.get('new_font_name')
        if original and new_font:
            font_mapping[original] = new_font

    # Replace inline \fn tags using the font mapping
    if font_mapping:
        fn_pattern = re.compile(r'\\fn([^\\}]+)')

        for event in data.events:
            def replace_fn(match):
                font_name = match.group(1).strip()
                if font_name in font_mapping:
                    return f"\\fn{font_mapping[font_name]}"
                return match.group(0)

            new_text = fn_pattern.sub(replace_fn, event.text)
            if new_text != event.text:
                event.text = new_text

    data.save(subtitle_path)
    return modified_count
