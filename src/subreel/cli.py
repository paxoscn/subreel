"""Command line interface: ``subreel tts`` and ``subreel render``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional, Sequence

from . import __version__, asr as asr_mod, render as render_mod, tts as tts_mod
from .ass import AssStyle
from .render import RenderError
from .timings import TimingsError, load_words, split_lines

logger = logging.getLogger("subreel")

EXIT_OK = 0
EXIT_ERROR = 2


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subreel",
        description=(
            "Turn speech audio into subtitle reels: green-screen H.264, "
            "transparent WebM/ProRes, with word-by-word karaoke highlight."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version="subreel %s" % __version__
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="verbose (INFO) logging"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="only errors (WARNING) logging"
    )

    sub = parser.add_subparsers(dest="command", metavar="{tts,render}")

    # --- tts -------------------------------------------------------------
    p_tts = sub.add_parser(
        "tts",
        help="synthesize speech with edge-tts and capture word timings",
        description=(
            "Synthesize speech to an audio file and write per-word timings "
            "derived from edge-tts WordBoundary events."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = p_tts.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", metavar="FILE", help="read the script from FILE")
    source.add_argument(
        "--text-inline", metavar="STR", help="use the given text directly"
    )
    p_tts.add_argument(
        "--voice",
        default="zh-CN-XiaoxiaoNeural",
        help="edge-tts voice name",
    )
    p_tts.add_argument("--rate", default="+0%", help="speaking rate, e.g. +30%%")
    p_tts.add_argument("--pitch", default="+0Hz", help="pitch shift, e.g. +8Hz")
    p_tts.add_argument("--out", required=True, metavar="AUDIO", help="output audio file")
    p_tts.add_argument(
        "--timings",
        metavar="JSON",
        help="words.json output path (default: alongside --out)",
    )

    # --- render ----------------------------------------------------------
    p_r = sub.add_parser(
        "render",
        help="render subtitle overlays (green MP4 / alpha WebM / alpha MOV)",
        description=(
            "Render karaoke subtitles over a green or transparent canvas, "
            "synced to AUDIO.  Provide timings with --timings (a words.json "
            "file) or with --asr (run faster-whisper on the audio)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_r.add_argument("audio", metavar="AUDIO", help="source audio file")
    p_r.add_argument(
        "--timings",
        metavar="JSON",
        help="words.json word timings (takes precedence over --asr)",
    )
    p_r.add_argument(
        "--asr",
        action="store_true",
        help="derive timings by running faster-whisper on AUDIO",
    )
    p_r.add_argument(
        "--asr-model", default="base", help="faster-whisper model size / name"
    )
    p_r.add_argument(
        "--language", default=None, help="force ASR language (e.g. zh, en)"
    )
    p_r.add_argument(
        "--force-asr",
        action="store_true",
        help="re-run ASR even if a cached words.json exists",
    )

    p_r.add_argument(
        "--formats",
        default="green",
        help="comma-separated subset of: green, webm, mov",
    )
    p_r.add_argument(
        "--out-dir", default="./out", help="directory for outputs"
    )
    p_r.add_argument(
        "--size", default="1280x720", help="canvas size, e.g. 1280x720"
    )
    p_r.add_argument("--fps", type=float, default=30.0, help="frame rate")
    p_r.add_argument(
        "--green", default=render_mod.GREEN_DEFAULT, help="chroma-key green colour"
    )
    p_r.add_argument(
        "--no-audio", action="store_true", help="omit the audio track from outputs"
    )
    p_r.add_argument("--fontsdir", default=None, help="extra font directory for libass")

    p_r.add_argument(
        "--font", default="Noto Sans CJK SC", help="subtitle font name"
    )
    p_r.add_argument("--fontsize", type=int, default=64, help="subtitle font size")
    p_r.add_argument(
        "--align",
        default="bottom",
        choices=sorted(set(["bottom", "center", "middle", "top"])),
        help="vertical alignment",
    )
    p_r.add_argument(
        "--highlight",
        default="#FFE500",
        help="karaoke highlight colour (#RRGGBB, sung words)",
    )
    p_r.add_argument(
        "--color", default="#FFFFFF", help="base subtitle colour (unsung words)"
    )
    p_r.add_argument(
        "--no-fade", action="store_true", help="disable the line fade in/out"
    )
    p_r.add_argument(
        "--max-chars",
        type=float,
        default=22.0,
        help="per-line width budget in CJK cells",
    )
    p_r.add_argument(
        "--max-lines", type=int, default=2, help="soft max lines per sentence"
    )
    p_r.add_argument(
        "--hold", type=float, default=0.3, help="karaoke hold tail (seconds)"
    )

    return parser


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging(args) -> None:
    level = logging.WARNING
    if getattr(args, "verbose", False):
        level = logging.INFO
    if getattr(args, "quiet", False):
        level = logging.ERROR
    logging.basicConfig(
        level=level, stream=sys.stderr, format="%(levelname)s: %(message)s"
    )


# ---------------------------------------------------------------------------
# tts
# ---------------------------------------------------------------------------


def _read_script(args) -> str:
    if args.text_inline is not None:
        return args.text_inline
    with open(args.text, "r", encoding="utf-8") as fh:
        return fh.read()


def cmd_tts(args) -> int:
    try:
        text = _read_script(args)
    except OSError as exc:
        logger.error("cannot read text file: %s", exc)
        return EXIT_ERROR

    timings_path = args.timings or tts_mod.default_timings_path(args.out)

    try:
        data = tts_mod.synthesize(
            text,
            voice=args.voice,
            out=args.out,
            rate=args.rate,
            pitch=args.pitch,
            timings=timings_path,
        )
    except tts_mod.TtsError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR

    ffmpeg_pair = None
    try:
        ffmpeg_pair = render_mod.ensure_ffmpeg()
    except RenderError:
        pass  # duration is nice-to-have, not essential
    duration = 0.0
    if ffmpeg_pair:
        duration = render_mod.probe_duration(ffmpeg_pair[1], args.out)

    print("wrote %s (%s, %.2fs)" % (args.out, _readable_size(args.out), duration))
    print("wrote %s (%d words)" % (timings_path, len(data.words)))
    return EXIT_OK


def _readable_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "size unknown"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return "%d B" % size if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "size unknown"


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _parse_formats(value: str) -> List[str]:
    out: List[str] = []
    for part in value.split(","):
        name = part.strip().lower()
        if name and name not in out:
            out.append(name)
    return out


def _resolve_timings(args) -> Optional[str]:
    """Return a path to a words.json file, or None on failure."""
    if not args.timings and not args.asr:
        logger.error(
            "no timing source: pass --timings words.json, or --asr to run "
            "speech recognition.\n"
            "  subreel render AUDIO --timings words.json\n"
            '  subreel render AUDIO --asr              # needs "subreel[asr]"'
        )
        return None

    if args.timings and args.asr:
        logger.warning("both --timings and --asr given; using --timings")

    if args.timings:
        return args.timings

    # ASR with an on-disk cache next to the outputs.
    cache = os.path.join(
        args.out_dir, os.path.splitext(os.path.basename(args.audio))[0] + ".words.json"
    )
    if os.path.isfile(cache) and not args.force_asr:
        print("reusing cached timings %s (use --force-asr to re-run)" % cache)
        return cache

    try:
        data = asr_mod.transcribe(
            args.audio,
            model_size=args.asr_model,
            language=args.language,
        )
    except asr_mod.AsrError as exc:
        logger.error("%s", exc)
        return None

    os.makedirs(args.out_dir, exist_ok=True)
    data.dump(cache)
    print("wrote %s (%d words, source=%s)" % (cache, len(data.words), data.source))
    return cache


def cmd_render(args) -> int:
    if not os.path.isfile(args.audio):
        logger.error("audio file not found: %s", args.audio)
        return EXIT_ERROR

    formats = _parse_formats(args.formats)
    try:
        width, height = render_mod.parse_size(args.size)
    except RenderError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR

    timings_path = _resolve_timings(args)
    if timings_path is None:
        return EXIT_ERROR

    try:
        data = load_words(timings_path)
    except TimingsError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR

    lines = split_lines(
        data.words,
        max_chars=args.max_chars,
        max_lines=args.max_lines,
        hold=args.hold,
    )
    logger.info(
        "loaded %d words -> %d lines (language=%s, source=%s)",
        len(data.words),
        len(lines),
        data.language,
        data.source,
    )

    style = AssStyle(
        font=args.font,
        fontsize=args.fontsize,
        highlight=args.highlight,
        base=args.color,
        align=args.align,
    )

    try:
        artifacts = render_mod.render(
            args.audio,
            lines,
            args.out_dir,
            formats=formats,
            width=width,
            height=height,
            fps=args.fps,
            green=args.green,
            no_audio=args.no_audio,
            fontsdir=args.fontsdir,
            style=style,
            fade=not args.no_fade,
        )
    except RenderError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR

    for art in artifacts:
        print("%s  %s" % (art.human_size(), art.path))
        print("    %s" % art.summary)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    if args.command == "tts":
        return cmd_tts(args)
    if args.command == "render":
        return cmd_render(args)

    parser.error("unknown command %r" % args.command)
    return EXIT_ERROR  # unreachable; parser.error exits


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())