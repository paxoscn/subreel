"""Word-level timing model, words.json I/O and the line-breaking algorithm.

The *words.json* file is subreel's public, documented interchange format.  Any
tool that can produce per-word timestamps can drive subreel: an ``edge-tts``
run, a faster-whisper ASR run, or your own forced-alignment pipeline.

Schema (all times in **seconds**, ``float``)::

    {
      "language": "zh",                 # optional, BCP-47-ish, best effort
      "source": "edge-tts",             # optional, free-form provenance string
      "words": [
        {"text": "你", "start": 0.12, "end": 0.31},
        {"text": "好", "start": 0.31, "end": 0.58}
      ]
    }

Invariants enforced by :func:`load_words`:

* ``words`` must be a non-empty list;
* every entry must have ``text`` (str), ``start`` (number), ``end`` (number);
* ``start < end`` for every word;
* ``start`` values are monotonically non-decreasing (equal is allowed — two
  words may share a boundary), and a word may not start before the previous
  word's ``start``.

Anything that violates these raises :class:`TimingsError` with a message that
names the offending word index.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "TimingsError",
    "Word",
    "Line",
    "WordsData",
    "load_words",
    "char_units",
    "line_units",
    "split_lines",
    "SENTENCE_END",
    "COMMA",
]

#: Characters that end a sentence.  A line is closed eagerly right after one of
#: these so subtitles never straddle a sentence boundary.
SENTENCE_END = frozenset("。！？；!?;…")

#: Weaker break characters, preferred over a plain space when wrapping.
COMMA = frozenset("，、,")

#: Characters that must never begin a wrapped line (they belong to the end of
#: the previous line).  CJK + ASCII closing punctuation.
_NO_LINE_START = frozenset("。！？；!?;…，、,）)】》」』〕”’\"'.:")


class TimingsError(ValueError):
    """Raised when a words.json document is missing or malformed."""


@dataclass
class Word:
    """A single spoken word (or CJK character) with its time span in seconds."""

    text: str
    start: float
    end: float

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "start": self.start, "end": self.end}


@dataclass
class Line:
    """One subtitle line — one ASS ``Dialogue`` event, one karaoke sweep.

    ``start``/``end`` are in seconds; ``end`` already includes the karaoke
    ``hold`` tail when it does not collide with the following line.
    """

    text: str
    words: List[Word] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0


@dataclass
class WordsData:
    """The whole words.json document."""

    words: List[Word]
    language: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "source": self.source,
            "words": [w.to_dict() for w in self.words],
        }

    def dump(self, path: str) -> None:
        """Write this document to ``path`` as pretty UTF-8 JSON."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
            fh.write("\n")


