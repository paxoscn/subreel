"""ASS (Advanced SubStation Alpha) subtitle generation with word karaoke.

Colour semantics
----------------

libass draws a ``\\kf`` (sweep) karaoke segment with two colours:

* the **not-yet-sung** part uses ``SecondaryColour``;
* the **already-sung** part uses ``PrimaryColour``.

We verified this against the bundled libass (ffmpeg 4.4) by rendering a probe.
The product requirement is the usual karaoke direction — *the word currently
being sung and every word before it are shown in the highlight colour* — so the
highlight colour (default ``#FFE500`` yellow) is written to **PrimaryColour**
and the resting/base colour (white) to **SecondaryColour**.  ``--highlight``
therefore drives ``PrimaryColour``.

Note this is the *opposite* assignment from a naive reading of some ASS
documentation that treats ``PrimaryColour`` as the resting colour; the tests
lock the actual bytes emitted so the behaviour cannot silently regress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .timings import Line, Word, _needs_space
from . import __version__

__all__ = [
    "AssError",
    "AssStyle",
    "rgb_to_ass",
    "ass_time",
    "karaoke_cs",
    "build_ass",
    "write_ass",
]


class AssError(ValueError):
    """Raised when an ASS colour or parameter cannot be interpreted."""


# ---------------------------------------------------------------------------
# Colour conversion
# ---------------------------------------------------------------------------

_NAMED_COLOURS = {
    "white": "FFFFFF",
    "black": "000000",
    "red": "FF0000",
    "green": "00FF00",
    "blue": "0000FF",
    "yellow": "FFE500",
    "cyan": "00FFFF",
    "magenta": "FF00FF",
}


def _normalise_rgb(value: str) -> Tuple[int, int, int]:
    """Parse ``#RRGGBB`` / ``0xRRGGBB`` / ``RRGGBB`` / ``#RGB`` into RGB bytes."""
    if not isinstance(value, str):
        raise AssError("colour must be a string like '#FFE500', got %r" % (value,))
    raw = value.strip()
    if raw.lower() in _NAMED_COLOURS:
        raw = _NAMED_COLOURS[raw.lower()]
    if raw.startswith("#"):
        raw = raw[1:]
    elif raw[:2].lower() == "0x":
        raw = raw[2:]
    if len(raw) == 3:  # #abc -> #aabbcc
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raise AssError(
            "colour %r is not a valid #RRGGBB / 0xRRGGBB value" % (value,)
        )
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        raise AssError("colour %r contains non-hexadecimal digits" % (value,))
    return r, g, b


def rgb_to_ass(value: str, alpha: int = 0x00) -> str:
    """Convert an RGB colour to an ASS ``&HAABBGGRR`` string.

    ASS stores colours in reverse (BGR) byte order with an *inverted* alpha
    byte where ``00`` is fully opaque and ``FF`` is fully transparent.

    >>> rgb_to_ass("#FFE500")
    '&H0000E5FF'
    """
    if not 0 <= alpha <= 0xFF:
        raise AssError("alpha must be in 0..255, got %r" % (alpha,))
    r, g, b = _normalise_rgb(value)
    return "&H%02X%02X%02X%02X" % (alpha, b, g, r)


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------


