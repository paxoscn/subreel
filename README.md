# subreel

**Turn speech audio into subtitle reels: green-screen H.264, transparent
WebM/ProRes, with word-by-word karaoke highlight.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/paxoscn/subreel/actions/workflows/ci.yml/badge.svg)](https://github.com/paxoscn/subreel/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/subreel.svg)](https://pypi.org/project/subreel/)
[![PyPI - Python versions](https://img.shields.io/pypi/pyversions/subreel.svg)](https://pypi.org/project/subreel/)
[![No runtime deps](https://img.shields.io/badge/runtime%20deps-none-success.svg)](#installation)

subreel is a small, dependency-free CLI that turns a voice-over into a subtitle
clip you can drop straight onto a video timeline. It renders the subtitles onto
a chroma-key green background (for editors that key out green) or onto a
transparent canvas (for editors that take alpha directly), and it lights up each
word as it is spoken — classic karaoke style.

Two ways to get the timeline:

1. **`subreel tts` — the accurate path.** Synthesize the speech with
   [edge-tts](https://github.com/rany2/edge-tts) and capture the per-word
   timestamps straight from the synthesis events. The subtitle timing is exact,
   because it comes from the same engine that produced the audio — **zero ASR
   error**.
2. **`subreel render --asr` — the any-audio path.** Run
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on any existing
   audio file to get word-level timestamps.

---

## Features

- **Three output flavours** from one command:
  - **Green-screen MP4** — H.264 / `yuv420p`, ready for chroma key in 剪映, Premiere, DaVinci, Final Cut.
  - **Transparent WebM** — VP9 with an alpha channel (`yuva420p`).
  - **Transparent ProRes 4444 MOV** — with alpha (`yuva444p10le`), for Premiere / Final Cut / DaVinci.
- **Per-word karaoke highlight** — each word is wrapped in an ASS `\kf` sweep,
  so the current and already-sung words are drawn in the highlight colour.
- **edge-tts precise timelines** — word timings captured from `WordBoundary`
  events, no speech recognition involved.
- **Whisper ASR fallback** — word-level recognition for audio you did not
  synthesize, with caching.
- **Zero mandatory Python dependencies** — ffmpeg is the only system
  requirement; `edge-tts` and `faster-whisper` are opt-in extras.
- **A documented, portable timeline format** — the [`words.json`](#wordsjson-timing-format) file.

<!-- Demo — uncomment and add the files when they are recorded.
<p align="center">
  <img src="docs/demo-green.gif"   alt="Green-screen karaoke subtitles" width="640">
  <img src="docs/demo-alpha.gif"   alt="Transparent karaoke subtitles"  width="640">
</p>
-->

---

## Installation

### 1. ffmpeg (required)

subreel shells out to `ffmpeg` / `ffprobe` and checks for them at startup.

| Platform        | Command                                    |
| --------------- | ------------------------------------------ |
| Ubuntu / Debian | `sudo apt install ffmpeg`                  |
| macOS           | `brew install ffmpeg`                      |
| Windows         | `winget install Gyan.FFmpeg`               |
| Conda           | `conda install -c conda-forge ffmpeg`      |

For CJK subtitles, install a CJK font as well (e.g. `fonts-noto-cjk` on Debian
/ Ubuntu); the default style uses `Noto Sans CJK SC`.

### 2. subreel

```bash
# from PyPI (recommended)
pip install subreel

# or the latest development snapshot
pip install "git+https://github.com/paxoscn/subreel.git"
```

With the optional features (PyPI extras — when installing from GitHub, append
them to the URL as `#egg=subreel[tts]`):

```bash
# edge-tts synthesis (subreel tts)
pip install "subreel[tts]"

# faster-whisper ASR (subreel render --asr)
pip install "subreel[asr]"

# both
pip install "subreel[tts,asr]"
```

---

## Quick start

### A. Synthesize *and* render (most accurate)

```bash
# 1. make the voice-over plus its exact word timings
subreel tts \
  --text script.txt \
  --voice zh-CN-XiaoxiaoNeural \
  --rate +15% \
  --out voice.mp3
# -> voice.mp3  and  voice.words.json

# 2. render all three flavours
subreel render voice.mp3 \
  --timings voice.words.json \
  --formats green,webm,mov \
  --out-dir out
# -> out/subs-green.mp4, out/subs-alpha.webm, out/subs-alpha.mov
```

### B. You already have audio — let Whisper transcribe it

```bash
subreel render narration.m4a --asr --asr-model small --formats green,webm
```

The recognised timings are cached to `out/narration.words.json` and reused on
the next run (pass `--force-asr` to re-run).

### C. You already have timings

Any tool that emits the [`words.json`](#wordsjson-timing-format) format can
drive subreel:

```bash
subreel render voice.mp3 --timings my-alignment.json --formats mov
```

### Decoding the transparent WebM from the command line

`subs-alpha.webm` carries its alpha channel as a VP9 *BlockAdditional* layer
(`alpha_mode=1`).  NLEs and browsers handle this natively, but ffmpeg's
**native** `vp9` decoder silently drops that layer, so a plain
`ffmpeg -i subs-alpha.webm frame.png` yields an opaque black frame.  Decode
with libvpx instead:

```bash
ffmpeg -c:v libvpx-vp9 -i subs-alpha.webm -frames:v 1 frame.png   # RGBA, alpha intact
```

The ProRes `.mov` needs no such flag — every ffmpeg/ProRes toolchain reads its
alpha directly.

---

## Compositing guide

All three outputs are subtitle *overlays*: they contain only the text (and the
audio), so you place them on top of your footage and key out the background.

### 剪映 (CapCut / JianYing)

1. Import `subs-green.mp4` and drop it on a track above your video.
2. Select the clip → **画面 (Picture)** → **抠像 (Key)** → **色度抠图 (Chroma key)**.
3. Pick the key colour from the green background — it is `0x00B140`
   (RGB `0, 177, 64`). Use the eyedropper on the green area.
4. Raise **强度 (Strength)** until the green is fully gone, then adjust
   **阴影 (Shadow)** to clean up the antialiased edges around the glyphs.

### Adobe Premiere Pro

- **Green MP4**: apply **Ultra Key**, eyedrop the green, set *Matte Generation*
  → *Tolerance* ~ 30–40 % and *Pedestal* ~ 10 %.
- **Transparent WebM / MOV**: just drop `subs-alpha.webm` (VP9 with alpha) or
  `subs-alpha.mov` (ProRes 4444) onto the timeline — no keying needed.

### DaVinci Resolve

- **Green MP4**: add a **3D Keyer** node, eyedrop the green, then refine with
  the *Clean Black* / *Clean White* controls.
- **Transparent MOV**: import `subs-alpha.mov` and place it on a higher track;
  Resolve honours the ProRes 4444 alpha directly.

### Final Cut Pro

- **Green MP4**: apply the **Keyer** effect and pick the green.
- **Transparent MOV**: add `subs-alpha.mov` above your footage — the alpha is
  used automatically.

### Any NLE

Transparent WebM (VP9 `yuva420p`) and transparent MOV (ProRes 4444) can be
dragged straight onto the timeline in Premiere, DaVinci and Final Cut with no
keying. If your editor is unhappy with VP9 alpha, use the MOV.

---

## `words.json` timing format

subreel's public interchange format. Times are in **seconds** (`float`).

```json
{
  "language": "zh",
  "source": "edge-tts",
  "words": [
    { "text": "你", "start": 0.12, "end": 0.31 },
    { "text": "好", "start": 0.31, "end": 0.58 }
  ]
}
```

| Field      | Type   | Required | Notes                                                        |
| ---------- | ------ | -------- | ------------------------------------------------------------ |
| `words`    | array  | yes      | Non-empty list of word objects.                              |
| `words[].text`  | string | yes | The word or character as it should be displayed.        |
| `words[].start` | number | yes | Start time in seconds.                                  |
| `words[].end`   | number | yes | End time in seconds; must be strictly greater than `start`. |
| `language` | string | no       | Best-effort language tag (e.g. `zh`, `en`).                  |
| `source`   | string | no       | Free-form provenance (`edge-tts`, `faster-whisper`, …).      |

Validation rules (enforced on load, with a clear error otherwise):

- `words` must be present and non-empty;
- every word needs `text` (string) and numeric `start` / `end`;
- `start < end` for every word;
- `start` values are monotonically non-decreasing (equal is allowed, so two
  words may share a boundary).

---

## CLI reference

```
subreel [-h] [--version] [-v] [-q] {tts,render} ...
```

Global options: `--version`, `-v/--verbose` (INFO logging), `-q/--quiet`.

### `subreel tts`

```
subreel tts (--text FILE | --text-inline STR) [--voice VOICE]
            [--rate RATE] [--pitch PITCH] --out AUDIO [--timings JSON]
```

| Option              | Default                  | Description                                   |
| ------------------- | ------------------------ | --------------------------------------------- |
| `--text FILE`       | —                        | Read the script from a UTF-8 file.            |
| `--text-inline STR` | —                        | Use the given text directly.                  |
| `--voice`           | `zh-CN-XiaoxiaoNeural`   | edge-tts voice name.                          |
| `--rate`            | `+0%`                    | Speaking rate, e.g. `+30%`.                   |
| `--pitch`           | `+0Hz`                   | Pitch shift, e.g. `+8Hz`.                     |
| `--out`             | *(required)*             | Output audio file.                            |
| `--timings`         | next to `--out`          | words.json output path.                       |

### `subreel render`

```
subreel render AUDIO [--timings JSON] [--asr] [--asr-model M] [--language L]
               [--force-asr] [--formats F] [--out-dir DIR] [--size WxH]
               [--fps N] [--green HEX] [--no-audio] [--fontsdir DIR]
               [--font NAME] [--fontsize N] [--align POS] [--highlight HEX]
               [--color HEX] [--no-fade] [--max-chars N] [--max-lines N]
               [--hold SEC]
```

| Option          | Default             | Description                                                    |
| --------------- | ------------------- | -------------------------------------------------------------- |
| `AUDIO`         | *(required)*        | Source audio file.                                             |
| `--timings`     | —                   | words.json word timings (takes precedence over `--asr`).       |
| `--asr`         | off                 | Derive timings with faster-whisper.                            |
| `--asr-model`   | `base`              | faster-whisper model size / name.                              |
| `--language`    | auto                | Force the ASR language (e.g. `zh`, `en`).                      |
| `--force-asr`   | off                 | Re-run ASR even if a cached words.json exists.                |
| `--formats`     | `green`             | Comma-separated subset of `green`, `webm`, `mov`.              |
| `--out-dir`     | `./out`             | Output directory (created if missing).                        |
| `--size`        | `1280x720`          | Canvas size.                                                   |
| `--fps`         | `30`                | Frame rate.                                                    |
| `--green`       | `0x00B140`          | Chroma-key green colour for the `green` format.               |
| `--no-audio`    | off                 | Omit the audio track from the outputs.                        |
| `--fontsdir`    | —                   | Extra font directory for libass.                              |
| `--font`        | `Noto Sans CJK SC`  | Subtitle font name.                                            |
| `--fontsize`    | `64`                | Subtitle font size.                                            |
| `--align`       | `bottom`            | `bottom`, `center`/`middle` or `top`.                          |
| `--highlight`   | `#FFE500`           | Karaoke highlight colour (sung words), `#RRGGBB`.              |
| `--color`       | `#FFFFFF`           | Base colour (not-yet-sung words).                             |
| `--no-fade`     | off                 | Disable the per-line fade in/out.                             |
| `--max-chars`   | `22`                | Per-line width budget, in CJK cells.                          |
| `--max-lines`   | `2`                 | Soft maximum lines per sentence.                              |
| `--hold`        | `0.3`               | Karaoke hold tail, in seconds.                                |

**Exit codes:** `0` on success, `2` for every recoverable error (missing
ffmpeg, missing audio, no timing source, bad words.json, ffmpeg failure).

---

## Development

```bash
git clone https://github.com/paxoscn/subreel.git
cd subreel
pip install -e ".[dev,tts,asr]"

# run the offline test suite (no network, no model downloads)
python3 -m pytest tests/ -q

# byte-compile check
python3 -m compileall src/
```

The tests mock `edge-tts`, `faster-whisper` and `ffmpeg`, so they run anywhere.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the suite on
Python 3.9–3.13, then builds the sdist + wheel, `twine check --strict`s the
metadata and smoke-installs the wheel. Release automation (tag → PyPI via OIDC
trusted publishing) is documented in [`docs/releasing.md`](docs/releasing.md).

---

## License

[Apache-2.0](LICENSE) © 2026 paxoscn

---

## Credits

subreel stands on the shoulders of these projects:

- [**ffmpeg**](https://ffmpeg.org/) — probing, filtering and encoding;
- [**libass**](https://github.com/libass/libass) — ASS subtitle rendering (via
  ffmpeg's `ass` filter);
- [**edge-tts**](https://github.com/rany2/edge-tts) — neural text-to-speech and
  word-boundary timings;
- [**faster-whisper**](https://github.com/SYSTRAN/faster-whisper) — fast
  word-level speech recognition.