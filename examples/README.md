# VisualKit Examples

Practical runnable examples demonstrating how to use `visualkit` as a video editing engine library in Python.

---

## Running the Examples

Run any example directly using `uv run python`:

```bash
# 1. Basic multi-track timeline & DaVinci Resolve export
uv run python examples/01_basic_timeline.py

# 2. Coded visuals (HTML/CSS/JS infographics & dynamic variables)
uv run python examples/02_coded_visuals.py

# 3. Reusable compound clip templates & parameter exposure
uv run python examples/03_compound_clips_and_templates.py

# 4. Decoupled asset resolvers (asset:// URIs -> local/cloud media)
uv run python examples/04_asset_resolvers.py
```

---

## Guide to the Examples

### [01_basic_timeline.py](01_basic_timeline.py)
Shows how to:
- Instantiate a `Timeline()`.
- Add `MediaClip`, `TextClip`, and `AudioClip` with start offsets and durations.
- Pass paths directly to `source` (e.g. `MediaClip(source="video.mp4")`).
- Export to DaVinci Resolve (`.xml` / `.fcpxml`) and serialize the timeline to JSON.

### [02_coded_visuals.py](02_coded_visuals.py)
Shows how to:
- Reference a visual **bundle** (`assets/stat_card/`: `index.html`, `manifest.json`, a local `logo.svg`).
- Pull the design canvas and the typed `Variable` schema from the manifest with `load_manifest()`.
- Set typed values (numbers, colors) and see a bad value rejected immediately.
- Render a cheap still preview, then the full animation to MP4 (needs `pip install visualkit[render]`).
- Flatten the timeline, turning the coded visual into a concrete `MediaClip`.

The bundle is also the template to copy when authoring your own: put content in
`.visualkit-canvas`, use `{{ variable }}` placeholders, and declare variables in `manifest.json`.

### [03_compound_clips_and_templates.py](03_compound_clips_and_templates.py)
Shows how to:
- Package multi-track scenes into reusable `CompoundClip` components.
- Expose template parameters (`expose_parameter`) with AI/UI metadata.
- Set parameter overrides dynamically (`set_parameter("key", "value")`).
- Automatically route companion audio to audio tracks.
- Flatten nested compound timelines with cascading speeds and audio volume mixing.

### [04_asset_resolvers.py](04_asset_resolvers.py)
Shows how to:
- Use abstract media identifiers (e.g. `asset://drone_skyline`, `asset://vo_intro`).
- Keep timeline schemas completely decoupled from physical machine paths or CDN storage.
- Provide a `DictAssetResolver` or custom resolver function on export to resolve paths dynamically.
