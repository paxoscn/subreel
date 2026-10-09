"""ASS generation: colours, timing, karaoke tags and document structure."""

import pytest

from subreel.ass import (
    AssError,
    AssStyle,
    ass_time,
    build_ass,
    karaoke_cs,
    line_text,
    rgb_to_ass,
    write_ass,
)
from subreel.timings import Line, Word


# ---------------------------------------------------------------------------
# colour conversion
# ---------------------------------------------------------------------------


def test_rgb_to_ass_reverses_to_bgr():
    assert rgb_to_ass("#FFE500") == "&H0000E5FF"
    assert rgb_to_ass("#FFFFFF") == "&H00FFFFFF"
    assert rgb_to_ass("FF0000") == "&H000000FF"
    assert rgb_to_ass("0x00B140") == "&H0040B100"


def test_rgb_to_ass_alpha():
    # ASS alpha is inverted: 0x00 = opaque, 0xFF = fully transparent
    assert rgb_to_ass("#000000", alpha=0xE6) == "&HE6000000"  # ~90% transparent
    assert rgb_to_ass("#000000", alpha=0x00) == "&H00000000"  # fully opaque


def test_rgb_to_ass_short_form():
    assert rgb_to_ass("#abc") == rgb_to_ass("#aabbcc")


@pytest.mark.parametrize("bad", ["#FFFF", "nope", "#GGGGGG", 123])
def test_rgb_to_ass_rejects_garbage(bad):
    with pytest.raises(AssError):
        rgb_to_ass(bad)


# ---------------------------------------------------------------------------
# timing
# ---------------------------------------------------------------------------


def test_ass_time_format():
    assert ass_time(0.0) == "0:00:00.00"
    assert ass_time(0.12) == "0:00:00.12"
    assert ass_time(61.5) == "0:01:01.50"
    assert ass_time(-3) == "0:00:00.00"


def test_karaoke_cs_rounds_and_clamps():
    assert karaoke_cs(Word("x", 0.0, 0.19)) == 19
    assert karaoke_cs(Word("x", 0.0, 0.31)) == 31
    # never zero even for a zero-length word
    assert karaoke_cs(Word("x", 1.0, 1.0)) == 1


# ---------------------------------------------------------------------------
# style
# ---------------------------------------------------------------------------


def test_style_puts_highlight_in_primary_sung_slot():
    # libass: sung == PrimaryColour, unsung == SecondaryColour.
    style = AssStyle(highlight="#FFE500", base="#FFFFFF")
    line = style.style_line()
    fields = line.split(",")
    # Name, Fontname, Fontsize, Primary, Secondary, ...
    assert fields[0].endswith("Default")
    assert fields[3] == "&H0000E5FF"  # highlight -> primary (sung)
    assert fields[4] == "&H00FFFFFF"  # base -> secondary (unsung)
    assert fields[5] == "&H00000000"  # opaque black outline


def test_style_alignment_mapping():
    assert AssStyle(align="bottom").alignment() == 2
    assert AssStyle(align="center").alignment() == 5
    assert AssStyle(align="top").alignment() == 8
    with pytest.raises(AssError):
        AssStyle(align="sideways").alignment()


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def test_line_text_has_kf_per_word():
    line = Line(
        text="你好",
        words=[Word("你", 0.0, 0.19), Word("好", 0.19, 0.50)],
        start=0.0,
        end=0.50,
    )
    text = line_text(line, fade=False)
    assert text == "{\\kf19}你{\\kf31}好"


def test_line_text_fade_prefix():
    line = Line(text="a", words=[Word("a", 0, 0.2)], start=0, end=0.2)
    assert line_text(line, fade=True).startswith("{\\fad(120,120)}")


def test_dialogue_count_matches_lines(tmp_path):
    lines = [
        Line("甲", [Word("甲", 0.0, 0.5)], 0.0, 0.5),
        Line("乙", [Word("乙", 0.5, 1.0)], 0.5, 1.0),
        Line("丙", [Word("丙", 1.0, 1.5)], 1.0, 1.5),
    ]
    doc = build_ass(lines, 1280, 720)
    assert doc.count("Dialogue:") == 3
    assert "Dialogue: 0,0:00:00.00,0:00:00.50,Default,,0,0,0,," in doc


def test_script_info_header(tmp_path):
    doc = build_ass([Line("甲", [Word("甲", 0, 1)], 0, 1)], 1920, 1080)
    assert "PlayResX: 1920" in doc
    assert "PlayResY: 1080" in doc
    assert "WrapStyle: 0" in doc
    assert "ScaledBorderAndShadow: yes" in doc
    assert "[V4+ Styles]" in doc
    assert "[Events]" in doc


def test_write_ass_writes_utf8(tmp_path):
    out = tmp_path / "s.ass"
    write_ass(str(out), [Line("你", [Word("你", 0, 1)], 0, 1)], 1280, 720)
    content = out.read_text(encoding="utf-8")
    assert "你" in content


def test_word_with_braces_is_sanitised():
    line = Line("a", [Word("a{b}", 0, 0.3)], 0, 0.3)
    # braces must not leak a stray override block
    assert "{b}" not in line_text(line, fade=False)