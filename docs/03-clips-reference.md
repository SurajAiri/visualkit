# Clips reference

```
Clip
├── AudioClip
├── VisualClip                  (transform, keyframes, chroma_key, mask, animation)
│   ├── TextClip
│   ├── MediaClip
│   │   └── CodedVisualClip     (renders to media, then behaves like MediaClip)
└── CompoundClip                 (its own inner Timeline)
```

Every clip shares `BaseClip`:

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Unique across wherever it lives; `Timeline.add_clip` rejects duplicate ids, including within one batch call. |
| `timeline_start` | `Time` | Absolute position on its track (or clip-local position inside a compound's inner timeline). |
| `duration` | `Time` | |
| `speed` | `float` | Playback speed of the underlying source. `1.0` is identity. |

## `VisualClip` (base for `MediaClip`, `TextClip`, `CodedVisualClip`)

Adds, on top of `BaseClip`:

| Field | Type | Notes |
|---|---|---|
| `transform` | `Transform` | `position: Position(x, y)`, `size: Size(width, height)`, `rotation`, `scale`, `zoom`, `opacity`. `Transform.is_identity()` reports whether it changes anything. `Transform.at_anchor("center", ...)` builds a transform at one of 9 standard screen anchors. |
| `keyframes` | `dict[str, PropertyCurve]` | See [06-keyframes-and-effects.md](06-keyframes-and-effects.md). |
| `chroma_key` | `ChromaKey \| None` | FFmpeg-exporter only. |
| `mask` | `Mask \| None` | FFmpeg-exporter only. |
| `animation` | `ClipAnimation \| None` | In/out presets (`fade`, `slide_*`, `pop`, `wipe`), sugar over `keyframes`. FFmpeg-exporter only. |

Useful methods: `is_animated()`, `transform_at(time)` (resolves every keyed
property to a static `Transform` at clip-local `time`), `effective_keyframes()`,
`effective_mask()`, `mask_at(time)`.

> **Important:** the **DaVinci Resolve export ignores `keyframes`,
> `chroma_key`, `mask`, and `animation` entirely** and renders the clip's
> plain static `transform` instead. Only `FFmpegVideoExporter` (and the
> single-clip preview helpers) honor them. If you need those effects to
> survive into an NLE project, they don't yet — that's the current
> boundary of what's implemented, not a bug to route around.

## `MediaClip`

A video or image file placed on a track.

| Field | Type | Notes |
|---|---|---|
| `source` | `Source` | `Source(source: str, start: Time)` — a path (local or `asset://...`) plus an in-file trim offset. A bare string is also accepted where `MediaClip(source=...)` is used directly. |
| `fps` | `float` | |
| `resolution` | `tuple[int, int]` | Must be positive. |
| `source_audio` | `AudioProperties` | `volume: float`, `muted: bool` — the clip's own embedded audio. |
| `linked_clip_id` | `str \| None` | |

`preview_image(time=0.0, *, resolution=None, cache_dir=None, asset_resolver=None, force=False)`
renders one frame of the clip's own source, with its own transform applied,
to a PNG — useful for a quick look without a full export.

## `TextClip`

Text rendered as a visual clip — a `TextClip` **is a `VisualClip`**, so
everything in the table above (keyframes, animation presets, transform)
applies to text exactly like any other visual.

| Field | Type | Notes |
|---|---|---|
| `text` | `str` | |
| `style` | `TextStyle` | See below. |

`TextStyle` fields: `alignment` (`TextAlignment`: `left`/`center`/`right`),
`font_family`, `font_size` (int, **relative to a 1080p reference frame** —
`font_size=48` is 48px at 1080p and scales with export resolution),
`color`, `background_color`, `weight`, `stroke_width` / `stroke_color`
(outline), `shadow_color` / `shadow_offset_x` / `shadow_offset_y` /
`shadow_blur` (drop shadow), `letter_spacing`, `line_height`,
`gradient: TextGradient | None` (`start_color`, `end_color`, `angle` — a
two-stop linear gradient fill). `style.is_bold()` reports whether `weight`
resolves to bold.

`preview_image(*, resolution=None, cache_dir=None)` renders the clip to a
transparent PNG.

## `AudioClip`

| Field | Type | Notes |
|---|---|---|
| `source` | `Source` | |
| `audio_properties` | `AudioProperties` | `volume`, `muted` |
| `linked_clip_id` | `str \| None` | |

## `CodedVisualClip` (a `MediaClip` subclass)

References a small HTML/CSS/JS project instead of a media file. It is
**not itself media** — `CodedVisualCompiler` renders it in headless Chrome
into a real PNG (still) or MP4 (animated), and *that* is what the timeline
and exporters use. Full authoring guide:
[05-coded-visuals.md](05-coded-visuals.md).

| Field | Type | Notes |
|---|---|---|
| `aspect_ratio` | `str \| None` | e.g. `"16:9"`. `None` until set explicitly. |
| `canvas_size` | `Size \| None` | Explicit design canvas. `None` until set explicitly — use `design_size()` for the *effective* value (explicit, else manifest, else 1920x1080). |
| `auto_scale` | `bool` | |
| `render_mode` | `RenderMode` | `AUTO` (default: video if the page has motion, else a still PNG), `IMAGE`, `VIDEO`. |
| `variables` | `dict[str, Variable]` | Typed template variables — see [05-coded-visuals.md](05-coded-visuals.md). |
| `compile_status` | `CompileStatus` | `PENDING` / `COMPILING` / `READY` / `FAILED`. |
| `media_source` | `str \| None` | Set once compiled — the path to the rendered PNG/MP4. Never HTML. |

Key methods: `load_manifest(path=None)`, `define_variable(...)`,
`set_variable(name, value)`, `get_resolved_variables()`,
`get_missing_required_variables()`, `compile(compiler=None, *, force=False)`,
`lint(compiler=None)` (pure-Python pre-flight checks, no Chrome needed),
`validate_bundle(compiler=None)` (checks every local asset reference
resolves to a real file), `preview_image(...)`, `preview_frame(time, ...)`,
`to_media_clip()` / `resolve()` (convert a *compiled* clip into an ordinary
`MediaClip`).

## `CompoundClip`

Groups a nested `Timeline` into a single clip on the parent timeline — the
mechanism for reusable, parameterized templates. Full guide:
[04-templates-and-compounds.md](04-templates-and-compounds.md).

| Field | Type | Notes |
|---|---|---|
| `transform` | `Transform` | Composed onto every child's own transform when flattened. |
| `inner_timeline` | `Timeline \| None` | The nested timeline. A compound that contains its own timeline (a cycle) is rejected by `add_clip` / reported by `flatten`, not infinitely recursed. |
| `linked_clip_id` | `str \| None` | |
| `exposed_parameters` | `list[ExposedParameter]` | Registered via `expose_parameter(...)`. |
| `parameters` | `dict[str, Any]` | Current values, set via `set_parameter(...)`. |

`CompoundAudioClip` is the automatically-created audio-lane counterpart of
a `CompoundClip` (`compound_clip_id`, `volume`, `mute`) — see
[04-templates-and-compounds.md](04-templates-and-compounds.md).

## `Position` / `Size` / `Source`

- `Position(x, y)` — pixels of the *target* canvas. `Position.from_anchor("top_left", margin=20, canvas_size=(1920, 1080))` builds one of the 9 standard screen anchors (corners, edge midpoints, center).
- `Size(width, height)`.
- `Source(source: str, start: Time)` — `source` may be a real path or an
  abstract reference (`asset://...`) resolved later via an `AssetResolver`;
  `start` trims into the source file.
