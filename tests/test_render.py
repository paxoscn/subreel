"""ffmpeg command construction and the render orchestration (fully mocked)."""

import json
import os

import pytest

import subreel.render as render_mod
from subreel.render import (
    RenderError,
    build_command,
    ensure_ffmpeg,
    escape_filter_path,
    parse_size,
    render,
)
from subreel.timings import Line, Word


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _cmd(fmt, **kw):
    base = dict(
        ffmpeg="/usr/bin/ffmpeg",
        audio="/tmp/voice.mp3",
        ass_path="/tmp/out/subs.ass",
        width=1280,
        height=720,
        fps=30,
        duration=4.0,
        out_path="/tmp/out/x",
    )
    base.update(kw)
    return build_command(fmt, **base)


def _pairs(cmd):
    """Return the arg list as (flag, value) pairs plus bare tokens."""
    return cmd


# ---------------------------------------------------------------------------
# escaping / size
# ---------------------------------------------------------------------------


def test_escape_filter_path_escapes_metachars():
    assert escape_filter_path("/tmp/a b/subs.ass") == "/tmp/a b/subs.ass"
    assert escape_filter_path(r"C:\x\subs.ass") == r"C\:/x/subs.ass"
    assert escape_filter_path("/a:b'c/s.ass") == r"/a\:b\'c/s.ass"


def test_parse_size():
    assert parse_size("1280x720") == (1280, 720)
    assert parse_size("1920:1080") == (1920, 1080)
    with pytest.raises(RenderError):
        parse_size("huge")


# ---------------------------------------------------------------------------
# command construction
# ---------------------------------------------------------------------------


def test_green_command():
    cmd = _cmd("green")
    joined = " ".join(cmd)
    assert "libx264" in cmd
    assert "-pix_fmt" in cmd and "yuv420p" in cmd
    assert "-crf" in cmd and "18" in cmd
    assert "-c:a" in cmd and "aac" in cmd
    assert "color=c=0x00B140:s=1280x720:r=30" in cmd
    assert any(a.startswith("ass=") for a in cmd)
    # audio is mapped explicitly
    assert "1:a?" in cmd


def test_webm_command_has_alpha_and_alt_ref_zero():
    cmd = _cmd("webm")
    vf = cmd[cmd.index("-vf") + 1]
    assert "libvpx-vp9" in cmd
    assert "yuva420p" in cmd
    assert "format=yuva420p" in vf
    assert cmd[cmd.index("-auto-alt-ref") + 1] == "0"
    assert "libopus" in cmd
    # transparent canvas keeps its alpha, and the ass filter composites it
    assert "color=c=black@0:s=1280x720:r=30,format=rgba" in cmd
    assert "alpha=1" in vf


def test_mov_command_is_prores4444():
    cmd = _cmd("mov")
    vf = cmd[cmd.index("-vf") + 1]
    assert "prores_ks" in cmd
    assert cmd[cmd.index("-profile:v") + 1] == "4444"
    assert "yuva444p10le" in cmd
    assert "format=yuva444p10le" in vf
    assert "alpha=1" in vf
    assert "pcm_s16le" in cmd


def test_green_command_has_no_alpha_filter():
    cmd = _cmd("green")
    vf = cmd[cmd.index("-vf") + 1]
    assert "alpha=1" not in vf
    assert "yuva" not in vf


def test_no_audio_drops_track():
    cmd = _cmd("green", no_audio=True)
    assert "-an" in cmd
    assert "-c:a" not in cmd
    assert "/tmp/voice.mp3" not in cmd


def test_unknown_format_raises():
    with pytest.raises(RenderError):
        build_command(
            "gif",
            ffmpeg="ffmpeg",
            audio=None,
            ass_path="/x.ass",
            width=1,
            height=1,
            fps=1,
            duration=1,
            out_path="/o",
        )


def test_fontsdir_added_when_given():
    cmd = _cmd("green", fontsdir="/usr/share/fonts")
    assert "fontsdir=/usr/share/fonts" in " ".join(cmd)


# ---------------------------------------------------------------------------
# tool discovery
# ---------------------------------------------------------------------------


def test_ensure_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr(render_mod.shutil, "which", lambda name: None)
    with pytest.raises(RenderError, match="missing required tool"):
        ensure_ffmpeg()


