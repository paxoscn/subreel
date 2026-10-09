"""faster-whisper wrapper — fully mocked, no model download."""

import sys
import types

import pytest

from subreel.asr import AsrError, _flatten, transcribe


class _Word:
    def __init__(self, word, start, end):
        self.word = word
        self.start = start
        self.end = end


class _Segment:
    def __init__(self, words):
        self.words = words


class _Info:
    language = "zh"


class _FakeModel:
    def __init__(self, size, device="cpu", compute_type="int8"):
        self.size = size

    def transcribe(self, audio, word_timestamps=False, language=None):
        assert word_timestamps is True
        segments = [
            _Segment([_Word(" 你", 0.0, 0.30), _Word("好", 0.30, 0.62)]),
            _Segment([_Word("世界", 0.62, 1.10)]),
        ]
        return iter(segments), _Info()


@pytest.fixture
def fake_whisper(monkeypatch):
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    return mod


def test_transcribe_flattens_words_across_segments(tmp_path, fake_whisper):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    data = transcribe(str(audio), model_size="tiny")

    assert data.source == "faster-whisper"
    assert data.language == "zh"
    assert [w.text for w in data.words] == ["你", "好", "世界"]  # leading space stripped
    assert data.words[0].start == pytest.approx(0.0)
    assert data.words[-1].end == pytest.approx(1.10)


def test_flatten_skips_blank_and_degenerate():
    seg = _Segment([
        _Word("ok", 0.0, 0.2),
        _Word("   ", 0.2, 0.3),   # blank -> skipped
        _Word("x", 0.5, 0.5),     # zero-length -> nudged forward
        _Word("y", None, 1.0),    # missing start -> skipped
    ])
    words = _flatten([seg])
    assert [w.text for w in words] == ["ok", "x"]
    assert words[1].end > words[1].start


def test_missing_faster_whisper_raises(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(AsrError, match="faster-whisper is not installed"):
        transcribe(str(tmp_path / "a.wav"))


def test_model_load_failure_mentions_mirror(monkeypatch, tmp_path):
    class Boom:
        def __init__(self, *a, **kw):
            raise OSError("could not connect to huggingface.co")

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = Boom
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    with pytest.raises(AsrError) as exc:
        transcribe(str(tmp_path / "a.wav"))
    assert "HF_ENDPOINT" in str(exc.value)


def test_empty_transcription_raises(monkeypatch, tmp_path):
    class Empty(_FakeModel):
        def transcribe(self, audio, word_timestamps=False, language=None):
            return iter([]), _Info()

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = Empty
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    with pytest.raises(AsrError, match="no words"):
        transcribe(str(tmp_path / "a.wav"))