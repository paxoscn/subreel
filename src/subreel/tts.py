"""edge-tts wrapper: synthesize speech *and* capture per-word timings.

edge-tts streams ``WordBoundary`` events alongside the audio, each carrying an
``offset`` and ``duration`` in 100-nanosecond ticks (1 tick = 1e-7 s).  Capturing
those gives a subtitle timeline with exactly zero ASR error.
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional

from .timings import Word, WordsData

__all__ = ["TtsError", "synthesize", "default_timings_path", "infer_language"]

#: edge-tts offsets are in 100 ns ticks.
_TICKS_PER_SECOND = 1e7

_PIP_HINT = 'edge-tts is not installed.  Install it with:\n  pip install "subreel[tts]"'


class TtsError(RuntimeError):
    """A recoverable synthesis failure; the CLI turns this into exit code 2."""


def infer_language(voice: str) -> str:
    """Best-effort language tag from a voice name (``zh-CN-...`` -> ``zh``)."""
    return (voice.split("-", 1)[0] or "").strip().lower()


def default_timings_path(out_path: str) -> str:
    """Return the default words.json path for an audio output path."""
    root, _ext = os.path.splitext(out_path)
    return root + ".words.json"


def _make_communicate(edge_tts, text: str, voice: str, rate: str, pitch: str):
    """Build a Communicate, requesting word boundaries when edge-tts allows it.

    edge-tts >= 7 lets you choose the boundary granularity (it defaults to
    *sentence* boundaries); older releases always emit word boundaries.
    """
    try:
        return edge_tts.Communicate(
            text, voice, rate=rate, pitch=pitch, boundary="WordBoundary"
        )
    except TypeError:
        return edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)


async def _synthesize_async(
    text: str,
    voice: str,
    out_path: str,
    rate: str,
    pitch: str,
) -> WordsData:
    try:
        import edge_tts  # noqa: WPS433 (deliberate lazy import)
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise TtsError("%s\n(%s)" % (_PIP_HINT, exc))

    communicate = _make_communicate(edge_tts, text, voice, rate, pitch)
    words: List[Word] = []

    try:
        with open(out_path, "wb") as fh:
            async for chunk in communicate.stream():
                ctype = chunk.get("type") if isinstance(chunk, dict) else None
                if ctype == "audio":
                    fh.write(chunk["data"])
                elif ctype == "WordBoundary":
                    offset = float(chunk["offset"])
                    duration = float(chunk["duration"])
                    words.append(
                        Word(
                            text=str(chunk["text"]),
                            start=offset / _TICKS_PER_SECOND,
                            end=(offset + duration) / _TICKS_PER_SECOND,
                        )
                    )
    except Exception as exc:  # network, NoAudioReceived, UnexpectedResponse, ...
        raise TtsError(_friendly_error(exc, voice))

    if not words:
        raise TtsError(
            "edge-tts returned audio but no word boundaries for voice %r; "
            "the voice may have been retired, or the text produced no speech."
            % voice
        )

    words = _merge_punctuation(text, words)

    return WordsData(words=words, language=infer_language(voice), source="edge-tts")


#: punctuation that edge-tts keeps *inside* a spoken token, e.g. the dot of
#: "4.1" or the hyphen of "e-mail" — never a line-break hint.
_INTRA_WORD = ".-'’"


def _spoken_char(src: List[str], i: int) -> bool:
    """True when ``src[i]`` is part of a spoken token, not punctuation."""
    ch = src[i]
    if ch.isalnum():
        return True
    return (
        ch in _INTRA_WORD
        and 0 < i < len(src) - 1
        and src[i - 1].isalnum()
        and src[i + 1].isalnum()
    )


def _merge_punctuation(text: str, words: List[Word]) -> List[Word]:
    """Glue source-text punctuation onto the neighbouring spoken words.

    edge-tts ``WordBoundary`` events cover only *spoken* characters, so the
    captured timeline carries no punctuation and the line breaker would be
    forced into hard ``max_chars`` cuts.  The original script does carry
    punctuation, and it aligns 1:1 with the boundary stream once punctuation
    and whitespace are stripped, so each punctuation run is re-attached to the
    word spoken just before it (leading runs go to the first word, trailing
    runs to the last).  Characters of :data:`_INTRA_WORD` sandwiched between
    alphanumerics count as spoken ("4.1", "e-mail").  Returns ``words``
    unchanged when the two streams do not align — a defensive fallback, never
    a crash.
    """
    src = [ch for ch in text if not ch.isspace()]
    spoken_flags = [_spoken_char(src, i) for i in range(len(src))]
    spoken = "".join(ch for ch, f in zip(src, spoken_flags) if f)
    if spoken != "".join(w.text for w in words):
        return words

    out: List[Word] = []
    pending: List[str] = []
    ci = 0
    for w in words:
        while ci < len(src) and not spoken_flags[ci]:
            pending.append(src[ci])
            ci += 1
        new_text = w.text
        if pending:
            run = "".join(pending)
            if out:
                prev = out[-1]
                out[-1] = Word(prev.text + run, prev.start, prev.end)
            else:
                new_text = run + new_text
            pending = []
        ci += len(w.text)
        out.append(Word(new_text, w.start, w.end))
    while ci < len(src) and not spoken_flags[ci]:
        pending.append(src[ci])
        ci += 1
    if pending and out:
        prev = out[-1]
        out[-1] = Word(prev.text + "".join(pending), prev.start, prev.end)
    return out


def _friendly_error(exc: Exception, voice: str) -> str:
    name = type(exc).__name__
    msg = str(exc) or name
    extra = ""
    if name in ("NoAudioReceived", "UnexpectedResponse"):
        extra = (
            "\nThe voice %r may have been retired or the text was empty. "
            "Run `edge-tts --list-voices` to see what is available." % voice
        )
    elif name in ("ClientConnectorError", "ClientOSError", "ServerDisconnectedError"):
        extra = "\nCheck your network connection (edge-tts needs the Microsoft endpoint)."
    return "edge-tts synthesis failed: %s: %s%s" % (name, msg, extra)


def synthesize(
    text: str,
    *,
    voice: str = "zh-CN-XiaoxiaoNeural",
    out: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    timings: Optional[str] = None,
) -> WordsData:
    """Synthesize ``text`` to ``out`` and return the captured word timings.

    If ``timings`` is given (or defaults next to ``out`` when the caller wants
    it), the words.json document is written there.  Returns the
    :class:`~subreel.timings.WordsData`.
    """
    if not text or not text.strip():
        raise TtsError("no text to synthesize (empty input)")

    out_dir = os.path.dirname(os.path.abspath(out))
    os.makedirs(out_dir, exist_ok=True)

    data = asyncio.run(_synthesize_async(text, voice, out, rate, pitch))

    if timings:
        data.dump(timings)
    return data