def ass_time(seconds: float) -> str:
    """Format seconds as an ASS timestamp ``H:MM:SS.cc`` (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


def karaoke_cs(word: Word) -> int:
    """Karaoke duration of ``word`` in centiseconds, clamped to a minimum of 1."""
    return max(1, int(round((word.end - word.start) * 100)))


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

_ALIGNMENTS = {"bottom": 2, "center": 5, "middle": 5, "top": 8}


@dataclass
class AssStyle:
    """The ``Default`` V4+ style written into the generated file."""

    font: str = "Noto Sans CJK SC"
    fontsize: int = 64
    #: highlight = sung words (PrimaryColour) — see module docstring.
    highlight: str = "#FFE500"
    #: resting colour = not-yet-sung words (SecondaryColour).
    base: str = "#FFFFFF"
    outline_colour: str = "#000000"
    #: ASS alpha byte is *inverted*: ``0x00`` = fully opaque, ``0xFF`` =
    #: invisible.  The outline must be opaque or it cannot do its job of
    #: separating the glyphs from a bright background.
    outline_alpha: int = 0x00
    outline: float = 2.5
    shadow: float = 0.0
    align: str = "bottom"
    margin_v: int = 90
    margin_l: int = 60
    margin_r: int = 60
    bold: bool = True

    def alignment(self) -> int:
        try:
            return _ALIGNMENTS[self.align.lower()]
        except KeyError:
            raise AssError(
                "align must be one of %s, got %r"
                % (sorted(_ALIGNMENTS), self.align)
            )

    def style_line(self) -> str:
        primary = rgb_to_ass(self.highlight)          # sung
        secondary = rgb_to_ass(self.base)             # not yet sung
        outline = rgb_to_ass(self.outline_colour, alpha=self.outline_alpha)
        back = rgb_to_ass("#000000", alpha=0xFF)
        bold = -1 if self.bold else 0
        fields = [
            "Default",
            self.font,
            str(self.fontsize),
            primary,
            secondary,
            outline,
            back,
            str(bold),
            "0",
            "0",
            "0",
            "100",
            "100",
            "0",
            "0",
            "1",
            _fmt_num(self.outline),
            _fmt_num(self.shadow),
            str(self.alignment()),
            str(self.margin_l),
            str(self.margin_r),
            str(self.margin_v),
            "1",
        ]
        return "Style: " + ",".join(fields)


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return ("%g" % value)


STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding"
)

EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)


# ---------------------------------------------------------------------------
# Event text
# ---------------------------------------------------------------------------


def _escape_text(text: str) -> str:
    """Escape characters that are structural in ASS event text."""
    # Newlines are not expected inside a word, but be defensive.
    text = text.replace("\r\n", " ").replace("\n", "\\N").replace("\r", " ")
    # Curly braces open override blocks; drop them rather than risk corruption.
    return text.replace("{", "(").replace("}", ")")


def line_text(line: Line, fade: bool = True) -> str:
    """Build the karaoke event text for one line.

    Words are prefixed with ``{\\kf<cs>}`` so the sweep advances word by word;
    an optional ``{\\fad(120,120)}`` gives the line a short fade in/out.
    """
    parts: List[str] = []
    if fade:
        parts.append("{\\fad(120,120)}")
    prev = ""
    for word in line.words:
        if _needs_space(prev, word.text):
            parts.append(" ")
        parts.append("{\\kf%d}" % karaoke_cs(word))
        parts.append(_escape_text(word.text))
        prev = word.text
    return "".join(parts)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def build_ass(
    lines: Iterable[Line],
    width: int,
    height: int,
    style: Optional[AssStyle] = None,
    fade: bool = True,
) -> str:
    """Render a complete ASS document for ``lines`` at the given canvas size."""
    style = style or AssStyle()
    out: List[str] = []
    out.append("[Script Info]")
    out.append("; generated by subreel %s" % __version__)
    out.append("ScriptType: v4.00+")
    out.append("PlayResX: %d" % width)
    out.append("PlayResY: %d" % height)
    out.append("WrapStyle: 0")
    out.append("ScaledBorderAndShadow: yes")
    out.append("")
    out.append("[V4+ Styles]")
    out.append(STYLE_FORMAT)
    out.append(style.style_line())
    out.append("")
    out.append("[Events]")
    out.append(EVENT_FORMAT)
    for line in lines:
        out.append(
            "Dialogue: 0,%s,%s,Default,,0,0,0,,%s"
            % (ass_time(line.start), ass_time(line.end), line_text(line, fade=fade))
        )
    out.append("")
    return "\n".join(out)


def write_ass(
    path: str,
    lines: Iterable[Line],
    width: int,
    height: int,
    style: Optional[AssStyle] = None,
    fade: bool = True,
) -> str:
    """Write a built ASS document to ``path`` (UTF-8) and return the path."""
    document = build_ass(lines, width, height, style=style, fade=fade)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(document)
    return path