"""
pysubs2-based style filtering for generated tracks.

This module provides an alternative to SubtitleData filtering using pysubs2,
which may handle certain edge cases differently.
"""

from pathlib import Path
from typing import List, Optional
import shutil


def filter_ass_with_pysubs2(
    input_path: Path,
    output_path: Path,
    styles: List[str],
    mode: str = 'exclude',
    runner=None
) -> dict:
    """
    Filter an ASS file by style using pysubs2.

    Args:
        input_path: Path to input ASS file
        output_path: Path to write filtered output
        styles: List of style names to filter
        mode: 'exclude' (remove these styles) or 'include' (keep only these)
        runner: CommandRunner for logging

    Returns:
        dict with 'success', 'original_count', 'filtered_count', 'error'
    """
    try:
        import pysubs2
    except ImportError:
        return {
            'success': False,
            'error': 'pysubs2 not installed. Install with: pip install pysubs2',
            'original_count': 0,
            'filtered_count': 0,
        }

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    try:
        log(f"[pysubs2] Loading: {input_path.name}")
        subs = pysubs2.load(str(input_path))

        original_count = len(subs.events)
        styles_set = set(styles)

        # Track which styles were found
        found_styles = set()
        for event in subs.events:
            if event.style in styles_set:
                found_styles.add(event.style)

        # Filter events
        if mode == 'include':
            # Keep only events with styles in the list
            subs.events = [e for e in subs.events if e.style in styles_set]
            mode_desc = 'included'
        else:  # mode == 'exclude'
            # Remove events with styles in the list
            subs.events = [e for e in subs.events if e.style not in styles_set]
            mode_desc = 'excluded'

        filtered_count = len(subs.events)
        removed_count = original_count - filtered_count

        log(f"[pysubs2] {mode_desc.capitalize()} {len(found_styles)} style(s), "
            f"removed {removed_count}/{original_count} events")

        # Check for missing styles
        missing_styles = styles_set - found_styles
        if missing_styles:
            log(f"[pysubs2] WARNING: Styles not found: {', '.join(sorted(missing_styles))}")

        # Save
        log(f"[pysubs2] Saving to: {output_path.name}")
        subs.save(str(output_path))

        log(f"[pysubs2] Done - {filtered_count} events remaining")

        return {
            'success': True,
            'original_count': original_count,
            'filtered_count': filtered_count,
            'removed_count': removed_count,
            'styles_found': list(found_styles),
            'styles_missing': list(missing_styles),
            'error': None,
        }

    except Exception as e:
        log(f"[pysubs2] ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        return {
            'success': False,
            'error': str(e),
            'original_count': 0,
            'filtered_count': 0,
        }


def process_generated_track_pysubs2(
    input_path: Path,
    output_path: Path,
    filter_styles: List[str],
    filter_mode: str = 'exclude',
    delay_ms: float = 0.0,
    runner=None
) -> dict:
    """
    Process a generated track using pysubs2 - filter styles and apply delay.

    This is a complete alternative to SubtitleData processing for generated tracks.

    Args:
        input_path: Path to input ASS file
        output_path: Path to write output
        filter_styles: List of style names to filter
        filter_mode: 'exclude' or 'include'
        delay_ms: Delay to apply in milliseconds
        runner: CommandRunner for logging

    Returns:
        dict with processing results
    """
    try:
        import pysubs2
    except ImportError:
        return {
            'success': False,
            'error': 'pysubs2 not installed',
        }

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    try:
        log(f"[pysubs2] === Processing Generated Track ===")
        log(f"[pysubs2] Input: {input_path.name}")
        log(f"[pysubs2] Filter mode: {filter_mode}, styles: {filter_styles}")
        log(f"[pysubs2] Delay: {delay_ms:+.3f}ms")

        # Load
        subs = pysubs2.load(str(input_path))
        original_count = len(subs.events)

        # Log first few events before processing
        log(f"[pysubs2] Loaded {original_count} events")
        for i, event in enumerate(subs.events[:3]):
            log(f"[pysubs2]   Event {i}: {event.start}ms-{event.end}ms style='{event.style}'")

        # Filter by style
        styles_set = set(filter_styles)
        if filter_mode == 'include':
            subs.events = [e for e in subs.events if e.style in styles_set]
        else:
            subs.events = [e for e in subs.events if e.style not in styles_set]

        filtered_count = len(subs.events)
        log(f"[pysubs2] After filtering: {filtered_count} events")

        # Apply delay if non-zero
        if abs(delay_ms) > 0.001:
            log(f"[pysubs2] Applying delay: {delay_ms:+.3f}ms")
            subs.shift(ms=int(round(delay_ms)))

        # Log first few events after processing
        for i, event in enumerate(subs.events[:3]):
            log(f"[pysubs2]   Event {i}: {event.start}ms-{event.end}ms style='{event.style}'")

        # Save
        subs.save(str(output_path))
        log(f"[pysubs2] Saved to: {output_path.name}")

        # Verify by re-reading
        log(f"[pysubs2] Verifying output...")
        verify_subs = pysubs2.load(str(output_path))
        log(f"[pysubs2] Verified: {len(verify_subs.events)} events")
        for i, event in enumerate(verify_subs.events[:3]):
            log(f"[pysubs2]   Verified Event {i}: {event.start}ms-{event.end}ms style='{event.style}'")

        return {
            'success': True,
            'original_count': original_count,
            'filtered_count': filtered_count,
            'delay_applied_ms': delay_ms,
            'error': None,
        }

    except Exception as e:
        log(f"[pysubs2] ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        return {
            'success': False,
            'error': str(e),
        }
