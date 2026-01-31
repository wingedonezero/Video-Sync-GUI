# vsg_qt/subtitle_editor/utils/cps.py
"""
Characters Per Second (CPS) calculation for subtitle editor.

CPS indicates reading speed:
- < 15 CPS: Comfortable reading speed (green)
- 15-20 CPS: Normal (default/no highlight)
- 20-25 CPS: Fast (yellow)
- > 25 CPS: Too fast (red)
"""
import re


def calculate_cps(text: str, duration_ms: float) -> float:
    """
    Calculate characters per second for a subtitle line.

    Args:
        text: Subtitle text (with ASS tags)
        duration_ms: Duration in milliseconds

    Returns:
        Characters per second (0 if duration is 0)
    """
    if duration_ms <= 0:
        return 0.0

    # Strip ASS override tags for character count
    clean_text = strip_ass_tags(text)

    # Count visible characters (excluding \N newlines)
    clean_text = clean_text.replace('\\N', ' ')
    clean_text = clean_text.replace('\\n', ' ')
    clean_text = clean_text.replace('\\h', ' ')

    char_count = len(clean_text.strip())
    duration_seconds = duration_ms / 1000.0

    return char_count / duration_seconds if duration_seconds > 0 else 0.0


def strip_ass_tags(text: str) -> str:
    """
    Remove ASS override tags from text.

    Args:
        text: Text with ASS tags like {\\pos(100,200)\\c&HFFFFFF&}

    Returns:
        Text with tags removed
    """
    # Remove {...} blocks
    return re.sub(r'\{[^}]*\}', '', text)


def cps_color(cps: float) -> tuple[int, int, int]:
    """
    Get color for CPS value (RGB tuple).

    Args:
        cps: Characters per second

    Returns:
        (R, G, B) tuple for the CPS indicator color
    """
    if cps <= 0:
        return (128, 128, 128)  # Gray for invalid/zero
    elif cps < 15:
        return (100, 200, 100)  # Green - comfortable
    elif cps < 20:
        return (200, 200, 200)  # Light gray - normal
    elif cps < 25:
        return (230, 180, 80)   # Yellow/orange - fast
    else:
        return (230, 100, 100)  # Red - too fast


def cps_tooltip(cps: float) -> str:
    """
    Get tooltip text for CPS value.

    Args:
        cps: Characters per second

    Returns:
        Description of the reading speed
    """
    if cps <= 0:
        return "No text or zero duration"
    elif cps < 15:
        return f"{cps:.0f} CPS - Comfortable reading speed"
    elif cps < 20:
        return f"{cps:.0f} CPS - Normal reading speed"
    elif cps < 25:
        return f"{cps:.0f} CPS - Fast reading speed"
    else:
        return f"{cps:.0f} CPS - Too fast to read comfortably"
