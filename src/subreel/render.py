"""ffprobe probing and ffmpeg invocation for the three output flavours.

All ffmpeg calls are built as argument **lists** (never a shell string) and run
through :func:`subprocess.run` with captured output, so paths with spaces or
non-ASCII characters are safe.  Failures surface the tail of ffmpeg's stderr.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .ass import AssStyle, write_ass
from .timings import Line

__all__ = [
    "RenderError",
    "Artifact",
    "ensure_ffmpeg",
    "probe_duration",
    "probe_media_summary",
    "escape_filter_path",
    "parse_size",
    "build_command",
    "render",
    "FORMATS",
    "GREEN_DEFAULT",
]

#: Supported output formats and the file each produces.
FORMATS = {
    "green": "subs-green.mp4",
    "webm": "subs-alpha.webm",
    "mov": "subs-alpha.mov",
}

#: Chroma-key green that keyers pick cleanly (matches common NLE presets).
GREEN_DEFAULT = "0x00B140"

_INSTALL_HINT = (
    "ffmpeg (and ffprobe) not found on PATH.\n"
    "Install it with one of:\n"
    "  Ubuntu/Debian : sudo apt install ffmpeg\n"
    "  macOS         : brew install ffmpeg\n"
    "  Windows       : winget install Gyan.FFmpeg\n"
    "  Conda         : conda install -c conda-forge ffmpeg"
)


class RenderError(RuntimeError):
    """A recoverable rendering failure; the CLI turns this into exit code 2."""


@dataclass
class Artifact:
    """A produced output file plus a one-line ffprobe summary."""

    path: str
    size: int
    summary: str
    format: str

    def human_size(self) -> str:
        size = float(self.size)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024 or unit == "GiB":
                return "%.1f %s" % (size, unit) if unit != "B" else "%d B" % self.size
            size /= 1024
        return "%d B" % self.size


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


def ensure_ffmpeg() -> Tuple[str, str]:
    """Return the ``(ffmpeg, ffprobe)`` executable paths or raise."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    missing = [name for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not path]
    if missing:
        raise RenderError(
            "missing required tool(s): %s\n%s" % (", ".join(missing), _INSTALL_HINT)
        )
    return ffmpeg, ffprobe


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True)


def _check(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    proc = _run(cmd)
    if proc.returncode != 0:
        tail = _stderr_tail(proc.stderr, lines=40)
        raise RenderError(
            "ffmpeg failed (exit %d)\n  command: %s\n%s"
            % (proc.returncode, " ".join(cmd), tail)
        )
    return proc


def _stderr_tail(stderr, lines: int = 40) -> str:
    if not stderr:
        return "  (no stderr output)"
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    tail = stderr.strip().splitlines()[-lines:]
    return "\n".join("  " + ln for ln in tail)


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def probe_duration(ffprobe: str, path: str) -> float:
    """Return the container duration in seconds, or ``0.0`` if unknown."""
    proc = _check(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ]
    )
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
        return float(data["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def probe_media_summary(ffprobe: str, path: str) -> str:
    """Return a one-line ``video: ...; audio: ...`` summary of a file."""
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,profile,pix_fmt,width,height",
            "-of",
            "json",
            path,
        ]
    )
    if proc.returncode != 0:
        return "unreadable"
    try:
        streams = json.loads(proc.stdout.decode("utf-8", "replace") or "{}").get(
            "streams", []
        )
    except ValueError:
        return "unreadable"
    parts: List[str] = []
    for st in streams:
        kind = st.get("codec_type", "?")
        codec = st.get("codec_name", "?")
        bits = codec
        profile = st.get("profile")
        if profile and profile not in ("unknown", "Unknown"):
            bits += " (%s)" % profile
        pix = st.get("pix_fmt")
        if pix:
            bits += " [%s]" % pix
        if st.get("width") and st.get("height"):
            bits += " %sx%s" % (st["width"], st["height"])
        parts.append("%s: %s" % (kind, bits))
    return ", ".join(parts) if parts else "no streams"


# ---------------------------------------------------------------------------
# Filter escaping
# ---------------------------------------------------------------------------


def escape_filter_path(path: str) -> str:
    """Escape a filesystem path for use *inside* an ffmpeg filtergraph value.

    Backslashes are normalised to forward slashes (so Windows paths work), the
    filtergraph metacharacters ``: ' , ; [ ]`` are backslash-escaped, and the
    whole value keeps working when it contains spaces.
    """
    path = path.replace("\\", "/")
    out: List[str] = []
    for ch in path:
        if ch in ":',;[]":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _ass_filter(ass_path: str, fontsdir: Optional[str], alpha: bool = False) -> str:
    """Build the ``ass=...`` filter value.

    ``alpha=1`` is required whenever the canvas carries an alpha channel: the
    ffmpeg ``ass`` filter does not composite the subtitle's own alpha plane by
    default (its ``alpha`` option defaults to false), which would make the text
    vanish into a fully transparent frame.
    """
    value = "ass=" + escape_filter_path(os.path.abspath(ass_path))
    if fontsdir:
        value += ":fontsdir=" + escape_filter_path(os.path.abspath(fontsdir))
    if alpha:
        value += ":alpha=1"
    return value


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------


