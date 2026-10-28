"""Rescale geometry: pictures matched by displayed shape, not stored pixels.

Real cases: Elf 17 (1440x1080 4:3 crop of a 1920x1080 pillarboxed Blu-ray),
Samurai Harem (1024x576 square fansub onto a 720x480 DVD shown 853x480).
"""

from __future__ import annotations

from collections import OrderedDict
from fractions import Fraction

import pytest

from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
from vsg_core.subtitles.operations.style_ops import (
    RescaleGeometry,
    _scale_override_tags,
    apply_rescale,
    rescale_geometry,
)

DVD_SAR = Fraction(853, 720)  # 16:9 NTSC DVD as mkvmerge stores it (853x480)


def _data(play_res: tuple[int, int], *texts: str) -> SubtitleData:
    data = SubtitleData()
    data.script_info["PlayResX"] = str(play_res[0])
    data.script_info["PlayResY"] = str(play_res[1])
    style = SubtitleStyle.default()
    style.margin_l, style.margin_r, style.margin_v = 120, 120, 50
    data.styles = OrderedDict([("Default", style)])
    data.events = [
        SubtitleEvent(start_ms=0.0, end_ms=1000.0, text=t, style="Default")
        for t in texts
    ]
    return data


def test_same_shape_square_is_a_plain_scale() -> None:
    geom = rescale_geometry((1280, 720), (1920, 1080), source_dar=Fraction(16, 9))
    # Blur/3D units stay the script's 720p pixels: LayoutRes keeps them
    assert geom == RescaleGeometry(
        1.5, 1.5, video_x=1.0, video_y=1.0, layout_res=(1280, 720)
    )


def test_unknown_source_video_takes_playres_as_square() -> None:
    assert rescale_geometry((1280, 720), (1920, 1080)) == RescaleGeometry(
        1.5, 1.5, video_x=1.0, video_y=1.0, layout_res=(1280, 720)
    )


def test_elf17_pillarbox_is_a_shift() -> None:
    geom = rescale_geometry((1440, 1080), (1920, 1080), source_dar=Fraction(4, 3))
    assert geom == RescaleGeometry(
        1.0, 1.0, offset_x=240.0, video_x=1.0, video_y=1.0, layout_res=(1920, 1080)
    )


def test_taller_target_gets_top_and_bottom_bars() -> None:
    geom = rescale_geometry((1920, 1080), (1440, 1080), source_dar=Fraction(16, 9))
    # LayoutRes grows by the bars (Aegisub): blur/3D units stay per text
    assert geom == RescaleGeometry(
        0.75, 0.75, offset_y=135.0, video_x=1.0, video_y=1.0, layout_res=(1920, 1440)
    )


def test_samurai_harem_square_onto_anamorphic_dvd() -> None:
    geom = rescale_geometry(
        (1024, 576), (720, 480), source_dar=Fraction(16, 9), target_sar=DVD_SAR
    )
    # x keeps the stored-pixel factor; the glyphs are squeezed by the DVD's
    # pixel aspect so the player's stretch restores their shape. 853x480 is
    # 0.04% narrower than 16:9, which the container says: a 0.13 px bar.
    assert geom.scale_x == pytest.approx(720 / 1024 * 576 / 576.32, rel=1e-3)
    assert geom.scale_y == pytest.approx(480 / 576, rel=1e-3)
    assert geom.offset_x == 0.0
    assert 0 < geom.offset_y < 0.2
    assert geom.text_x == float(1 / DVD_SAR)


def test_anamorphic_source_onto_square_unsqueezes_text() -> None:
    geom = rescale_geometry((720, 480), (1920, 1080), source_dar=Fraction(853, 480))
    assert geom.text_x == float(DVD_SAR)
    assert geom.scale_y == pytest.approx(1080 / 480, rel=1e-3)


