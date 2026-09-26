# Coded visuals

A **coded visual** is a small HTML/CSS/JS project — an animated infographic,
a lower-third, a chart — that VisualKit renders in headless Chrome into
ordinary media (a PNG for a still visual, an MP4 for an animated one), and
that file is then used exactly like any other clip. `CodedVisualClip` is
the reference to the project; `CodedVisualCompiler` is what actually runs
Chrome and produces the file.

```python
clip = vk.CodedVisualClip(id="card", source="assets/stat_card", duration=vk.Time(4))
clip.load_manifest()                          # canvas size + variable schema from the bundle
clip.set_variable("title", "Active users")
clip.set_variable("accent", "#22c55e")        # typed: a bad color raises immediately
timeline.add_clip(clip)
timeline.export_to_video("out.mp4")           # renders, then composites like any media clip
```

## Bundle layout

A coded visual is either a single `.html` file, or a directory bundle:

```
assets/stat_card/
├── index.html        # entrypoint
├── manifest.json      # optional, but recommended for anything reusable
└── logo.svg           # any local images/SVGs/CSS/JS load normally
```

`resolve_entrypoint(source_path)` finds the HTML entrypoint for either
shape; `load_coded_visual(source_path)` loads it plus its manifest.

## The design canvas — author once, place anywhere

A visual is authored against a **fixed design canvas**, declared one of
three ways (in this priority order): explicitly on the clip
(`clip.canvas_size = vk.Size(...)`), in `manifest.json`
(`"canvas_size": {"width": 1920, "height": 1080}`), or in the HTML itself
(`<meta name="canvas-size" content="1920x1080">`). `clip.design_size()`
reports whichever one wins; `clip.canvas_size` itself stays `None` until
you set it explicitly — don't read `clip.canvas_size` expecting a resolved
value, read `design_size()`.

Put your actual content inside a `<div class="visualkit-canvas">`. It is
**always rendered at exactly the design size** and then scaled (aspect
ratio preserved) to fit whatever frame it lands in — the layout never
reflows differently at different output resolutions. A 9:16 (vertical),
1:1, or 16:9 visual is just a different design size; there's no separate
"orientation" concept.

## Variables

Declare typed variables in `manifest.json`:

```json
{
  "variables": {
    "title": {"type": "string", "required": true, "label": "Card Title", "description": "..."},
    "accent": {"type": "color", "default": "#38bdf8", "label": "Accent color", "description": "..."},
    "progress": {"type": "number", "default": 72, "description": "0-100"}
  }
}
```

Types (`VariableType`): `string`, `number`, `boolean`, `color`, `asset`,
`json`. A bad value for the declared type raises `ValueError` immediately
on `set_variable` / `define_variable` — a mistyped color is caught the
moment you set it, not after a slow Chrome render fails or (worse) after
it silently renders wrong.

In the HTML:

- `{{ name }}` — the value, **HTML-escaped**. Use for anything that lands
  in text content or an attribute.
- `{{{ name }}}` — the value, inserted as **raw, trusted HTML**. Only use
  this for values you control; it is not escaped at all.
- `window.__VARIABLES__.name` — the same values, available to script,
  already typed (a `number` variable stays a JS number, not a string).
- Placeholders inside `<style>` are also HTML-escaped, which is safe for a
  validated `color`/`number` variable but **not** safe for an arbitrary
  string variable interpolated into CSS — don't put a `string`-typed
  variable straight into a `<style>` block without thinking about it.

Discovering what a bundle needs, without opening the HTML:

```python
clip.load_manifest()
clip.variables                            # {name: Variable}
clip.get_missing_required_variables()     # [name, ...] required + unset + no default
clip.get_resolved_variables()             # {name: value} — assigned, or default
clip.get_unset_variables()                # {name: Variable} not yet assigned
```

