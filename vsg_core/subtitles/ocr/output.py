# vsg_core/subtitles/ocr/output.py
"""
OCR Output — SubtitleData Conversion

Converts OCR results into SubtitleData for the unified subtitle pipeline.
The actual ASS/SRT file writing is handled by the shared writers in
vsg_core/subtitles/writers/ (ass_writer.py, srt_writer.py).

Position handling:
    - Bottom subtitles (default): Default style (alignment 2)
    - Top subtitles (< 40% of frame): Top style (alignment 8)
    Anime VobSub only uses top/bottom positioning in practice.

Post-processing:
    - Consecutive Top events with identical text are merged to prevent
      flickering when VobSub re-emits the same sign across multiple images.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import SubtitleData


@dataclass(slots=True)
class OutputConfig:
    """Configuration for subtitle output."""

    # Position handling
    preserve_positions: bool = True
    bottom_threshold_percent: float = 75.0  # Below this = not bottom
    top_threshold_percent: float = 40.0  # Below this = top

    # ASS style settings
    style_name: str = "Default"
    font_name: str = "Arial"
    font_size: int = 48
    primary_color: str = "&H00FFFFFF"  # White
    outline_color: str = "&H00000000"  # Black
    outline_width: float = 2.0
    shadow_depth: float = 1.0
    margin_v: int = 30  # Vertical margin from bottom

    # Video resolution (for PlayRes)
    video_width: int = 1920
    video_height: int = 1080


@dataclass(slots=True)
class LineRegion:
    """A single OCR line with its classified screen region."""

    text: str
    region: str  # "top" or "bottom"
    y_center: float = 0.0  # Y center in source image pixels


@dataclass(slots=True)
class OCRSubtitleResult:
    """
    Extended subtitle result with all OCR metadata for SubtitleData conversion.

    This carries all the data needed to populate SubtitleEvent.ocr and OCRMetadata.
    """

    index: int
    start_ms: float  # Float for precision
    end_ms: float
    text: str

    # OCR metadata
    confidence: float = 0.0
    raw_ocr_text: str = ""
    fixes_applied: dict = field(default_factory=dict)
    unknown_words: list[str] = field(default_factory=list)

    # Position data
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    frame_width: int = 0
    frame_height: int = 0

    # VobSub specific
    is_forced: bool = False
    subtitle_colors: list[list[int]] = field(default_factory=list)
    dominant_color: list[int] = field(default_factory=list)

    # Per-line region classifications from pipeline
    line_regions: list[LineRegion] = field(default_factory=list)

    # Debug image reference
    debug_image: str = ""  # e.g., "sub_0000.png"


def create_subtitle_data_from_ocr(
    ocr_results: list[OCRSubtitleResult],
    source_file: str,
    engine: str = "tesseract",
    language: str = "eng",
    source_format: str = "vobsub",
    source_resolution: tuple[int, int] = (720, 480),
    output_resolution: tuple[int, int] = (1920, 1080),
    master_palette: list[list[int]] | None = None,
    config: OutputConfig | None = None,
) -> "SubtitleData":
    """
    Create SubtitleData from OCR results.

    This is the unified entry point for OCR -> SubtitleData conversion.
    All OCR metadata is preserved on each event.

    Args:
        ocr_results: List of OCRSubtitleResult with full metadata
        source_file: Original source file path
        engine: OCR engine used
        language: OCR language
        source_format: Source subtitle format (vobsub, pgs)
        source_resolution: Source video resolution
        output_resolution: Target video resolution
        master_palette: VobSub master palette (16 colors)
        config: Output configuration

    Returns:
        SubtitleData with all OCR metadata populated
    """
    from collections import OrderedDict

    from ..data import (
        OCREventData,
        OCRMetadata,
        SubtitleData,
        SubtitleEvent,
        SubtitleStyle,
    )

    config = config or OutputConfig()

    # Create SubtitleData
    data = SubtitleData()
    data.source_path = Path(source_file)
    data.source_format = "ocr"
    data.encoding = "utf-8"

    # Set up script info
    data.script_info = OrderedDict(
        [
            ("Title", "OCR Output"),
            ("ScriptType", "v4.00+"),
            ("WrapStyle", "0"),
            ("ScaledBorderAndShadow", "yes"),
            ("PlayResX", str(output_resolution[0])),
            ("PlayResY", str(output_resolution[1])),
        ]
    )

    # Create default style
    default_style = SubtitleStyle(
        name="Default",
        fontname=config.font_name,
        fontsize=float(config.font_size),
        primary_color=config.primary_color,
        outline_color=config.outline_color,
        outline=config.outline_width,
        shadow=config.shadow_depth,
        alignment=2,  # Bottom center
        margin_v=config.margin_v,
    )

    # Create top style for positioned subtitles
    top_style = SubtitleStyle(
        name="Top",
        fontname=config.font_name,
        fontsize=float(config.font_size),
        primary_color=config.primary_color,
        outline_color=config.outline_color,
        outline=config.outline_width,
        shadow=config.shadow_depth,
        alignment=8,  # Top center
        margin_v=config.margin_v,
    )

    data.styles = OrderedDict(
        [
            ("Default", default_style),
            ("Top", top_style),
        ]
    )

    # Track statistics for OCRMetadata
    confidences = []
    total_fixes = 0
    fixes_by_type: dict = {}
    unknown_words_map: dict = {}  # word -> first occurrence info
    positioned_count = 0

    # Region-to-style mapping (top/bottom only — anime VobSub standard)
    _region_styles = {"top": "Top", "bottom": "Default"}

    # Convert each OCR result to SubtitleEvent(s)
    for result in ocr_results:
        # Build OCR metadata (shared across split events)
        ocr_event_data = OCREventData(
            index=result.index,
            image=result.debug_image or f"sub_{result.index:04d}.png",
            confidence=result.confidence,
            raw_text=result.raw_ocr_text,
            fixes_applied=dict(result.fixes_applied),
            unknown_words=list(result.unknown_words),
            x=result.x,
            y=result.y,
            width=result.width,
            height=result.height,
            frame_width=result.frame_width,
            frame_height=result.frame_height,
            is_forced=result.is_forced,
            subtitle_colors=result.subtitle_colors,
            dominant_color=result.dominant_color,
        )

        # Check if we need to split into multiple events by region
        has_multiple = (
            config.preserve_positions
            and result.line_regions
            and len({lr.region for lr in result.line_regions}) > 1
        )

        if has_multiple:
            # Group lines by region and create separate events
            region_groups: dict[str, list[LineRegion]] = {}
            for lr in result.line_regions:
                region_groups.setdefault(lr.region, []).append(lr)

            for region in ("top", "bottom"):
                if region not in region_groups:
                    continue
                region_text = "\\N".join(lr.text for lr in region_groups[region])
                event = SubtitleEvent(
                    start_ms=float(result.start_ms),
                    end_ms=float(result.end_ms),
                    text=region_text,
                    style=_region_styles[region],
                    original_index=result.index,
                )
                event.ocr = ocr_event_data
                data.events.append(event)
        elif config.preserve_positions and result.line_regions:
            # All lines in same region — use that region's style
            region = result.line_regions[0].region
            text = result.text.replace("\n", "\\N")
            event = SubtitleEvent(
                start_ms=float(result.start_ms),
                end_ms=float(result.end_ms),
                text=text,
                style=_region_styles.get(region, "Default"),
                original_index=result.index,
            )
            event.ocr = ocr_event_data
            data.events.append(event)
        else:
            # No line_regions or preserve disabled — default bottom
            text = result.text.replace("\n", "\\N")
            event = SubtitleEvent(
                start_ms=float(result.start_ms),
                end_ms=float(result.end_ms),
                text=text,
                style="Default",
                original_index=result.index,
            )
            event.ocr = ocr_event_data
            data.events.append(event)

        # Track statistics
        confidences.append(result.confidence)

        for fix_name, count in result.fixes_applied.items():
            total_fixes += count
            fixes_by_type[fix_name] = fixes_by_type.get(fix_name, 0) + count

        for word in result.unknown_words:
            if word not in unknown_words_map:
                unknown_words_map[word] = {
                    "word": word,
                    "first_seen_index": result.index,
                    "occurrences": 0,
                }
            unknown_words_map[word]["occurrences"] += 1

        # Check if positioned
        if result.frame_height > 0:
            y_percent = (result.y / result.frame_height) * 100
            if y_percent < config.bottom_threshold_percent:
                positioned_count += 1

    # Create document-level OCR metadata
    data.ocr_metadata = OCRMetadata(
        engine=engine,
        language=language,
        source_format=source_format,
        source_file=source_file,
        source_resolution=list(source_resolution),
        master_palette=master_palette or [],
        total_subtitles=len(ocr_results),
        successful=len([r for r in ocr_results if r.text.strip()]),
        failed=len([r for r in ocr_results if not r.text.strip()]),
        average_confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        min_confidence=min(confidences) if confidences else 0.0,
        max_confidence=max(confidences) if confidences else 0.0,
        total_fixes_applied=total_fixes,
        positioned_subtitles=positioned_count,
        fixes_by_type=fixes_by_type,
        unknown_words=list(unknown_words_map.values()),
    )

    # Merge consecutive Top events with identical text to prevent flickering.
    # VobSub re-emits the same top text (signs, titles) each time the bottom
    # dialogue changes, creating duplicate Top events with tiny gaps.
    if config.preserve_positions:
        _merge_consecutive_top_events(data.events)

    return data


def _merge_consecutive_top_events(events: list) -> None:
    """
    Merge consecutive Top-styled events that have identical text.

    VobSub creates a new image each time bottom dialogue changes, even when
    top text (signs, titles) stays the same. This produces duplicate Top
    events with tiny gaps that cause flickering in players.

    Merges in-place: extends the first event's end_ms to cover all
    consecutive duplicates, then removes the duplicates.

    Uses a max gap of 200ms — anything larger likely means the sign
    actually disappeared and reappeared.
    """
    max_gap_ms = 200.0
    to_remove: list[int] = []
    i = 0
    while i < len(events):
        if events[i].style != "Top":
            i += 1
            continue

        # Found a Top event — look ahead for consecutive duplicates
        j = i + 1
        while j < len(events):
            if (
                events[j].style == "Top"
                and events[j].text == events[i].text
                and events[j].start_ms - events[i].end_ms <= max_gap_ms
            ):
                # Extend the first event to cover this duplicate
                events[i].end_ms = max(events[i].end_ms, events[j].end_ms)
                to_remove.append(j)
                j += 1
            elif events[j].style == "Top":
                # Different Top text or too large a gap — stop
                break
            else:
                # Skip non-Top events (Default dialogue between Top events)
                j += 1

        i = j if j > i + 1 else i + 1

    # Remove merged duplicates in reverse order to preserve indices
    for idx in reversed(to_remove):
        del events[idx]