def test_ensure_ffmpeg_hint_mentions_platforms(monkeypatch):
    monkeypatch.setattr(render_mod.shutil, "which", lambda name: None)
    with pytest.raises(RenderError) as exc:
        ensure_ffmpeg()
    msg = str(exc.value)
    assert "apt install ffmpeg" in msg
    assert "brew install ffmpeg" in msg
    assert "winget" in msg


# ---------------------------------------------------------------------------
# render orchestration
# ---------------------------------------------------------------------------


class _Proc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def fake_tools(monkeypatch):
    """Patch shutil.which + subprocess.run; record every argv."""
    calls = []

    def fake_which(name):
        return "/usr/bin/" + name

    def fake_run(cmd, capture_output=True):
        calls.append(list(cmd))
        joined = " ".join(cmd)
        if "format=duration" in joined:
            return _Proc(stdout=json.dumps({"format": {"duration": "4.0"}}).encode())
        if "stream=codec_type" in joined:
            payload = {
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                     "width": 1280, "height": 720},
                    {"codec_type": "audio", "codec_name": "aac"},
                ]
            }
            return _Proc(stdout=json.dumps(payload).encode())
        # an ffmpeg render: materialise the output file so getsize() works
        out = cmd[-1]
        with open(out, "wb") as fh:
            fh.write(b"\x00" * 32)
        return _Proc()

    monkeypatch.setattr(render_mod.shutil, "which", fake_which)
    monkeypatch.setattr(render_mod.subprocess, "run", fake_run)
    return calls


def test_render_all_three_formats(tmp_path, fake_tools):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"AUDIO")
    lines = [Line("你好", [Word("你", 0.0, 0.5), Word("好", 0.5, 1.0)], 0.0, 1.3)]

    artifacts = render(
        str(audio),
        lines,
        str(tmp_path / "out"),
        formats=["green", "webm", "mov"],
    )

    names = [os.path.basename(a.path) for a in artifacts]
    assert names == ["subs-green.mp4", "subs-alpha.webm", "subs-alpha.mov"]
    for art in artifacts:
        assert art.size > 0
        assert "video:" in art.summary

    # the ASS side-car was written next to the outputs
    assert (tmp_path / "out" / "subs.ass").exists()

    ffmpeg_calls = [c for c in fake_tools if c[0] == "/usr/bin/ffmpeg"]
    assert len(ffmpeg_calls) == 3
    assert any("libx264" in c for c in ffmpeg_calls)
    assert any("libvpx-vp9" in c for c in ffmpeg_calls)
    assert any("prores_ks" in c for c in ffmpeg_calls)


def test_render_duration_uses_max_of_audio_and_subtitles(tmp_path, fake_tools):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"AUDIO")
    # audio probes at 4.0s; subtitles end later at 9.0s -> duration 9.0
    lines = [Line("x", [Word("x", 0.0, 9.0)], 0.0, 9.0)]
    render(str(audio), lines, str(tmp_path / "out"), formats=["green"])
    ffmpeg_call = [c for c in fake_tools if c[0] == "/usr/bin/ffmpeg"][0]
    assert ffmpeg_call[ffmpeg_call.index("-t") + 1] == "9.000"


def test_render_missing_audio_raises(tmp_path, fake_tools):
    lines = [Line("x", [Word("x", 0.0, 1.0)], 0.0, 1.0)]
    with pytest.raises(RenderError, match="audio file not found"):
        render(str(tmp_path / "nope.mp3"), lines, str(tmp_path / "out"))


def test_render_unknown_format_raises(tmp_path, fake_tools):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"AUDIO")
    with pytest.raises(RenderError, match="unknown format"):
        render(str(audio), [Line("x", [Word("x", 0, 1)], 0, 1)], str(tmp_path / "o"),
               formats=["gif"])


def test_ffmpeg_failure_surfaces_stderr_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod.shutil, "which", lambda n: "/usr/bin/" + n)

    def failing_run(cmd, capture_output=True):
        joined = " ".join(cmd)
        if "format=duration" in joined:
            return _Proc(stdout=json.dumps({"format": {"duration": "1.0"}}).encode())
        return _Proc(stderr=b"boom: bad filter\n", returncode=1)

    monkeypatch.setattr(render_mod.subprocess, "run", failing_run)
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"A")
    with pytest.raises(RenderError) as exc:
        render(str(audio), [Line("x", [Word("x", 0, 1)], 0, 1)], str(tmp_path / "o"),
               formats=["green"])
    assert "bad filter" in str(exc.value)
    assert "ffmpeg failed" in str(exc.value)