def test_layout_res_sets_the_source_glyph_aspect() -> None:
    # A DVD script declaring LayoutRes 853x480 draws square glyphs under
    # libass, so nothing needs un-squeezing on a square target.
    geom = rescale_geometry(
        (720, 480),
        (1920, 1080),
        source_dar=Fraction(853, 480),
        layout_res=(853, 480),
    )
    assert geom.text_x == 1.0


def test_same_shape_square_output_matches_plain_scaling() -> None:
    data = _data(
        (1280, 720),
        "{\\pos(100,200)\\fscx120\\bord2\\xbord1\\fs40\\blur2}Sign",
        "{\\p1}m 0 0 l 10 0 10 10{\\p0}",
    )
    data.script_info["ScaledBorderAndShadow"] = "yes"
    apply_rescale(data, (1920, 1080), source_dar=Fraction(16, 9))
    assert [e.text for e in data.events] == [
        "{\\pos(150,300)\\fscx120\\bord3\\xbord1.5\\fs60\\blur2}Sign",
        "{\\p1}m 0 0 l 15 0 15 15{\\p0}",
    ]
    style = data.styles["Default"]
    assert (style.margin_l, style.margin_r, style.margin_v) == (180, 180, 75)
    assert style.scale_x == 100.0
    # \\blur and 3D rotation stay in 720p units: LayoutRes keeps them
    assert data.script_info["LayoutResX"] == "1280"
    assert data.script_info["LayoutResY"] == "720"


def test_border_goes_into_margins() -> None:
    data = _data((1440, 1080), "plain dialogue")
    apply_rescale(data, (1920, 1080), source_dar=Fraction(4, 3))
    style = data.styles["Default"]
    # Wrap width stays the original 1200 px, centred on the 4:3 picture.
    assert (style.margin_l, style.margin_r, style.margin_v) == (360, 360, 50)
    assert style.fontsize == 48


def test_anamorphic_target_squeezes_text_and_writes_layout_res() -> None:
    data = _data(
        (1024, 576),
        "{\\pos(512,18)\\fscx90}lyric",
        "{\\p1\\pos(0,0)}m 0 0 l 100 0 100 100",
    )
    apply_rescale(data, (720, 480), source_dar=Fraction(16, 9), target_sar=DVD_SAR)
    text_x = float(1 / DVD_SAR)
    assert data.styles["Default"].scale_x == pytest.approx(100 * text_x)
    assert f"\\fscx{90 * text_x:.3f}".rstrip("0") in data.events[0].text
    # Drawings are stretched by \fscx like glyphs, so their x is divided by
    # it: on screen the box keeps its shape.
    geom = rescale_geometry(
        (1024, 576), (720, 480), source_dar=Fraction(16, 9), target_sar=DVD_SAR
    )
    drawing = data.events[1].text.split("}")[1].split()
    assert float(drawing[4]) == pytest.approx(100 * geom.scale_x / text_x, abs=1e-3)
    assert float(drawing[7]) == pytest.approx(100 * geom.scale_y, abs=1e-3)
    # 1024x576's units with PlayRes's shape; libass derives the DVD's glyph
    # aspect from it in every player
    assert data.script_info["LayoutResX"] == "864"
    assert data.script_info["LayoutResY"] == "576"


def test_already_matching_dvd_script_is_left_alone() -> None:
    data = _data((720, 480), "{\\pos(10,10)}x")
    result = apply_rescale(
        data, (720, 480), source_dar=Fraction(853, 480), target_sar=DVD_SAR
    )
    assert result.summary == "Already at target resolution"
    assert data.events[0].text == "{\\pos(10,10)}x"
    assert "LayoutResX" not in data.script_info


def test_unclosed_clip_ends_at_block_end_like_libass() -> None:
    geom = RescaleGeometry(scale_x=1.0, scale_y=1.0, offset_x=240.0)
    text = "{\\b1\\iclip(m 904 852 l 868 724 855 733}HEY!"
    assert _scale_override_tags(text, geom) == (
        "{\\b1\\iclip(m 1144 852 l 1108 724 1095 733}HEY!"
    )


