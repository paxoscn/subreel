"""faster-whisper wrapper: word-level ASR timings for arbitrary audio."""

from __future__ import annotations

from typing import List, Optional

from .timings import Word, WordsData

__all__ = ["AsrError", "transcribe"]

_PIP_HINT = (
    'faster-whisper is not installed.  Install it with:\n'
    '  pip install "subreel[asr]"'
)

_MIRROR_HINT = (
    "If the model download failed because huggingface.co is unreachable, "
    "try a mirror:\n  export HF_ENDPOINT=https://hf-mirror.com"
)


class AsrError(RuntimeError):
    """A recoverable ASR failure; the CLI turns this into exit code 2."""


def transcribe(
    audio: str,
    *,
    model_size: str = "base",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
) -> WordsData:
    """Transcribe ``audio`` and return word-level timings.

    The model is loaded lazily on first use; if the download fails (no network
    to huggingface.co) the error message points at ``HF_ENDPOINT``.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise AsrError("%s\n(%s)" % (_PIP_HINT, exc))

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        raise AsrError(
            "could not load whisper model %r (%s: %s)\n%s"
            % (model_size, type(exc).__name__, exc, _MIRROR_HINT)
        )

    try:
        segments, info = model.transcribe(
            audio, word_timestamps=True, language=language
        )
        words = _flatten(segments)
    except Exception as exc:
        raise AsrError("transcription failed (%s: %s)" % (type(exc).__name__, exc))

    if not words:
        raise AsrError("no words were recognised in %r" % audio)

    detected = getattr(info, "language", None) or language
    return WordsData(words=words, language=detected, source="faster-whisper")


def _flatten(segments) -> List[Word]:
    """Flatten faster-whisper segments into a list of :class:`Word`."""
    words: List[Word] = []
    for segment in segments:
        seg_words = getattr(segment, "words", None) or ()
        for sw in seg_words:
            text = getattr(sw, "word", None)
            start = getattr(sw, "start", None)
            end = getattr(sw, "end", None)
            if text is None or start is None or end is None:
                continue
            text = text.strip()
            if not text:
                continue
            start = float(start)
            end = float(end)
            if end <= start:
                # Guard against degenerate timings from the model.
                end = start + 0.01
            words.append(Word(text=text, start=start, end=end))
    return words