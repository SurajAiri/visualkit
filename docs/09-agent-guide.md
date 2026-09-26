# Agent guide

This page is for an LLM (or an LLM-driven coding agent) generating
VisualKit code, whether that's a one-off script or a long-running process
that assembles videos from instructions at runtime. It assumes you've read
[02-concepts.md](02-concepts.md); it doesn't repeat the model, it tells you
how to move through it without guessing.

## Decision tree: what am I building?

1. **Do I have a real media file (video/image) already?** → `MediaClip`.
2. **Is it text I want rendered as a clip, with its own styling/animation?**
   → `TextClip`. (It's a full `VisualClip` — transform, keyframes,
   animation presets, everything in
   [06-keyframes-and-effects.md](06-keyframes-and-effects.md) applies.)
3. **Is it audio only?** → `AudioClip`.
4. **Do I need to generate the visual itself** (an infographic, a chart, a
   branded card, anything drawn rather than filmed)? → `CodedVisualClip`.
   Read [05-coded-visuals.md](05-coded-visuals.md) fully before writing the
   HTML — the design-canvas and variable-escaping rules are not optional
   details.
5. **Am I building something reusable** — a scene with a few things that
   change per use (a name, a color, a headline) and a lot that stays fixed?
   → build it once as a `CompoundClip` with `expose_parameter(...)`, then
   drive it with `set_parameter(...)` per instance. See
   [04-templates-and-compounds.md](04-templates-and-compounds.md). Don't
   regenerate the whole inner structure from scratch every time you need a
   slightly different instance of the same scene — that's exactly what
   `CompoundClip` exists to avoid.
6. **Do I need this to land in DaVinci Resolve** rather than as a
   standalone file? Check [07-exporting.md](07-exporting.md)'s feature
   table *before* reaching for keyframes/chroma key/masks/animation —
   Resolve export silently drops all of them and renders the plain static
   `transform` instead. If you need those effects and the target is
   Resolve, they aren't representable in that export path today; don't
   generate code that assumes otherwise.

## Discover before you assume

If you're operating on a `CompoundClip` or `CodedVisualClip` you didn't
just build yourself in this same script (loaded from a file, fetched from
a library, handed to you by a user), **read its schema, don't guess its
fields**:

```python
# A compound template
for p in compound.exposed_parameters:
    ...  # p.name, p.label, p.description, p.required, p.default

# A coded visual bundle
clip.load_manifest()
clip.variables                          # {name: Variable}
clip.get_missing_required_variables()
```

Both `ExposedParameter` and `Variable` are Pydantic models with
`label`/`description`/`required`/`default` — that metadata exists
specifically so you (or the human you're assisting) never have to open the
inner timeline's Python or the bundle's HTML to know what a template needs.

## Recipes

**Fill a template and place it on a timeline:**

```python
lower_third.set_parameter("speaker_name", "Dr. Jane Doe")
lower_third.timeline_start = vk.Time.from_seconds(3)
root_timeline.add_clip(lower_third)   # audio companion is automatic
```

**Generate several instances of the same template cheaply:** build the
`CompoundClip` once, then for each instance, copy it (or rebuild the light
wrapper — the inner timeline is the expensive part to construct, not the
`set_parameter` calls) and vary only the exposed parameters. Don't
re-author the inner timeline per instance.

**Check what a batch of edits will do before doing it:** `Timeline.add_clip`
accepts several clips in one call and the whole batch is atomic — if you're
generating N clips programmatically, prefer one batched `add_clip` call
over N separate calls so a bad clip in the middle can't leave the timeline
half-edited.

**Preview before a full export:** `clip.preview_image()` /
`clip.preview_frame(time)` (coded visuals), `MediaClip.preview_image()`,
`TextClip.preview_image()` all render a single frame to a PNG without
touching the rest of the timeline or running a full FFmpeg export — use
these for a fast feedback loop while iterating, then export once you're
confident.

**Serialize/inspect a timeline as data:** `timeline.model_dump_json()` /
`Timeline.model_validate_json(...)`. If you're reasoning about a timeline
programmatically (checking for overlaps, summarizing what's on it, diffing
two versions), work with the parsed model, not string-matched Python
source.

## Pre-flight checklist before you run an export

- [ ] Every clip `id` is unique (duplicates raise at `add_clip` time, but
      check your own generation logic rather than relying on the
      exception as the first signal).
- [ ] For a coded visual: `clip.lint()` and `clip.validate_bundle()` come
      back clean *before* you spend a Chrome render on it.
- [ ] For a template: `get_missing_required_parameters()` /
      `get_missing_required_variables()` are empty.
- [ ] You've picked the exporter that actually supports the effects you
      used (see the table in [07-exporting.md](07-exporting.md)).
- [ ] If the export can fail (FFmpeg not installed, Chrome not found,
      source file missing), you're catching the specific
      `VisualKitError` subclass that tells you what to fix — see
      [08-errors-and-validation.md](08-errors-and-validation.md) — not a
      bare `except Exception`.

## Footguns specific to generated code

- **Don't hand-roll `Time` from a float and skip the constructor.** Use
  `Time.from_seconds(...)` / `Time.from_frames(...)` so the exact-fraction
  guarantees actually hold.
- **Don't assume an unknown keyword argument gets ignored.** Every model
  is `extra="forbid"` — a field name you invented because it seemed
  plausible will raise `ValidationError`, not silently vanish. Check
  [03-clips-reference.md](03-clips-reference.md) for the real field name.
- **Don't put an arbitrary (untyped) string variable straight into a
  coded visual's `<style>` block** via `{{ }}` — it's escaped for HTML but
  that doesn't make it safe CSS. Validated `color`/`number` variables are
  fine; free-form `string` variables aren't.
- **Don't assume Resolve export preserves keyframes/effects.** It doesn't,
  today. Re-read the table in [07-exporting.md](07-exporting.md) if you're
  about to generate a `keyframes=`/`chroma_key=`/`mask=`/`animation=`
  argument on a clip headed for `export_to_resolve()`.
- **Don't compose an animated child under a non-identity compound
  transform.** It raises `NotImplementedError` on flatten by design (see
  [04-templates-and-compounds.md](04-templates-and-compounds.md)) rather
  than silently rendering wrong — treat that error as "give the child its
  final position directly," not as a bug to retry around.