def parse_size(value: str) -> Tuple[int, int]:
    """Parse ``"WxH"`` (also ``W:H``) into ``(width, height)``."""
    for sep in ("x", "X", ":", "*"):
        if sep in value:
            left, _, right = value.partition(sep)
            try:
                w, h = int(left), int(right)
            except ValueError:
                break
            if w > 0 and h > 0:
                return w, h
            break
    raise RenderError("invalid --size %r; expected e.g. 1280x720" % (value,))


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def build_command(
    fmt: str,
    *,
    ffmpeg: str,
    audio: Optional[str],
    ass_path: str,
    width: int,
    height: int,
    fps: float,
    duration: float,
    out_path: str,
    green: str = GREEN_DEFAULT,
    fontsdir: Optional[str] = None,
    no_audio: bool = False,
) -> List[str]:
    """Assemble the ffmpeg argv for one output format."""
    if fmt not in FORMATS:
        raise RenderError(
            "unknown format %r; choose from %s" % (fmt, ", ".join(sorted(FORMATS)))
        )

    a = _fmt_num(fps)
    dur = "%.3f" % max(duration, 0.001)
    has_audio = bool(audio) and not no_audio
    alpha = fmt in ("webm", "mov")
    ass = _ass_filter(ass_path, fontsdir, alpha=alpha)

    cmd: List[str] = [ffmpeg, "-y"]

    if fmt == "green":
        cmd += ["-f", "lavfi", "-i", "color=c=%s:s=%dx%d:r=%s" % (green, width, height, a)]
    else:
        # A genuinely transparent canvas: append ",format=rgba" inside the
        # lavfi graph, otherwise the color source negotiates yuv420p and drops
        # the @0 alpha before the subtitles are drawn.
        cmd += [
            "-f",
            "lavfi",
            "-i",
            "color=c=black@0:s=%dx%d:r=%s,format=rgba" % (width, height, a),
        ]

    if has_audio:
        cmd += ["-i", audio]

    if fmt == "green":
        cmd += ["-vf", ass]
    elif fmt == "webm":
        cmd += ["-vf", ass + ",format=yuva420p"]
    else:  # mov
        cmd += ["-vf", ass + ",format=yuva444p10le"]

    cmd += ["-map", "0:v"]
    if has_audio:
        cmd += ["-map", "1:a?"]

    if fmt == "green":
        cmd += [
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            "-preset", "medium",
        ]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]
    elif fmt == "webm":
        cmd += [
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",
            "-b:v", "0",
            "-crf", "30",
            "-deadline", "good",
            "-cpu-used", "2",
            "-auto-alt-ref", "0",  # required for a usable alpha plane
        ]
        if has_audio:
            cmd += ["-c:a", "libopus", "-b:a", "128k"]
        else:
            cmd += ["-an"]
    else:  # mov
        cmd += [
            "-c:v", "prores_ks",
            "-profile:v", "4444",
            "-pix_fmt", "yuva444p10le",
        ]
        if has_audio:
            cmd += ["-c:a", "pcm_s16le"]
        else:
            cmd += ["-an"]

    cmd += ["-t", dur, out_path]
    return cmd


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return "%g" % value


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(
    audio: Optional[str],
    lines: List[Line],
    out_dir: str,
    formats: Sequence[str] = ("green",),
    *,
    width: int = 1280,
    height: int = 720,
    fps: float = 30,
    green: str = GREEN_DEFAULT,
    no_audio: bool = False,
    fontsdir: Optional[str] = None,
    style: Optional[AssStyle] = None,
    fade: bool = True,
) -> List[Artifact]:
    """Render every requested format and return the produced artifacts.

    Raises :class:`RenderError` on any failure (the CLI maps this to exit 2).
    """
    ffmpeg, ffprobe = ensure_ffmpeg()

    for fmt in formats:
        if fmt not in FORMATS:
            raise RenderError(
                "unknown format %r; choose from %s"
                % (fmt, ", ".join(sorted(FORMATS)))
            )

    os.makedirs(out_dir, exist_ok=True)

    ass_path = os.path.join(out_dir, "subs.ass")
    write_ass(ass_path, lines, width, height, style=style, fade=fade)

    audio_duration = 0.0
    if audio and not no_audio:
        if not os.path.isfile(audio):
            raise RenderError("audio file not found: %s" % audio)
        audio_duration = probe_duration(ffprobe, audio)

    subtitle_end = lines[-1].end if lines else 0.0
    duration = max(audio_duration, subtitle_end)

    artifacts: List[Artifact] = []
    for fmt in formats:
        out_path = os.path.join(out_dir, FORMATS[fmt])
        cmd = build_command(
            fmt,
            ffmpeg=ffmpeg,
            audio=audio,
            ass_path=ass_path,
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            out_path=out_path,
            green=green,
            fontsdir=fontsdir,
            no_audio=no_audio,
        )
        _check(cmd)
        artifacts.append(
            Artifact(
                path=out_path,
                size=os.path.getsize(out_path),
                summary=probe_media_summary(ffprobe, out_path),
                format=fmt,
            )
        )

    return artifacts