# VisualKit

A Python engine for programmatically building and exporting video timelines —
media clips, text, audio, reusable "compound" clip templates, and
code-rendered visuals (infographics/animations built with HTML/CSS/JS),
composed on a `Timeline` and exported to a standalone video or to a project
file for import into DaVinci Resolve.

> **Status:** phase 1. Core timeline/clip model, coded-visual compilation,
> and export are implemented. Keyframed transforms (position, scale, rotation,
> zoom, opacity) are supported by the FFmpeg exporter and single-clip previews;
> the DaVinci Resolve export ignores keyframes. Transitions, masking/chroma-key,
> and other advanced editing features are on the roadmap (see `notes/`) but
> not yet built.

## Requirements

- Python >= 3.12
- [FFmpeg](https://ffmpeg.org/) on your `PATH`, for standalone video export and for
  encoding animated coded visuals
- A Chrome or Chromium install, for `CodedVisualClip`s and for `TextClip`s exported
  with `FFmpegVideoExporter`. VisualKit never bundles or downloads a browser. It
  looks, in order, at the `VISUALKIT_CHROME` environment variable, your `PATH`,
  the usual install locations, and browsers cached by Playwright/Puppeteer.
  `chrome-headless-shell` is preferred when present (smaller and faster to start).
- Optional: `playwright` (`pip install "visualkit[render]"`), needed only to render
  **animated** coded visuals. It is used purely as a driver for the Chrome above.
  Still visuals, text, and everything else work without it.

## Installation

```bash
pip install -e .              # core
pip install -e ".[render]"    # + animated coded visuals
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
| `02_coded_visuals.py` | `CodedVisualClip`: a bundle with a manifest, typed variables, a still preview, and an animated render |
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

**CodedVisualClip.** References a small HTML/CSS/JS project (a "coded visual"),
such as an animated infographic, either a single `.html` file or a directory
bundle (`index.html` + `manifest.json` + local images/SVGs/CSS/JS). It is *not*
itself media: `CodedVisualCompiler` renders it in headless Chrome into a real
file, a **PNG** for a still visual or an **MP4** for an animated one, and that file
is what the timeline and exporters use. See [Coded visuals](#coded-visuals) below.

**Flattening.** `timeline.flatten()` (used internally by both exporters)
applies template parameters, renders any `CodedVisualClip`s, and expands
`CompoundClip`s into plain clips with absolute timeline coordinates, giving a
timeline made only of `MediaClip`/`TextClip`/`AudioClip`. **It never modifies the
timeline you call it on**, so exporting cannot change your templates. A compound's
own `transform` is composed onto its children, and its content is trimmed to the
compound's `duration`.

## Coded visuals

```python
clip = vk.CodedVisualClip(id="card", source="assets/stat_card", duration=vk.Time(4))
clip.load_manifest()  # canvas size + variable schema from the bundle
clip.set_variable("title", "Active users")
clip.set_variable("accent", "#22c55e")  # typed: a bad color raises immediately
timeline.add_clip(clip)
timeline.export_to_video("out.mp4")  # renders, then composites like any media clip
```

**Design canvas and scaling.** A visual is authored against a fixed design canvas
(`<meta name="canvas-size" content="1920x1080">`, or `canvas_size` in `manifest.json`,
or set on the clip; `clip.design_size` reports the effective one; `canvas_size` itself
is `None` until set explicitly). Put your content inside `.visualkit-canvas`. It is
always rendered at exactly that size and scaled, aspect ratio preserved, to fit
whatever frame it lands in, so the layout never reflows. The 9:16 (vertical), 1:1 and
16:9 cases are all just a different design size.

**Variables and templates.** `{{ name }}` in the HTML is replaced by the
**HTML-escaped** value. Use `{{{ name }}}` for trusted raw HTML. The same values are
available to script as `window.__VARIABLES__.name`, already typed. Variable types
(`string`, `number`, `boolean`, `color`, `asset`, `json`) are enforced. Declare them
in `manifest.json` with labels and descriptions to make a bundle a reusable scene
template. Wrap a visual in a `CompoundClip` and `expose_parameter(...)` to drive it
per instance. Placeholders inside `<style>` are HTML-escaped as well, which is safe
for validated `color`/`number` variables but not for arbitrary strings.

**Local assets.** Images, SVGs, fonts, CSS and JS beside `index.html` load normally.
Editing any of them invalidates the cached render.

**Still vs. animated.** `render_mode` is `auto` by default: a page with motion becomes a
video, a static one a PNG. Detection uses the manifest's `animated` flag if set, else
renders the page at two times and compares. Animation is stepped deterministically
(CSS/Web Animations are seeked; `Date`, `setTimeout`, `setInterval` and
`requestAnimationFrame` run on a virtual clock), so output is identical on every
machine. Frames stream straight into FFmpeg. Pass `render_video=True`/`False` to
`flatten()`/`export_*()` to override.

**Limits.** Determinism is guaranteed for CSS/Web Animations and for the JavaScript timing
APIs listed above. Anything else that depends on real time (`<video>`/`<audio>` elements,
WebGL or canvas code that reads other clocks, network fetches) is **not** guaranteed to be
frame-exact. Pre-render such media and reference it as a normal clip instead. Only
HTML/CSS/JS visuals exist today; other compilers are a possible future extension.

## Exporting

- **`timeline.export_to_video(path, **kwargs)`**: renders a standalone video via
  `FFmpegVideoExporter`. Text size is relative to a 1080p reference frame
  (`font_size=48` is 48px at 1080p) so a 360p preview matches the 1080p render. A failed
  encode raises `ExportError` carrying FFmpeg's own output, and the destination file is
  only replaced on success.
- **`timeline.export_to_resolve(path, **kwargs)`**: writes an NLE project via
  `DaVinciResolveExporter`. `.xml` produces FCP7 XML (XMEML), the more established path
  for DaVinci Resolve. `.fcpxml` produces Apple FCPXML 1.10. NTSC rates (29.97, 23.976,
  59.94) use their exact rational frame rate, and FCPXML times are frame-aligned
  rationals.

  > **Verify in your NLE.** XMEML and FCPXML *position* conventions were implemented from
  > the format specifications and are covered by structural tests, but have **not** been
  > checked against a live DaVinci Resolve import. Test a positioned clip before relying
  > on it. Scale, opacity and timing are the well-trodden parts.

Both exporters accept an `asset_resolver`, a callable or an object with a
`.resolve(str) -> str` method, for mapping abstract source references
(e.g. `asset://b_roll`) to real paths or URLs at export time. See
`visualkit.engine.asset_resolver.DictAssetResolver` or `examples/04_asset_resolvers.py`.

## Errors

All library errors derive from `visualkit.VisualKitError`: `InvalidTimeError`,
`TimelineValidationError`, `TemplateParameterError` (an exposed parameter targets a
missing clip/property, or a protected field such as `id`), `MissingSourceError`,
`ExportError`, and the coded-visual family `CodedVisualError` >
`CodedVisualCompileError` > `BrowserNotFoundError`. Timeline edits (`split_clip`,
`move_clip_track`, and `add_clip`, including a batch of several clips) are atomic: a rejected
edit leaves the timeline exactly as it was.

## Development

```bash
uv sync --group dev        # includes playwright + pillow so the render tests run
pytest
ruff check . && ruff format --check .
```

## License

MIT — see [LICENSE](LICENSE).