`define_variable(name, type=..., value=None, default=None, label=None,
description=None, required=False)` lets you declare/override a variable
from Python (e.g. to add metadata a manifest didn't have), and
`set_variable(name, value)` assigns a value, inferring the type if the
variable doesn't exist yet.

## Still vs. animated

`render_mode` defaults to `RenderMode.AUTO`: a page with motion becomes a
video, a static one a PNG. Detection uses the manifest's `animated` flag if
you set one; otherwise it renders the page at two different virtual times
and compares the output. You can force it either way with
`render_mode=RenderMode.IMAGE` / `RenderMode.VIDEO` on the clip, or pass
`render_video=True`/`False` to `flatten()` / `export_to_video()` /
`export_to_resolve()` to override for the whole timeline.

## Determinism

Animation is stepped **deterministically**: CSS and Web Animations are
seeked to an exact virtual time rather than played back in real time, and
`Date`, `setTimeout`, `setInterval`, and `requestAnimationFrame` all run on
a virtual clock. This is what makes a render byte-identical on every
machine, and it's why VisualKit can afford to cache renders by content
hash rather than re-running Chrome every time.

**Limits — read before relying on anything time-based inside a visual:**
determinism is only guaranteed for CSS/Web Animations and the JS timing
APIs listed above. Anything that reads a real clock or does real I/O —
`<video>`/`<audio>` elements, WebGL or canvas code driven by
`performance.now()` or a network response, `fetch()` calls — is **not**
guaranteed to be frame-exact. Pre-render that kind of content to a file and
reference it as a normal `MediaClip` instead of trying to make it live
inside a coded visual.

## Rendering directly (without a timeline)

```python
from visualkit.coded_visual.compiler import CodedVisualCompiler

compiler = CodedVisualCompiler()
still = compiler.render_to_image(clip)                    # cheap: one screenshot at design size
video = compiler.render_to_video(clip, fps=30.0)           # needs the `render` extra
frame = compiler.preview_frame(clip, time=1.5)             # one frame at virtual time 1.5s, no cache write to clip
```

`render_to_image` / `render_to_video` also set `clip.media_source` and
`clip.compile_status`, so a `CodedVisualClip` you've compiled once behaves
like a `MediaClip` for anything that just reads `media_source`.

## Caching and invalidation

Renders are **content-addressed**: the cache key covers the HTML, every
variable value, canvas size, aspect ratio, fps, duration, render mode, and
the bytes of every sibling asset the bundle references. Editing any of
those — including a sibling image/CSS/JS file on disk — invalidates the
cache automatically; you don't need to manually bust it. `force=True` on
`compile()` / `render_to_image()` / `render_to_video()` re-renders
regardless. `invalidate_compile()` marks a clip's cached output stale
explicitly (e.g. after you've mutated something the cache key can't see).

## Pre-flight checks

Two checks exist specifically so you can validate a bundle **without**
starting Chrome:

- `clip.lint()` / `compiler.lint(clip)` — pure-Python checks (manifest
  shape, variable types, obviously-missing required values) returning a
  list of `LintIssue(severity, code, message)`.
- `clip.validate_bundle()` / `compiler.validate_bundle(clip)` — confirms
  every local asset the bundle's HTML/CSS actually references resolves to
  a real file next to `index.html`.

Run these before a batch render (especially in an agent pipeline that's
about to spend real wall-clock time in Chrome) to fail fast on a bad bundle
instead of discovering it mid-render.

## Browser discovery, without Chrome installed globally

If Chrome isn't on `PATH` or in a standard location, set
`VISUALKIT_CHROME=/path/to/chrome` (or to `chrome-headless-shell`, which is
preferred when present — smaller and faster to start). `find_chrome()`
returns the resolved path or `None`; `require_chrome()` does the same but
raises `BrowserNotFoundError` with the exact fix. VisualKit auto-adds
`--no-sandbox` when it detects it's running as root or in a container, so
you don't need to pass Chrome flags yourself in CI/Docker.

## Authoring checklist

- [ ] Content lives inside `.visualkit-canvas`, sized to the design canvas.
- [ ] `manifest.json` declares `canvas_size`, `fps`, `duration`, and every
      variable the page uses, with `label`/`description` for each — this
      is what makes the bundle a reusable, agent-discoverable template
      rather than a one-off.
- [ ] Every variable that reaches raw HTML uses `{{{ }}}` deliberately, and
      only for values you trust; everything else uses `{{ }}`.
- [ ] Anything that depends on a real clock, `<video>`/`<audio>`, or
      network I/O is pre-rendered to a file, not live inside the page.
- [ ] `clip.lint()` and `clip.validate_bundle()` pass before you spend a
      Chrome render on it.
