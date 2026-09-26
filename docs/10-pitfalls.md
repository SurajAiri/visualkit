# Pitfalls

Non-obvious current behavior that's easy to assume otherwise. This is a
condensed, present-tense version of the "behavior changes" section in
[`CHANGES.md`](../CHANGES.md) — read that file if you want the history and
regression-test detail behind each one; this page just tells you what's
true today.

- **A `CodedVisualClip`'s rendered output is real media, not HTML.**
  `compile()` produces a PNG (still) or MP4 (animated); `media_source` is
  never an HTML path. Don't write code that expects to open
  `clip.media_source` as HTML.

- **`render_video` defaults to `auto`**, in `flatten()`,
  `export_to_video()`, and `export_to_resolve()`. An animated coded visual
  does *not* silently export as one frozen frame unless you explicitly
  force `render_video=False`.

- **`CodedVisualClip.canvas_size` and `.aspect_ratio` are `None` until you
  set them.** Read `clip.design_size()` / `clip.design_aspect_ratio()` for
  the effective value (explicit → manifest → 1920x1080 default) — reading
  the raw fields directly will often give you `None` even for a bundle
  that clearly has a size, because that size came from the manifest, not
  from the clip.

- **Compound duration is enforced.** A `CompoundClip` whose inner content
  is longer than `duration` gets that content trimmed on flatten, not
  silently allowed to overflow.

- **A broken exposed-parameter mapping only raises *at export/flatten*
  time, not necessarily when you set it.** `set_parameter(name, value)`
  raises immediately only if `name` itself isn't a known exposed
  parameter (or a `clip_id.property` path). If `name` *is* a valid
  exposed parameter but its `target_clip_id`/`target_variable` points at
  a clip or property that doesn't exist (a template-authoring bug, not a
  caller bug), `set_parameter` calls `apply_parameters()` with its
  default `strict=False` and **that failure is silently skipped**. The
  strict version — used internally at export/flatten time — raises
  `TemplateParameterError` there. If you're authoring or validating a
  template (rather than just consuming one), call
  `compound.apply_parameters(strict=True)` yourself to surface a broken
  mapping immediately instead of waiting for an export to fail. A
  protected field (`id`, `clip_type`, `linked_clip_id`,
  `compound_clip_id`, `inner_timeline`, `exposed_parameters`) as a target
  follows the same strict/non-strict rule.

- **`flatten()` never mutates the timeline you call it on.** Exporting
  from a template twice with different parameters in between is safe and
  intended; it does not bake defaults into your original template object.

- **Text size is relative to a 1080p reference frame.** `font_size=48` is
  48px at 1080p and scales with the actual export resolution — it is not
  a fixed pixel size regardless of resolution.

- **`Timeline.add_clip` rejects duplicate clip ids**, including two clips
  with the same id in one batched call, and never creates a track of the
  *other* kind as a side effect (adding a video-only clip no longer leaves
  behind an empty, unwanted audio track).

- **DaVinci Resolve export ignores keyframes, chroma key, masks,
  animation presets, and extended text styling.** It renders each clip's
  plain, static `transform`. This is a current scope boundary, not a bug —
  see the table in [07-exporting.md](07-exporting.md).

- **Resolve position conventions (XMEML / FCPXML) are implemented from the
  format specs and covered by structural tests, but have not been
  confirmed against a live DaVinci Resolve import.** Verify a positioned
  clip in Resolve itself before depending on exact placement in
  production; scale, opacity, and timing are the higher-confidence parts.

- **Time-dependent web content beyond CSS/Web Animations and the standard
  JS timing APIs is not made deterministic** inside a coded visual —
  `<video>`/`<audio>` elements, WebGL/canvas code reading a real clock, and
  network fetches can render differently between machines or runs. Pre-render
  that content and reference it as a normal clip instead.

- **An animated child under a non-identity compound `transform` isn't
  silently composed wrong** — it raises `NotImplementedError` on flatten,
  deliberately, rather than producing an incorrect render. See
  [04-templates-and-compounds.md](04-templates-and-compounds.md).

- **A compound that contains itself (directly or via nesting) is rejected**
  by `add_clip` or reported by `flatten` — it is never infinitely
  recursed into a hang.
