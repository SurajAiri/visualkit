# VisualKit

A Python engine for programmatically building and exporting video timelines —
media clips, text, audio, reusable "compound" clip templates, and
code-rendered visuals (infographics/animations built with HTML/CSS/JS),
composed on a `Timeline` and exported to a standalone video or to a project
file for import into DaVinci Resolve.

> **Status:** phase 1. Core timeline/clip model, coded-visual compilation,
> and export are implemented. Keyframes, transitions, masking/chroma-key,
> and other advanced editing features are on the roadmap (see `notes/`) but
> not yet built.

## Requirements

- Python >= 3.12
- [FFmpeg](https://ffmpeg.org/) on your `PATH`, for standalone video export
- A Chrome or Chromium install, for rendering `CodedVisualClip`s (and
  `TextClip`s exported via `FFmpegVideoExporter`) — VisualKit looks for a
  system install; it does not bundle a browser

## Installation

```bash
pip install -e .
```

(This project isn't yet published to PyPI; install from a local checkout.)

## Quick start

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

See `examples/` for runnable walkthroughs of each feature area:

| Example | Covers |
|---|---|
| `01_basic_timeline.py` | Building a timeline from media/text/audio clips, multi-track layout, exporting |
| `02_coded_visuals.py` | `CodedVisualClip`: rendering an HTML/CSS/JS bundle into a media clip |
| `03_compound_clips_and_templates.py` | `CompoundClip` as a grouping/template mechanism with exposed `Variable`s |
| `04_asset_resolvers.py` | Resolving abstract asset references (`asset://...`) to real files at export time |

## Core concepts

**Timeline & Tracks.** A `Timeline` holds a list of video tracks and a list
of audio tracks (`Track[Clip]`). `timeline.add_clip(clip, track_index=N)`
routes a clip to the right lane automatically based on its type, creating
tracks up to `N` as needed. Clips can be inserted in `OVERLAP` (default) or
`RIPPLE` mode; ripple-inserting into a point that falls inside an existing
clip's span raises `InvalidTrackOperationError` rather than silently
producing an overlapping timeline.

**Clips.** `MediaClip` (video/image files), `AudioClip`, `TextClip`, and
`CodedVisualClip` all share a common `BaseClip` (id, timing, speed). Visual
clips (`MediaClip`, `TextClip`, `CodedVisualClip`) additionally carry a
`Transform` (position, scale, rotation, opacity).

**CompoundClip.** Groups a nested `Timeline` (its `inner_timeline`) into a
single clip on the parent timeline — useful for building reusable templates.
Exposed `Variable`s let a compound clip's inner text/parameters be
overridden per-instance (`compound.set_parameter(name, value)`) without
touching the inner timeline's structure. A compound's own `speed` compresses
its entire inner timeline proportionally when flattened.

**CodedVisualClip.** References a small HTML/CSS/JS project (a "coded
visual") — e.g. an animated infographic — that gets compiled by
`CodedVisualCompiler` into a concrete media file (a still image if
`render_video=False`, or a video via headless Chrome + ffmpeg if
`render_video=True`) before export. The coded visual's own aspect ratio is
preserved and scaled to fit its `Transform`/canvas without distorting the
layout.

**Flattening.** `timeline.flatten()` (used internally by both exporters)
resolves `Variable`s, compiles any `CodedVisualClip`s, and expands
`CompoundClip`s into plain clips with absolute timeline coordinates —
producing a timeline made only of `MediaClip`/`TextClip`/`AudioClip`.

## Exporting

- **`timeline.export_to_video(path, **kwargs)`** — renders a standalone
  video file via `FFmpegVideoExporter`. Requires `ffmpeg` on `PATH`; `.html`-
  based clips (`TextClip`, `CodedVisualClip`) additionally require a
  Chrome/Chromium install to rasterize.
- **`timeline.export_to_resolve(path, **kwargs)`** — writes an NLE project
  file via `DaVinciResolveExporter`. `.xml` produces FCP7 XML (XMEML), the
  more established path for DaVinci Resolve; `.fcpxml` produces Apple
  FCPXML v1.10 (its exact spine/lane layout hasn't been verified against a
  real Resolve import — prefer XMEML if you hit import issues).

Both exporters accept an `asset_resolver` — a callable or an object with a
`.resolve(str) -> str` method — for mapping abstract source references
(e.g. `asset://b_roll`) to real file paths or URLs at export time. See
`visualkit.engine.asset_resolver.DictAssetResolver` for a simple built-in
resolver, or `examples/04_asset_resolvers.py`.

## Development

```bash
uv sync --group dev   # or: pip install -e ".[dev]" equivalent via pyproject dependency-groups
pytest
ruff check .
```

## License

MIT — see [LICENSE](LICENSE).
