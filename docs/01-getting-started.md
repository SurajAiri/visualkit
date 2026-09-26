# Getting started

## Requirements

- **Python >= 3.12** to develop against this repo (the packaging metadata
  says `>=3.10`, but treat 3.12 as the supported floor — that's what CI/tests
  target).
- **FFmpeg** on your `PATH` — needed for `export_to_video()` and for
  encoding animated coded visuals.
- **A Chrome or Chromium install** — needed for `CodedVisualClip` (any coded
  visual) and for `TextClip` rendering through `FFmpegVideoExporter`.
  VisualKit never bundles or downloads a browser itself. It looks, in order:
  1. the `VISUALKIT_CHROME` environment variable (a path to the executable),
  2. your `PATH`,
  3. the usual OS install locations,
  4. browsers cached by Playwright/Puppeteer.

  `chrome-headless-shell` is preferred when present (smaller, faster to
  start). If nothing is found, you get `BrowserNotFoundError` with concrete
  fix instructions in the message — that error is designed to be read.
- **Optional: `playwright`** (`pip install "visualkit[render]"`) — only
  needed to render *animated* coded visuals (video). Still visuals, text,
  and everything else works without it.

## Install

```bash
pip install visualkit              # core
pip install "visualkit[render]"    # + animated coded visuals

# with uv
# uv add visualkit
# uv add "visualkit[render]"
```

## dev mode
```bash
uv sync --group dev        # includes playwright + pillow so render tests run
pytest
ruff check . && ruff format --check .
```

## Your first timeline

```python
import visualkit as vk

timeline = vk.Timeline()

video = vk.MediaClip(
    id="main_video",
    source=vk.Source(source="footage.mp4"),
    duration=vk.Time.from_seconds(10),
)
timeline.add_clip(video, track_index=0)

title = vk.TextClip(
    id="title",
    text="Hello, World!",
    timeline_start=vk.Time.from_seconds(1),
    duration=vk.Time.from_seconds(3),
)
timeline.add_clip(title, track_index=1)

# Export to a standalone MP4 (requires ffmpeg, and Chrome for the TextClip)
timeline.export_to_video("output/hello.mp4")

# ...or to a DaVinci Resolve project
timeline.export_to_resolve("output/hello_resolve.xml")
```

A few things worth noticing immediately, because they shape everything else:

- `timeline.add_clip(clip, track_index=N)` **routes by clip type** —
  `AudioClip` always lands on an audio track, everything else on a video
  track — and provisions tracks up to `N` if they don't exist yet. You never
  manually decide "is this an audio track."
- `MediaClip.source` accepts either a `Source(...)` instance or a bare
  string path — both examples above are valid; `Source` also carries an
  in-file trim offset (`start`).
- Nothing here is validated against the filesystem until export time.
  Building a `Timeline` in memory never touches disk or ffmpeg.

## Where to go next

Every feature area has a matching runnable script in `examples/` — read the
source, then run it:

```bash
uv run python examples/01_basic_timeline.py
uv run python examples/02_coded_visuals.py
uv run python examples/03_compound_clips_and_templates.py
uv run python examples/04_asset_resolvers.py
uv run python examples/05_keyframes_and_effects.py
```

Then read [02-concepts.md](02-concepts.md) for the model these examples all
build on.
