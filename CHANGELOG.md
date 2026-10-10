# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- GitHub Actions CI (`.github/workflows/ci.yml`): pytest on Python 3.9–3.13,
  byte-compile check, plus a packaging job that builds the sdist + wheel,
  runs `twine check --strict` and smoke-installs the wheel.
- Release workflow (`.github/workflows/release.yml`): pushing a `v*` tag
  publishes to PyPI via OIDC trusted publishing (no stored token) and opens a
  GitHub Release with the artefacts attached.
- `docs/releasing.md` — one-time PyPI trusted-publisher setup and the release
  checklist.

### Changed

- Packaging metadata modernised to PEP 639: `license = "Apache-2.0"` and
  `license-files` replace the legacy table form; the build backend now requires
  `setuptools>=77`.

## [0.1.0] - 2026-09-29

### Added

- `subreel tts` — synthesize speech with edge-tts and capture per-word timings
  from `WordBoundary` events (zero ASR error), written as a documented
  `words.json` file.
- `subreel render` — render word-by-word karaoke subtitles over a green or
  transparent canvas in three flavours:
  - `green`: opaque H.264 MP4 on a `0x00B140` chroma-key background,
  - `webm`: transparent VP9 (`yuva420p`) WebM,
  - `mov`: transparent ProRes 4444 (`yuva444p10le`) MOV.
- `--asr` mode — derive word-level timings for any audio with faster-whisper,
  with an on-disk cache and a Hugging Face mirror hint on download failure.
- Line-breaking with CJK-aware width budgeting, punctuation-priority wrapping
  and a configurable karaoke hold.
- ASS generation with a correct light-on-key colour model, `\kf` per-word
  sweep, optional fade and selectable font/size/alignment/colours.
- Clear, actionable errors: ffmpeg/ffprobe discovery with per-platform install
  commands, and exit code `2` for every recoverable failure.
- Fully offline test suite (76+ tests) covering line-breaking, ASS output,
  words.json validation, the CLI surface and mocked TTS/ASR/ffmpeg paths.

[Unreleased]: https://github.com/paxoscn/subreel/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/paxoscn/subreel/releases/tag/v0.1.0