# Exporting

There are two exporters, and they support meaningfully different subsets of
the model — pick based on where the output is going, not by default.

| | `export_to_video()` | `export_to_resolve()` |
|---|---|---|
| Backing exporter | `FFmpegVideoExporter` | `DaVinciResolveExporter` |
| Output | Standalone MP4/WebM | FCP7 XML (XMEML) or Apple FCPXML 1.10, for import into DaVinci Resolve |
| Keyframes / chroma key / masks / animation presets | ✅ honored | ❌ ignored — plain static `transform` only |
| Extended text styling (outline, shadow, gradient, letter spacing) | ✅ | ❌ |
| Alpha / transparency for animated coded visuals | ✅ (`render.mkv`, lossless FFV1) | ❌ (flat `render.mp4`) |

## `timeline.export_to_video(path, **kwargs)`

```python
timeline.export_to_video(
    "output/hello.mp4",
    fps=30.0, resolution=(1920, 1080),
    video_codec="libx264", audio_codec="aac",
    asset_resolver=None,
)
```

- Text size is relative to a **1080p reference frame** — `font_size=48` on
  a `TextStyle` is 48px at 1080p and scales proportionally with the actual
  export resolution, so a 360p preview and a 1080p render agree on how big
  the text looks.
- A failed encode raises `ExportError` carrying FFmpeg's own stderr —
  read it, it's the actual diagnostic.
- The destination file is only replaced on success — a failed export never
  leaves a partial/corrupt file at `path`.

## `timeline.export_to_resolve(path, **kwargs)`

```python
timeline.export_to_resolve(
    "output/hello_resolve.xml",           # .xml -> XMEML, .fcpxml -> FCPXML
    fps=30.0, resolution=(1920, 1080),
    project_name="VisualKit Project", sequence_name="VisualKit Sequence",
    asset_resolver=None,
)
```

- `.xml` → FCP7 XML (XMEML) — the more established, wider-compatibility
  path for DaVinci Resolve.
- `.fcpxml` → Apple FCPXML 1.10.
- NTSC rates (29.97, 23.976, 59.94) use their exact rational frame rate
  (an hour at 29.97 is exactly 107,892 frames, not 108,000); FCPXML times
  are frame-aligned rationals throughout.

> **Verify in your NLE before relying on positioning.** XMEML and FCPXML
> *position* conventions were implemented from the format specifications
> and are covered by structural tests, but have **not** been checked
> against a live DaVinci Resolve import as of this writing. Test a
> positioned clip in Resolve itself before depending on exact placement.
> Scale, opacity, and timing are the well-trodden, higher-confidence parts.

## Asset resolvers

Keep timeline schemas decoupled from concrete file paths — reference
media abstractly (`asset://drone_skyline`) and resolve it only at export
time:

```python
from visualkit.engine import DictAssetResolver

timeline.add_clip(vk.MediaClip(id="broll", source="asset://drone_skyline", duration=vk.Time(5)))

resolver = DictAssetResolver({"asset://drone_skyline": "/real/path/drone.mp4"})
timeline.export_to_video("out.mp4", asset_resolver=resolver)
```

Both exporters accept `asset_resolver` as any callable `str -> str` or an
object exposing `.resolve(str) -> str`. This is the seam for backing media
with S3/CDN URLs, a CMS, or an agent-maintained asset index instead of
local disk paths — see `examples/04_asset_resolvers.py`.

## Inspecting before exporting

```python
flat = timeline.flatten()          # resolve variables, compile coded visuals, expand compounds
print(flat.duration())
print(flat.model_dump_json(indent=2))
```

Useful when you want to sanity-check a template's output (e.g. an agent
confirming a compound's parameters resolved the way it expected) before
committing to an actual FFmpeg/Resolve export. See
[02-concepts.md](02-concepts.md) for exactly what `flatten()` does and its
non-mutation guarantee.
