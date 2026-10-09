"""edge-tts wrapper — fully mocked, no network."""

import sys
import types

import pytest

import subreel.tts as tts_mod
from subreel.tts import TtsError, default_timings_path, infer_language, synthesize


class _FakeCommunicate:
    """Stand-in for edge_tts.Communicate emitting audio + WordBoundary chunks."""

    def __init__(self, text, voice, rate="+0%", pitch="+0Hz", boundary=None):
        self.text = text
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.boundary = boundary

    async def stream(self):
        yield {"type": "audio", "data": b"ID3-AUDIO-1"}
        # 1_200_000 ticks = 0.12s ; 1_900_000 ticks = 0.19s
        yield {"type": "WordBoundary", "offset": 1_200_000, "duration": 1_900_000, "text": "你"}
        yield {"type": "audio", "data": b"-AUDIO-2"}
        yield {"type": "WordBoundary", "offset": 3_100_000, "duration": 2_700_000, "text": "好"}


@pytest.fixture
def fake_edge_tts(monkeypatch):
    mod = types.ModuleType("edge_tts")
    mod.Communicate = _FakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    return mod


def test_infer_language():
    assert infer_language("zh-CN-XiaoxiaoNeural") == "zh"
    assert infer_language("en-US-AriaNeural") == "en"
    assert infer_language("ja-JP-NanamiNeural") == "ja"


def test_default_timings_path():
    assert default_timings_path("/tmp/voice.mp3") == "/tmp/voice.words.json"
    assert default_timings_path("a.wav") == "a.words.json"


def test_synthesize_captures_word_timestamps(tmp_path, fake_edge_tts):
    out = tmp_path / "voice.mp3"
    timings = tmp_path / "voice.words.json"

    data = synthesize(
        "你好",
        voice="zh-CN-XiaoxiaoNeural",
        out=str(out),
        rate="+15%",
        pitch="+8Hz",
        timings=str(timings),
    )

    assert out.exists()
    assert out.read_bytes() == b"ID3-AUDIO-1-AUDIO-2"
    assert data.language == "zh"
    assert data.source == "edge-tts"
    assert len(data.words) == 2
    # exact tick -> seconds conversion
    assert data.words[0].start == pytest.approx(0.12)
    assert data.words[0].end == pytest.approx(0.31)
    assert data.words[1].start == pytest.approx(0.31)
    assert data.words[1].end == pytest.approx(0.58)
    assert timings.exists()
    assert '"source": "edge-tts"' in timings.read_text(encoding="utf-8")


def test_synthesize_requests_word_boundary(tmp_path, fake_edge_tts, monkeypatch):
    seen = {}

    class Spy(_FakeCommunicate):
        def __init__(self, *a, **kw):
            seen.update(kw)
            super().__init__(*a, **kw)

    fake_edge_tts.Communicate = Spy
    synthesize("hi", out=str(tmp_path / "v.mp3"), timings=str(tmp_path / "v.json"))
    assert seen.get("boundary") == "WordBoundary"


def test_empty_text_rejected(fake_edge_tts):
    with pytest.raises(TtsError, match="empty"):
        synthesize("   ", out="/tmp/x.mp3")


def test_no_word_boundaries_raises(tmp_path, fake_edge_tts):
    class AudioOnly(_FakeCommunicate):
        async def stream(self):
            yield {"type": "audio", "data": b"x"}

    fake_edge_tts.Communicate = AudioOnly
    with pytest.raises(TtsError, match="no word boundaries"):
        synthesize("hi", out=str(tmp_path / "v.mp3"))


def test_network_error_is_friendly(tmp_path, fake_edge_tts):
    class Boom(_FakeCommunicate):
        async def stream(self):
            raise ConnectionError("network down")
            yield  # pragma: no cover - unreachable, makes this a generator

    fake_edge_tts.Communicate = Boom
    with pytest.raises(TtsError) as exc:
        synthesize("hi", out=str(tmp_path / "v.mp3"))
    assert "synthesis failed" in str(exc.value)


def test_missing_edge_tts_raises(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    with pytest.raises(TtsError, match="edge-tts is not installed"):
        synthesize("hi", out=str(tmp_path / "v.mp3"))

class _PunctFakeCommunicate(_FakeCommunicate):
    """Emits one boundary per spoken char of '你好，世界！' (punct excluded)."""

    async def stream(self):
        yield {"type": "audio", "data": b"A"}
        for i, ch in enumerate("你好世界"):
            yield {
                "type": "WordBoundary",
                "offset": (1_000_000 + i * 2_000_000),
                "duration": 2_000_000,
                "text": ch,
            }


def test_punctuation_is_reattached_from_source_text(tmp_path, monkeypatch):
    mod = types.ModuleType("edge_tts")
    mod.Communicate = _PunctFakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)

    data = synthesize(
        "你好，世界！",
        voice="zh-CN-XiaoxiaoNeural",
        out=str(tmp_path / "v.mp3"),
    )
    assert [w.text for w in data.words] == ["你", "好，", "世", "界！"]
    # timings stay those of the spoken words
    assert data.words[1].start == 0.3 and data.words[1].end == 0.5


def test_punctuation_merge_falls_back_on_mismatch(tmp_path, monkeypatch):
    # boundary stream does not match the source text -> untouched words
    mod = types.ModuleType("edge_tts")
    mod.Communicate = _PunctFakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)

    data = synthesize(
        "再见，世界！",
        voice="zh-CN-XiaoxiaoNeural",
        out=str(tmp_path / "v.mp3"),
    )
    assert [w.text for w in data.words] == ["你", "好", "世", "界"]


class _DotFakeCommunicate(_FakeCommunicate):
    """'模型使用4.1 Flash。' — boundary tokens keep the intra-word dot."""

    async def stream(self):
        yield {"type": "audio", "data": b"A"}
        for i, tok in enumerate(["模型", "使用", "4.1", "Flash"]):
            yield {
                "type": "WordBoundary",
                "offset": (1_000_000 + i * 2_000_000),
                "duration": 2_000_000,
                "text": tok,
            }


def test_intra_word_dot_does_not_break_alignment(tmp_path, monkeypatch):
    mod = types.ModuleType("edge_tts")
    mod.Communicate = _DotFakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)

    data = synthesize(
        "模型使用4.1 Flash。",
        voice="zh-CN-XiaoxiaoNeural",
        out=str(tmp_path / "v.mp3"),
    )
    assert [w.text for w in data.words] == ["模型", "使用", "4.1", "Flash。"]
