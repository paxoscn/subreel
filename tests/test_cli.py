"""CLI surface: --version/--help, exit codes and timing-source resolution."""

import json

import pytest

import subreel.cli as cli


# ---------------------------------------------------------------------------
# version / help
# ---------------------------------------------------------------------------


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "0.1.0" in out


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "render" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# render: error paths
# ---------------------------------------------------------------------------


def test_render_missing_audio_file(tmp_path):
    code = cli.main(["render", str(tmp_path / "nope.mp3"), "--timings", "x.json"])
    assert code == 2


def test_render_without_timing_source(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"AUDIO")
    code = cli.main(["render", str(audio)])
    assert code == 2


def test_render_timings_and_asr_warns(tmp_path, caplog, monkeypatch):
    import logging

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"AUDIO")
    words = tmp_path / "w.json"
    words.write_text(json.dumps({"words": [{"text": "x", "start": 0.0, "end": 1.0}]}),
                     encoding="utf-8")

    # stop before actually invoking ffmpeg
    monkeypatch.setattr(cli.render_mod, "render", lambda *a, **k: [])
    with caplog.at_level(logging.WARNING, logger="subreel"):
        code = cli.main(
            ["render", str(audio), "--timings", str(words), "--asr", "--out-dir",
             str(tmp_path / "o")]
        )
    assert code == 0
    assert "using --timings" in caplog.text


def test_render_bad_timings_file(tmp_path, caplog):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"AUDIO")
    bad = tmp_path / "bad.json"
    bad.write_text('{"words": []}', encoding="utf-8")
    code = cli.main(["render", str(audio), "--timings", str(bad),
                     "--out-dir", str(tmp_path / "o")])
    assert code == 2


def test_render_success_mocked(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"AUDIO")
    words = tmp_path / "w.json"
    words.write_text(
        json.dumps({"language": "zh", "source": "edge-tts", "words": [
            {"text": "你", "start": 0.0, "end": 0.3},
            {"text": "好", "start": 0.3, "end": 0.6},
        ]}), encoding="utf-8")

    captured = {}

    def fake_render(audio_path, lines, out_dir, formats=("green",), **kw):
        captured["formats"] = list(formats)
        captured["lines"] = lines
        captured["size"] = (kw["width"], kw["height"])
        from subreel.render import Artifact

        return [Artifact(path=str(tmp_path / "o" / "subs-green.mp4"),
                         size=1024, summary="video: h264 [yuv420p]", format="green")]

    monkeypatch.setattr(cli.render_mod, "render", fake_render)
    code = cli.main([
        "render", str(audio), "--timings", str(words),
        "--formats", "green,webm", "--size", "1920x1080",
        "--out-dir", str(tmp_path / "o"),
    ])
    assert code == 0
    assert captured["formats"] == ["green", "webm"]
    assert captured["size"] == (1920, 1080)
    assert len(captured["lines"]) == 1  # both words fit on one line
    assert captured["lines"][0].text == "你好"


# ---------------------------------------------------------------------------
# tts
# ---------------------------------------------------------------------------


def test_tts_requires_a_text_source():
    with pytest.raises(SystemExit) as exc:
        cli.main(["tts", "--out", "/tmp/x.mp3"])
    assert exc.value.code == 2  # argparse: required mutually-exclusive group


def test_tts_from_inline(tmp_path, monkeypatch, capsys):
    from subreel.timings import Word, WordsData

    def fake_synth(text, **kw):
        assert text == "你好"
        # emulate writing files
        open(kw["out"], "wb").write(b"AUDIO")
        with open(kw["timings"], "w", encoding="utf-8") as fh:
            json.dump({"words": [{"text": "你", "start": 0.0, "end": 0.3}]}, fh)
        return WordsData(words=[Word("你", 0.0, 0.3)], language="zh", source="edge-tts")

    monkeypatch.setattr(cli.tts_mod, "synthesize", fake_synth)
    monkeypatch.setattr(cli.render_mod, "ensure_ffmpeg", lambda: (_ for _ in ()).throw(
        cli.RenderError("no ffmpeg")))
    code = cli.main([
        "tts", "--text-inline", "你好", "--out", str(tmp_path / "v.mp3"),
        "--timings", str(tmp_path / "v.words.json"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "v.mp3" in out
    assert "1 words" in out


def test_tts_default_timings_path(tmp_path, monkeypatch):
    from subreel.timings import Word, WordsData

    seen = {}

    def fake_synth(text, **kw):
        seen["timings"] = kw["timings"]
        open(kw["out"], "wb").write(b"AUDIO")
        open(kw["timings"], "w").write('{"words": []}')
        return WordsData(words=[Word("x", 0, 1)], source="edge-tts")

    monkeypatch.setattr(cli.tts_mod, "synthesize", fake_synth)
    monkeypatch.setattr(cli.render_mod, "ensure_ffmpeg", lambda: (_ for _ in ()).throw(
        cli.RenderError("no ffmpeg")))
    cli.main(["tts", "--text-inline", "hi", "--out", str(tmp_path / "v.mp3")])
    assert seen["timings"].endswith("v.words.json")