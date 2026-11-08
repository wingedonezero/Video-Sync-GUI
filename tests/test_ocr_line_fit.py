"""Positioned OCR lines are sized to their disc boxes; regions are left alone."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from vsg_core.subtitles.ocr.line_fit import (
    box_scale_percent,
    load_font_widths,
    text_width,
)
from vsg_core.subtitles.ocr.output import (
    OCRSubtitleResult,
    OutputConfig,
    create_subtitle_data_from_ocr,
)
from vsg_core.subtitles.ocr.pipeline import OCRPipeline


@pytest.fixture
def font_file(tmp_path: Path) -> str:
    """A font whose win metrics (1000) and hhea metrics (2000) differ."""
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space", "a"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: "space", 97: "a"})
    glyph = TTGlyphPen(None).glyph()
    builder.setupGlyf(dict.fromkeys(order, glyph))
    builder.setupHorizontalMetrics(dict.fromkeys(order, (1000, 0)))
    builder.setupHorizontalHeader(ascent=1500, descent=-500)
    builder.setupNameTable({"familyName": "T", "styleName": "Regular"})
    builder.setupOS2(usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    path = tmp_path / "t.ttf"
    builder.save(str(path))
    return str(path)


def _pos(text: str, index: int = 1, x: int = 50, width: int = 300) -> OCRSubtitleResult:
    return OCRSubtitleResult(
        index=index,
        start_ms=1000.0 * index,
        end_ms=1000.0 * index + 900.0,
        text=text,
        zone="pos",
        pos_x=x,
        pos_y=40,
        x=x,
        width=width,
    )


def _events(results: list[OCRSubtitleResult], font_file: str) -> list[str]:
    data = create_subtitle_data_from_ocr(
        ocr_results=results,
        source_file="x.sub",
        source_resolution=(720, 480),
        output_resolution=(720, 480),
        config=OutputConfig(font_size=35, font_file=font_file),
    )
    return [e.text for e in data.events]


def test_width_uses_the_metrics_libass_sizes_fonts_by(font_file: str) -> None:
    widths = load_font_widths(font_file)
    assert widths is not None
    assert text_width(widths, "aa", 35.0) == pytest.approx(70.0)


def test_missing_character_cannot_be_measured(font_file: str) -> None:
    widths = load_font_widths(font_file)
    assert widths is not None
    assert text_width(widths, "ab", 35.0) is None


def test_unreadable_font_is_ignored(tmp_path: Path) -> None:
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(b"not a font")
    assert load_font_widths(bad) is None


@pytest.mark.parametrize(
    ("width", "pos_x", "box", "expected"),
    [
        (500.0, 50, 400, 80),  # shrinks to the box
        (200.0, 50, 350, 175),  # grows to the box
        (400.0, 50, 400, None),  # already the box size
        (900.0, 10, 719, 77),  # capped at the 700 wrap limit
        (600.0, 300, 500, 70),  # capped at the 420 left to the right edge
    ],
)
def test_scale_follows_the_box(
    width: float, pos_x: int, box: int, expected: int | None
) -> None:
    assert box_scale_percent(width, pos_x, box, 720, 10, 10) == expected


def test_no_box_means_no_tag() -> None:
    assert box_scale_percent(900.0, 10, 0, 720, 10, 10) is None


def test_positioned_line_gets_its_box_size(font_file: str) -> None:
    # "aaaa" is 140 wide at 35pt; the box is 70
    assert _events([_pos("aaaa", width=70)], font_file) == [
        "{\\an4\\pos(50,40)\\fscx50\\fscy50}aaaa"
    ]


def test_line_can_grow_to_its_box(font_file: str) -> None:
    assert _events([_pos("aaaa", width=280)], font_file) == [
        "{\\an4\\pos(50,40)\\fscx200\\fscy200}aaaa"
    ]


def test_each_line_follows_its_own_box(font_file: str) -> None:
    texts = _events(
        [_pos("aaaa", index=1, width=70), _pos("aaaa", index=5, width=105)], font_file
    )
    assert "\\fscx50" in texts[0]
    assert "\\fscx75" in texts[1]


def test_no_font_changes_nothing() -> None:
    assert _events([_pos("a" * 40, width=520)], "") == [
        "{\\an4\\pos(50,40)}" + "a" * 40
    ]


def test_unmeasurable_character_changes_nothing(font_file: str) -> None:
    text = "a" * 30 + "b"
    assert _events([_pos(text)], font_file) == [f"{{\\an4\\pos(50,40)}}{text}"]


def test_regions_are_never_scaled(font_file: str) -> None:
    region = OCRSubtitleResult(
        index=1, start_ms=0.0, end_ms=900.0, text="a" * 40, zone="bot", width=300
    )
    assert _events([region], font_file) == ["a" * 40]


def test_scaled_duplicates_still_merge(font_file: str) -> None:
    text = "a" * 21
    first = _pos(text, index=1, width=520)
    second = _pos(text, index=2, width=520)
    second.start_ms = first.end_ms + 20.0
    second.end_ms = second.start_ms + 900.0
    assert len(_events([first, second], font_file)) == 1


def _find(font_name: str, fonts_dir: Path, results: list[OCRSubtitleResult]) -> str:
    stub = SimpleNamespace(settings={"fonts_directory": str(fonts_dir)})
    return OCRPipeline._find_ocr_font_file(stub, font_name, results)  # type: ignore[arg-type]


def test_missing_font_leaves_lines_alone(tmp_path: Path) -> None:
    assert _find("Nope", tmp_path, [_pos("aaaa")]) == ""


def test_fonts_are_not_scanned_without_positioned_lines(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert _find("Nope", missing, []) == ""
