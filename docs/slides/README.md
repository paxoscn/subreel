# Scenario slides

Diagram slides for the three `subreel` workflows (A: script → tts + timings,
B: existing audio → ASR, C: existing `words.json` → render). Each slide is
1920×1080 and reads left → right: **input → subreel command → green-screen
result**.

| File | What |
| ---- | ---- |
| `scenarios.html` | Hand-written source. All three slides live in one file, stacked, 1080px tall each. |
| `assets/frame-*.png` | Real frames pulled from an actual `subs-green.mp4` render (and `alpha-comp.png`, a transparent-WebM frame composited over a checkerboard). |
| `../images/scenario-*.png` | The rendered deliverables. |

## Re-rendering after an edit

The page is 1920 × (1080 × 3) with no margins, so one tall capture crops
cleanly into three slides:

```bash
cd docs/slides
google-chrome-stable --headless=new --disable-gpu --no-sandbox \
  --disable-dev-shm-usage --hide-scrollbars --force-device-scale-factor=1 \
  --window-size=1920,3240 --virtual-time-budget=9000 \
  --screenshot=/tmp/all.png "file://$PWD/scenarios.html"

python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/all.png')                     # must be 1920x3240
assert im.size == (1920, 3240), im.size
for i, n in enumerate(('a', 'b', 'c')):
    im.crop((0, i*1080, 1920, (i+1)*1080)).save(f'../images/scenario-{n}.png', optimize=True)
PY
```

Notes / pitfalls

- `--headless=new` is required; the old `--headless` fails silently (no PNG).
- `--disable-dev-shm-usage` is needed on hosts with a small `/dev/shm`.
- Keep the wide column narrow enough for the monospace command blocks: the
  command box is `white-space: pre`, so a too-long line does **not** wrap — it
  overflows, which the DOM audit (`scrollWidth > clientWidth`) catches.
- Fonts: "Noto Sans CJK SC" for text, "Noto Sans Mono CJK SC" for code.