# vsg_core/subtitles/style_filter.py
# -*- coding: utf-8 -*-
"""
Filters subtitle events by style name for creating generated tracks
(e.g., signs-only tracks from full subtitle tracks).

REFACTOR PLAN: Integrate with SubtitleData
==========================================
This module uses pysubs2 directly, bypassing the unified SubtitleData system.
This creates a parallel data path that doesn't integrate with operation tracking
or metadata preservation.

Phase 1: Add methods to SubtitleData
------------------------------------
- SubtitleData.get_style_counts() -> Dict[str, int]
- SubtitleData.filter_by_styles(styles: List[str], mode: str = 'exclude') -> OperationResult

Phase 2: Migrate callers
------------------------
Current usages (search for StyleFilterEngine):
- vsg_core/orchestrator/steps/extract_step.py (lines 246-374) - generated track filtering
- vsg_qt/sync_exclusion_dialog/ui.py - style enumeration for sync exclusion
- vsg_qt/generated_track_dialog/ui.py - style enumeration for track generation
- vsg_qt/job_queue_dialog/logic.py (lines 167, 307, 441) - validation

Phase 3: Deprecate StyleFilterEngine
------------------------------------
Once all callers use SubtitleData, this class can be removed.
The metadata_preserver.py workaround also becomes unnecessary.
"""
from pathlib import Path
from typing import Dict, List, Any
import pysubs2

from .metadata_preserver import SubtitleMetadata