def _as_float(value: Any, what: str, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TimingsError(
            "words[%d].%s must be a number, got %r (%s)"
            % (index, what, value, type(value).__name__)
        )
    return float(value)


def _parse_word(raw: Any, index: int) -> Word:
    if not isinstance(raw, dict):
        raise TimingsError(
            "words[%d] must be an object, got %s" % (index, type(raw).__name__)
        )
    for key in ("text", "start", "end"):
        if key not in raw:
            raise TimingsError("words[%d] is missing required field %r" % (index, key))
    text = raw["text"]
    if not isinstance(text, str):
        raise TimingsError(
            "words[%d].text must be a string, got %s" % (index, type(text).__name__)
        )
    if text == "":
        raise TimingsError("words[%d].text must not be empty" % index)
    start = _as_float(raw["start"], "start", index)
    end = _as_float(raw["end"], "end", index)
    if not start < end:
        raise TimingsError(
            "words[%d] (%r): start (%.3f) must be strictly less than end (%.3f)"
            % (index, text, start, end)
        )
    return Word(text=text, start=start, end=end)


def load_words(path: str) -> WordsData:
    """Load and validate a words.json document from ``path``.

    Raises :class:`TimingsError` on any structural or ordering problem.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise TimingsError("timings file not found: %s" % path)
    except json.JSONDecodeError as exc:
        raise TimingsError("timings file is not valid JSON (%s): %s" % (path, exc))

    return parse_words_data(doc, origin=path)


def parse_words_data(doc: Any, origin: str = "<data>") -> WordsData:
    """Validate an already-decoded words.json document."""
    if not isinstance(doc, dict):
        raise TimingsError("%s: top level must be a JSON object" % origin)
    raw_words = doc.get("words")
    if raw_words is None:
        raise TimingsError("%s: missing required key 'words'" % origin)
    if not isinstance(raw_words, list):
        raise TimingsError("%s: 'words' must be a list" % origin)
    if len(raw_words) == 0:
        raise TimingsError("%s: 'words' must not be empty" % origin)

    words = [_parse_word(raw, i) for i, raw in enumerate(raw_words)]

    # Monotonic, non-decreasing starts (equal allowed).
    for i in range(1, len(words)):
        if words[i].start < words[i - 1].start:
            raise TimingsError(
                "%s: words[%d] starts at %.3f, before words[%d] at %.3f "
                "(starts must be non-decreasing)"
                % (origin, i, words[i].start, i - 1, words[i - 1].start)
            )

    language = doc.get("language")
    source = doc.get("source")
    if language is not None and not isinstance(language, str):
        raise TimingsError("%s: 'language' must be a string when present" % origin)
    if source is not None and not isinstance(source, str):
        raise TimingsError("%s: 'source' must be a string when present" % origin)

    return WordsData(words=words, language=language, source=source)


# ---------------------------------------------------------------------------
# Display width
# ---------------------------------------------------------------------------


def char_units(text: str) -> float:
    """Return the display width of ``text`` in "CJK units".

    Wide / full-width characters (CJK ideographs, CJK punctuation, full-width
    forms) count as ``1.0``; everything else — ASCII letters, digits, spaces,
    half-width punctuation — counts as ``0.5``.  A line budget of ``max_chars``
    therefore means "``max_chars`` full-width cells", i.e. 22 CJK glyphs or 44
    ASCII characters.
    """
    total = 0.0
    for ch in text:
        total += 1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.5
    return total


def _is_punct_only(text: str) -> bool:
    return bool(text) and all(
        ch in SENTENCE_END or ch in COMMA or ch in _NO_LINE_START for ch in text
    )


def _ends_sentence(text: str) -> bool:
    return bool(text) and text[-1] in SENTENCE_END


def _needs_space(prev: str, cur: str) -> bool:
    """Whether a space should be inserted between two word texts when joining.

    This keeps Latin text readable ("hello world") while gluing CJK and
    punctuation tightly ("你好。").
    """
    if not prev or not cur:
        return False
    a, b = prev[-1], cur[0]
    if b in _NO_LINE_START:
        return False
    if unicodedata.east_asian_width(a) in ("W", "F"):
        return False
    if unicodedata.east_asian_width(b) in ("W", "F"):
        return False
    return a.isalnum() and (b.isalnum() or b in "([{")


#: A joining space costs the same as one half-width glyph.
_SPACE_UNITS = 0.5


def line_units(words: Iterable[Word]) -> float:
    """Display width of a run of words *including* the spaces joining them."""
    total = 0.0
    prev = ""
    for w in words:
        if _needs_space(prev, w.text):
            total += _SPACE_UNITS
        total += char_units(w.text)
        prev = w.text
    return total


def _step_units(prev: str, text: str) -> float:
    """Incremental width of appending ``text`` after ``prev``."""
    return char_units(text) + (_SPACE_UNITS if _needs_space(prev, text) else 0.0)


def join_words(words: Iterable[Word]) -> str:
    """Concatenate word texts into display text, inserting spaces as needed."""
    out: List[str] = []
    prev = ""
    for w in words:
        if _needs_space(prev, w.text):
            out.append(" ")
        out.append(w.text)
        prev = w.text
    text = "".join(out)
    return text.strip()


# ---------------------------------------------------------------------------
# Line breaking
# ---------------------------------------------------------------------------


def _best_cut(buf: List[Word]) -> int:
    """Choose how many words of ``buf`` to keep on the finished line.

    Returns ``k`` in ``[1, len(buf)]``; the finished line is ``buf[:k]`` and the
    remainder ``buf[k:]`` flows onto the next line.  Break priority, strongest
    first, matching the documented behaviour:

    1. right after a word ending in sentence punctuation (``。！？；!?;…``);
    2. otherwise right after a word ending in a comma (``，、,``);
    3. otherwise a hard cut — keep the whole buffer and wrap before the
       overflowing word.
    """
    n = len(buf)
    best = 0  # index of the last word of the kept prefix candidate
    for i in range(n):
        if _ends_sentence(buf[i].text):
            best = i
    if best:
        return best + 1
    for i in range(n):
        if buf[i].text and buf[i].text[-1] in COMMA:
            best = i
    if best:
        return best + 1
    return n


def _collapse_leading_punctuation(buf: List[Word], k: int) -> int:
    """Never let a line start with punctuation: pull such words back.

    If the remainder would begin with punctuation-only words, keep them on the
    finished line instead (``标点不孤行``).
    """
    n = len(buf)
    while k < n and _is_punct_only(buf[k].text):
        k += 1
    return k


def split_lines(
    words: List[Word],
    max_chars: float = 22.0,
    max_lines: int = 2,
    hold: float = 0.3,
) -> List[Line]:
    """Break a word stream into subtitle lines.

    Parameters
    ----------
    words:
        The word stream (typically ``WordsData.words``), already validated and
        time-ordered.
    max_chars:
        Per-line display budget in CJK units (see :func:`char_units`).  A line
        is wrapped once adding the next word would exceed this budget, and the
        break is moved backwards to the strongest available punctuation
        boundary.
    max_lines:
        Soft maximum number of lines a single sentence is allowed to span.
        Sentences that need more lines are split further rather than truncated;
        the value documents the intended simultaneous-line count for a cue.
    hold:
        Seconds added to each line's end so the finished karaoke sweep stays on
        screen briefly.  The hold is skipped when it would overlap the start of
        the next line.

    Returns
    -------
    list of :class:`Line`, one line per ASS ``Dialogue`` event.
    """
    if max_chars <= 0:
        raise TimingsError("max_chars must be positive, got %r" % (max_chars,))
    if max_lines < 1:
        raise TimingsError("max_lines must be >= 1, got %r" % (max_lines,))

    lines: List[Line] = []
    buf: List[Word] = []
    buf_units = 0.0
    i = 0
    n = len(words)

    def flush(chunk: List[Word]) -> None:
        if not chunk:
            return
        lines.append(
            Line(
                text=join_words(chunk),
                words=list(chunk),
                start=chunk[0].start,
                end=chunk[-1].end,
            )
        )

    while i < n:
        w = words[i]
        wu = _step_units(buf[-1].text, w.text) if buf else char_units(w.text)

        # Eagerly close a line after sentence-ending punctuation.  This keeps a
        # subtitle from straddling two sentences.
        if buf and _ends_sentence(buf[-1].text):
            flush(buf)
            buf = []
            buf_units = 0.0
            continue

        if buf and buf_units + wu > max_chars:
            # A trailing punctuation word may stay with the line even if it
            # pushes slightly past the budget, so the mark is not orphaned.
            if _is_punct_only(w.text):
                buf.append(w)
                buf_units += wu
                i += 1
                continue
            k = _best_cut(buf)
            k = _collapse_leading_punctuation(buf, k)
            flush(buf[:k])
            buf = buf[k:]
            buf_units = line_units(buf)
            continue

        buf.append(w)
        buf_units += wu
        i += 1

    flush(buf)

    if not lines:
        return lines

    # Apply the karaoke hold tail.
    for idx, line in enumerate(lines):
        candidate = line.end + hold
        if idx + 1 < len(lines) and candidate > lines[idx + 1].start:
            continue  # would overlap the next line: skip the hold
        line.end = candidate

    return lines