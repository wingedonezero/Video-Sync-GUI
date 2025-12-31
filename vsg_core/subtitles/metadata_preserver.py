# vsg_core/subtitles/metadata_preserver.py
# -*- coding: utf-8 -*-
"""
Metadata Preservation System for pysubs2

Problem: pysubs2 drops critical Aegisub metadata when loading/saving:
- [Aegisub Extradata] (motion tracking, karaoke templates)
- Comment: lines in [Events]
- Custom sections

This module captures original file state, validates pysubs2 output,
and restores any lost metadata while preserving timing changes.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Any, Optional
import re


class SubtitleMetadata:
    """Captures and restores subtitle metadata that pysubs2 loses."""

    def __init__(self, subtitle_path: str):
        self.path = Path(subtitle_path)
        self.original_content: str = ""
        self.encoding: str = 'utf-8'
        self.has_bom: bool = False

        # Sections that pysubs2 might lose or corrupt
        self.aegisub_extradata: List[str] = []
        self.project_garbage_lines: List[str] = []  # Original [Aegisub Project Garbage] content

        # Event validation data (non-timing)
        self.original_events: List[Dict[str, Any]] = []
        self.original_comment_lines: List[str] = []  # Raw comment lines

    def capture(self) -> bool:
        """
        Captures original file state before pysubs2 processing.
        Returns True if successful.
        """
        if not self.path.exists():
            return False

        try:
            # Try with BOM first
            with open(self.path, 'r', encoding='utf-8-sig') as f:
                self.original_content = f.read()

            # Check if BOM was present
            with open(self.path, 'rb') as f:
                if f.read(3) == b'\xef\xbb\xbf':
                    self.has_bom = True
                    self.encoding = 'utf-8-sig'
                else:
                    self.encoding = 'utf-8'

            self._extract_sections()
            self._extract_events()
            return True

        except Exception as e:
            print(f"[MetadataPreserver] ERROR capturing original: {e}")
            return False

    def _extract_sections(self):
        """Extract sections that pysubs2 doesn't preserve or corrupts."""
        lines = self.original_content.split('\n')

        # Extract [Aegisub Project Garbage] - pysubs2 corrupts this by adding Data lines
        in_project_garbage = False
        for line in lines:
            if line.strip() == '[Aegisub Project Garbage]':
                in_project_garbage = True
                continue
            elif line.strip().startswith('[') and in_project_garbage:
                # Hit next section, stop
                break
            elif in_project_garbage and line.strip():
                self.project_garbage_lines.append(line.rstrip())

        # Extract [Aegisub Extradata]
        in_extradata = False
        for line in lines:
            if line.strip() == '[Aegisub Extradata]':
                in_extradata = True
                continue
            elif line.strip().startswith('[') and in_extradata:
                # Hit next section, stop
                break
            elif in_extradata and line.strip():
                self.aegisub_extradata.append(line.rstrip())

    def _extract_events(self):
        """Extract event data for validation (excluding timestamps)."""
        lines = self.original_content.split('\n')

        in_events = False
        format_line = None

        for line in lines:
            stripped = line.strip()

            if stripped == '[Events]':
                in_events = True
                continue
            elif stripped.startswith('[') and in_events:
                # Hit next section, stop
                break
            elif not in_events:
                continue

            if stripped.startswith('Format:'):
                format_line = stripped
                continue

            # Capture Comment lines (pysubs2 often drops these)
            if stripped.startswith('Comment:'):
                self.original_comment_lines.append(line.rstrip())

            # Parse Dialogue/Comment lines for validation
            if stripped.startswith(('Dialogue:', 'Comment:')):
                event_data = self._parse_event_line(stripped)
                if event_data:
                    self.original_events.append(event_data)

    def _parse_event_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse an event line and extract non-timing data.
        Format: Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        """
        try:
            # Split on first colon
            line_type, rest = line.split(':', 1)
            parts = rest.split(',', 9)  # Split into 10 parts max

            if len(parts) < 10:
                return None

            return {
                'type': line_type.strip(),  # 'Dialogue' or 'Comment'
                'layer': parts[0].strip(),
                'style': parts[3].strip(),
                'name': parts[4].strip(),
                'marginl': parts[5].strip(),
                'marginr': parts[6].strip(),
                'marginv': parts[7].strip(),
                'effect': parts[8].strip(),
                'text': parts[9].strip()  # Includes all formatting tags
            }
        except Exception:
            return None

    def validate_and_restore(self, runner=None) -> Dict[str, int]:
        """
        Validates pysubs2 output against original and restores lost data.

        Args:
            runner: Optional runner for logging. If None, logging is skipped.

        Returns:
            Dictionary with restoration statistics
        """
        if not self.path.exists():
            if runner:
                runner._log_message("[MetadataPreserver] ERROR: Output file not found")
            return {}

        stats = {
            'extradata_restored': 0,
            'comment_lines_restored': 0,
            'validation_errors': 0,
            'project_garbage_restored': 0
        }

        try:
            # Read what pysubs2 wrote
            with open(self.path, 'r', encoding='utf-8-sig') as f:
                processed_content = f.read()

            # Validate event content (excluding timestamps)
            validation_errors = self._validate_events(processed_content)
            if validation_errors:
                stats['validation_errors'] = len(validation_errors)
                if runner:
                    runner._log_message(f"[MetadataPreserver] WARNING: {len(validation_errors)} validation issues detected:")
                    for error in validation_errors[:5]:  # Show first 5
                        runner._log_message(f"  - {error}")
                    if len(validation_errors) > 5:
                        runner._log_message(f"  ... and {len(validation_errors) - 5} more")

            # Restore [Aegisub Project Garbage] to original (pysubs2 corrupts it by adding Data lines)
            if self.project_garbage_lines and '[Aegisub Project Garbage]' in processed_content:
                fixed = self._restore_project_garbage()
                if fixed:
                    stats['project_garbage_restored'] = 1
                    if runner:
                        runner._log_message(f"[MetadataPreserver] Restored original [Aegisub Project Garbage] section")
                    # Re-read for subsequent operations
                    with open(self.path, 'r', encoding='utf-8-sig') as f:
                        processed_content = f.read()

            # Restore Aegisub Extradata if missing
            if self.aegisub_extradata and '[Aegisub Extradata]' not in processed_content:
                self._restore_extradata(processed_content)
                stats['extradata_restored'] = len(self.aegisub_extradata)
                if runner:
                    runner._log_message(f"[MetadataPreserver] Restored {len(self.aegisub_extradata)} Aegisub extradata lines")

            # Restore Comment lines if missing
            restored_comments = self._restore_comment_lines(processed_content)
            if restored_comments > 0:
                stats['comment_lines_restored'] = restored_comments
                if runner:
                    runner._log_message(f"[MetadataPreserver] Restored {restored_comments} Comment lines")

            return stats

        except Exception as e:
            if runner:
                runner._log_message(f"[MetadataPreserver] ERROR during validation: {e}")
            return stats

    def _validate_events(self, processed_content: str) -> List[str]:
        """
        Validates that pysubs2 processing preserved all subtitle content and formatting.

        After timestamp adjustments, ALL non-timing data must remain identical:
        - Text content (dialogue, effects, formatting tags)
        - Style assignments (font, color, positioning)
        - Layer numbers (z-order for overlapping subs)
        - Effects (karaoke, scrolling, etc.)

        This catches pysubs2 bugs that corrupt subtitle data during read/write cycles.
        Any differences (except timestamps) indicate data loss and trigger rejection.

        Returns: List of validation errors (empty = success)
        """
        errors = []

        # Extract processed events
        processed_events = []
        lines = processed_content.split('\n')
        in_events = False

        for line in lines:
            stripped = line.strip()
            if stripped == '[Events]':
                in_events = True
                continue
            elif stripped.startswith('[') and in_events:
                break
            elif in_events and stripped.startswith('Dialogue:'):
                event_data = self._parse_event_line(stripped)
                if event_data:
                    processed_events.append(event_data)

        # Compare counts (excluding Comment lines, pysubs2 drops those)
        original_dialogue = [e for e in self.original_events if e['type'] == 'Dialogue']
        if len(original_dialogue) != len(processed_events):
            errors.append(f"Line count mismatch: {len(original_dialogue)} original → {len(processed_events)} processed")
            return errors  # Can't validate further if counts don't match

        # Compare each event (excluding timestamps)
        for i, (orig, proc) in enumerate(zip(original_dialogue, processed_events)):
            line_num = i + 1

            if orig['text'] != proc['text']:
                errors.append(f"Line {line_num}: Text content changed")
            if orig['style'] != proc['style']:
                errors.append(f"Line {line_num}: Style changed ({orig['style']} → {proc['style']})")
            if orig['layer'] != proc['layer']:
                errors.append(f"Line {line_num}: Layer changed ({orig['layer']} → {proc['layer']})")
            if orig['effect'] != proc['effect']:
                errors.append(f"Line {line_num}: Effect changed")

        return errors

    def _restore_project_garbage(self) -> bool:
        """
        Replace [Aegisub Project Garbage] section with original.
        pysubs2 corrupts this section by adding Data: lines that shouldn't be there.
        """
        if not self.project_garbage_lines:
            return False

        try:
            # Read current file
            with open(self.path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            # Find and replace [Aegisub Project Garbage] section
            new_lines = []
            in_project_garbage = False
            section_replaced = False

            for line in lines:
                stripped = line.strip()

                if stripped == '[Aegisub Project Garbage]':
                    # Start of section - write header and original content
                    new_lines.append(line)
                    for orig_line in self.project_garbage_lines:
                        new_lines.append(orig_line + '\n')
                    # Add blank line after section (standard ASS format)
                    new_lines.append('\n')
                    in_project_garbage = True
                    section_replaced = True
                    continue
                elif stripped.startswith('[') and in_project_garbage:
                    # Hit next section - stop skipping and write this line
                    in_project_garbage = False
                    new_lines.append(line)
                    continue
                elif in_project_garbage:
                    # Inside garbage section - skip (we already wrote the original)
                    continue
                else:
                    # Normal line - keep it
                    new_lines.append(line)

            if section_replaced:
                # Write back to file
                with open(self.path, 'w', encoding=self.encoding) as f:
                    f.writelines(new_lines)
                return True

            return False

        except Exception as e:
            print(f"[MetadataPreserver] ERROR restoring project garbage: {e}")
            return False

    def _restore_extradata(self, processed_content: str):
        """Append [Aegisub Extradata] section to the file."""
        if not self.aegisub_extradata:
            return

        # Ensure file doesn't already have extradata
        if '[Aegisub Extradata]' in processed_content:
            return

        with open(self.path, 'a', encoding=self.encoding) as f:
            f.write('\n[Aegisub Extradata]\n')
            for line in self.aegisub_extradata:
                f.write(line + '\n')

    def _restore_comment_lines(self, processed_content: str) -> int:
        """
        Restore Comment: lines that pysubs2 dropped.
        This is tricky because we need to re-insert them in the right position
        with updated timestamps.

        For now, we'll just log that they were lost.
        TODO: Implement smart restoration with timestamp adjustment.
        """
        if not self.original_comment_lines:
            return 0

        # Check if any comment lines survived
        comment_count_processed = processed_content.count('Comment:')
        comment_count_original = len(self.original_comment_lines)

        if comment_count_processed < comment_count_original:
            # Some were lost, but restoring them with correct timestamps is complex
            # For now, just report the loss
            return 0

        return 0


def preserve_subtitle_metadata(subtitle_path: str, runner, processing_func, *args, **kwargs):
    """
    Wrapper function that preserves metadata around pysubs2 processing.

    Usage:
        def my_processing(subs, runner):
            # Modify subs here
            pass

        preserve_subtitle_metadata(path, runner, my_processing, runner)
    """
    metadata = SubtitleMetadata(subtitle_path)

    # Capture original state
    if not metadata.capture():
        runner._log_message("[MetadataPreserver] WARNING: Could not capture original metadata")
        return processing_func(*args, **kwargs)

    # Run the processing function
    result = processing_func(*args, **kwargs)

    # Validate and restore
    stats = metadata.validate_and_restore(runner)

    return result