def test_unclosed_transform_ends_at_block_end() -> None:
    geom = RescaleGeometry(scale_x=2.0, scale_y=2.0)
    assert _scale_override_tags("{\\t(0,100,\\fs10}x", geom) == "{\\t(0,100,\\fs20}x"


# --- sizes in video pixels, relative \fs, effects ---


def test_blur_follows_the_videos_not_playres() -> None:
    # Guilty Crown: PlayRes 1280x720 on 1080p video. \blur is in video
    # pixels, so moving onto another 1080p video leaves it as is.
    geom = rescale_geometry(
        (1280, 720), (1920, 1080), source_dar=Fraction(16, 9), source_size=(1920, 1080)
    )
    text = "{\\pos(640,360)\\fs40\\blur3\\be1\\bord2}x"
    assert _scale_override_tags(text, geom) == (
        "{\\pos(960,540)\\fs60\\blur3\\be1\\bord3}x"
    )


def test_unscaled_borders_follow_the_videos() -> None:
    geom = rescale_geometry(
        (1280, 720),
        (1920, 1080),
        source_dar=Fraction(16, 9),
        source_size=(1920, 1080),
        scaled_borders=False,
    )
    assert _scale_override_tags("{\\bord3\\xshad2\\fs40}x", geom) == (
        "{\\bord3\\xshad2\\fs60}x"
    )


def test_border_mode_comes_from_the_script() -> None:
    data = _data((1280, 720), "x")
    data.styles["Default"].outline = 3.0
    apply_rescale(
        data, (1920, 1080), source_dar=Fraction(16, 9), source_size=(1920, 1080)
    )
    assert data.styles["Default"].outline == 3.0  # header missing: video pixels
    data = _data((1280, 720), "x")
    data.script_info["ScaledBorderAndShadow"] = "yes"
    data.styles["Default"].outline = 3.0
    apply_rescale(
        data, (1920, 1080), source_dar=Fraction(16, 9), source_size=(1920, 1080)
    )
    assert data.styles["Default"].outline == 4.5


def test_relative_font_size_steps_are_kept() -> None:
    geom = RescaleGeometry(scale_x=1.5, scale_y=1.5)
    assert _scale_override_tags("{\\fs-2}a{\\fs+3}b{\\fs20}c", geom) == (
        "{\\fs-2}a{\\fs+3}b{\\fs30}c"
    )


def test_scroll_and_banner_effects_scale() -> None:
    data = _data((1440, 1080), "a", "b")
    data.events[0].effect = "Scroll up;100;900;20"
    data.events[1].effect = "Banner;10;1"
    apply_rescale(data, (720, 540), source_dar=Fraction(4, 3))
    assert data.events[0].effect == "Scroll up;50;450;40"
    assert data.events[1].effect == "Banner;20;1"


def test_font_sizes_stay_exact() -> None:
    # Aegisub rounds 35 x 1.5 = 52.5 up to 53; a whole Guilty Crown episode
    # rendered pixel-identical only with 52.5.
    data = _data((1280, 720), "x")
    data.styles["Default"].fontsize = 35.0
    apply_rescale(data, (1920, 1080), source_dar=Fraction(16, 9))
    assert data.styles["Default"].fontsize == 52.5


def test_karaoke_template_lines_are_left_as_written() -> None:
    template = "{\\pos($x,500)\\blur2\\fs!syl.height*2!}"
    data = _data((1280, 720), template, template, template)
    data.events[0].is_comment = True
    data.events[0].effect = "template syl noblank"
    data.events[0].margin_v = 20
    data.events[1].is_comment = True
    data.events[1].effect = "karaoke"  # the karaoke source line is resampled
    data.events[2].effect = "fx"  # generated line, shown on screen
    apply_rescale(data, (1920, 1080), source_dar=Fraction(16, 9))
    assert data.events[0].text == template
    assert data.events[0].margin_v == 20
    assert (
        data.events[1].text
        == data.events[2].text
        == ("{\\pos($x,750)\\blur2\\fs!syl.height*2!}")
    )