class StyleFilterEngine:
    """
    Filters subtitle events by style name, creating a new subtitle file
    with only the desired events while preserving all other file structure.
    """

    def __init__(self, subtitle_path: str):
        """
        Initialize the filter engine with a subtitle file.

        Args:
            subtitle_path: Path to the subtitle file (ASS/SSA/SRT)
        """
        self.path = Path(subtitle_path)
        self.subs: pysubs2.SSAFile | None = None
        self.metadata: SubtitleMetadata | None = None
        self.load()

    def load(self):
        """Load the subtitle file using pysubs2."""
        # Capture original metadata before pysubs2 processing (skip if it fails)
        try:
            self.metadata = SubtitleMetadata(str(self.path))
            self.metadata.capture()
        except Exception:
            # Metadata capture failed, but we can still proceed with filtering
            self.metadata = None

        # Try multiple encodings
        encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin1', 'shift_jis', 'gbk']

        for encoding in encodings:
            try:
                self.subs = pysubs2.load(str(self.path), encoding=encoding)
                return
            except (UnicodeDecodeError, LookupError):
                continue

        # Last resort: let pysubs2 detect encoding
        try:
            self.subs = pysubs2.load(str(self.path))
        except Exception as e:
            raise Exception(f"Failed to load subtitle file with any encoding: {e}")

    def get_available_styles(self) -> Dict[str, int]:
        """
        Get all available styles and their event counts.

        Returns:
            Dictionary mapping style name to event count
            Example: {'Default': 1243, 'Sign': 47, 'OP': 24}
        """
        if not self.subs:
            return {}

        style_counts: Dict[str, int] = {}
        for event in self.subs.events:
            style_name = event.style
            style_counts[style_name] = style_counts.get(style_name, 0) + 1

        return style_counts

    def filter_by_styles(
        self,
        styles: List[str],
        mode: str = 'exclude',
        output_path: str | None = None
    ) -> Dict[str, Any]:
        """
        Filter events by style names.

        Args:
            styles: List of style names to include or exclude
            mode: 'include' (keep only these styles) or 'exclude' (remove these styles)
            output_path: Path to save filtered file. If None, overwrites original.

        Returns:
            Dictionary with filtering statistics:
            {
                'original_count': int,
                'filtered_count': int,
                'removed_count': int,
                'styles_found': List[str],
                'styles_missing': List[str],
                'verification_passed': bool,
                'verification_issues': List[str]
            }
        """
        if not self.subs:
            return {
                'original_count': 0,
                'filtered_count': 0,
                'removed_count': 0,
                'styles_found': [],
                'styles_missing': [],
                'verification_passed': False,
                'verification_issues': ['Failed to load subtitle file']
            }

        original_count = len(self.subs.events)
        original_events = [self._event_to_dict(e) for e in self.subs.events]

        # Filter events
        if mode == 'include':
            # Keep only events with styles in the list
            self.subs.events = [
                event for event in self.subs.events
                if event.style in styles
            ]
        else:  # mode == 'exclude'
            # Remove events with styles in the list
            self.subs.events = [
                event for event in self.subs.events
                if event.style not in styles
            ]

        filtered_count = len(self.subs.events)
        removed_count = original_count - filtered_count

        # Check which styles were actually found in the file
        available_styles = set(e.style for e in self.subs.events +
                               [pysubs2.SSAEvent(style=s) for s in styles])
        styles_found = [s for s in styles if s in available_styles]
        styles_missing = [s for s in styles if s not in available_styles]

        # Verify that only event lines were removed, no content changed
        filtered_events = [self._event_to_dict(e) for e in self.subs.events]
        verification = self._verify_only_lines_removed(
            original_events,
            filtered_events,
            styles,
            mode
        )

        # Save to output path
        save_path = output_path if output_path else str(self.path)
        self.subs.save(save_path, encoding='utf-8')

        # Restore metadata if we're overwriting the original
        if not output_path and self.metadata:
            self.metadata.validate_and_restore()

        return {
            'original_count': original_count,
            'filtered_count': filtered_count,
            'removed_count': removed_count,
            'styles_found': styles_found,
            'styles_missing': styles_missing,
            'verification_passed': verification['passed'],
            'verification_issues': verification['issues']
        }

    def _event_to_dict(self, event: pysubs2.SSAEvent) -> Dict[str, Any]:
        """Convert an SSAEvent to a comparable dictionary."""
        return {
            'start': event.start,
            'end': event.end,
            'style': event.style,
            'name': event.name,
            'text': event.text,
            'marginl': event.marginl,
            'marginr': event.marginr,
            'marginv': event.marginv,
            'effect': event.effect,
            'type': event.type
        }

    def _verify_only_lines_removed(
        self,
        original_events: List[Dict[str, Any]],
        filtered_events: List[Dict[str, Any]],
        filter_styles: List[str],
        mode: str
    ) -> Dict[str, Any]:
        """
        Verify that only event lines matching the filter were removed,
        and no content was modified in the remaining events.

        Returns:
            {
                'passed': bool,
                'issues': List[str]  # Empty if passed, list of issues if failed
            }
        """
        issues = []

        # Create a mapping of filtered events by their text/timing/style signature
        # Include style in signature to handle events with same timing/text but different styles
        filtered_map = {
            (e['start'], e['end'], e['style'], e['text']): e
            for e in filtered_events
        }

        # Check each original event
        for orig_event in original_events:
            should_be_removed = (
                (mode == 'exclude' and orig_event['style'] in filter_styles) or
                (mode == 'include' and orig_event['style'] not in filter_styles)
            )

            # Include style in signature to match the filtered_map key format
            signature = (orig_event['start'], orig_event['end'], orig_event['style'], orig_event['text'])

            if should_be_removed:
                # This event should have been filtered out
                if signature in filtered_map:
                    issues.append(
                        f"Event was NOT removed as expected: "
                        f"style='{orig_event['style']}' at {orig_event['start']}ms"
                    )
            else:
                # This event should still exist
                if signature not in filtered_map:
                    issues.append(
                        f"Event was incorrectly removed: "
                        f"style='{orig_event['style']}' at {orig_event['start']}ms"
                    )
                else:
                    # Verify content wasn't changed
                    filtered = filtered_map[signature]
                    for key in ['style', 'name', 'marginl', 'marginr', 'marginv', 'effect']:
                        if orig_event[key] != filtered[key]:
                            issues.append(
                                f"Event content changed: "
                                f"{key} changed from '{orig_event[key]}' to '{filtered[key]}' "
                                f"at {orig_event['start']}ms"
                            )

        return {
            'passed': len(issues) == 0,
            'issues': issues
        }

    @staticmethod
    def get_styles_from_file(subtitle_path: str) -> Dict[str, int]:
        """
        Static method to quickly get available styles without creating an engine instance.

        Args:
            subtitle_path: Path to subtitle file

        Returns:
            Dictionary mapping style name to event count
        """
        try:
            engine = StyleFilterEngine(subtitle_path)
            return engine.get_available_styles()
        except Exception:
            return {}
