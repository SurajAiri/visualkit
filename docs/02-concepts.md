# Core concepts

Everything else in this framework is built from a small number of ideas.
Read this page fully before writing non-trivial VisualKit code — most
surprising behavior traces back to one of the rules here.

## Timeline, Track, Clip

- A **`Timeline`** owns two parallel lists: `video_tracks: list[VideoTrack]`
  and `audio_tracks: list[AudioTrack]`. `timeline.all_tracks()` returns video
  tracks first (in composite order — later index draws on top), then audio
  tracks.
- A **`Track`** holds an ordered, non-overlapping-by-default list of clips
  of one kind (`VideoTrack` holds `VisualContent`, `AudioTrack` holds
  `AudioContent`).
- A **`Clip`** is one of `MediaClip`, `TextClip`, `AudioClip`,
  `CodedVisualClip`, or `CompoundClip`. All share `BaseClip`: `id`,
  `timeline_start`, `duration`, `speed`. Visual clips (`MediaClip`,
  `TextClip`, `CodedVisualClip`) additionally carry a `Transform` (position,
  size, rotation, scale, zoom, opacity) plus optional `keyframes`,
  `chroma_key`, `mask`, and `animation` — see
  [03-clips-reference.md](03-clips-reference.md).

### `Timeline.add_clip` routes automatically

```python
timeline.add_clip(clip, track_index=0, mode=vk.InsertMode.OVERLAP)
```

- `AudioClip` → the audio track at `track_index`; anything else → the video
  track at `track_index`. You don't choose which list — the clip type
  decides.
- Tracks are provisioned **up to and including** `track_index` if they
  don't exist yet, so `track_index=5` on an empty timeline always lands on
  track 5, not "the next new track."
- Adding a `CompoundClip` **auto-creates its audio companion**
  (`CompoundAudioClip`) on an audio track for you — see
  [04-templates-and-compounds.md](04-templates-and-compounds.md).
- `Timeline.add_clip` also accepts a **batch of several clips in one call**,
  and that batch is atomic (see "Atomicity" below).
- `mode=InsertMode.RIPPLE` shifts later clips right to make room. If the
  insertion point falls *inside* an existing clip's span, ripple can't
  resolve that by shifting alone (it would require splitting the existing
  clip, which `add_clip` does not do) — it raises
  `InvalidTrackOperationError` instead of silently producing an overlapping
  timeline.

## `Time`

`Time` is the currency of every timestamp and duration in the model. It
wraps an **exact `Fraction` of seconds** — never a float internally — so
that repeated cuts, splits, and NTSC frame-rate math don't drift.

```python
vk.Time.from_seconds(1.5)
vk.Time.from_frames(45, fps=30)
vk.Time.from_timecode("00:00:01:15", fps=29.97)   # exact NTSC drop-frame
```

- `.seconds()` gives you a float — **lossy, for display/interop only**.
  Don't round-trip through it for further computation.
- `.value()` gives you the exact `Fraction`.
- NTSC rates (29.97, 23.976, 59.94) are recognized and treated as their
  exact `1000/1001` rational rate, whether you pass them as a float or a
  `Fraction`. Real SMPTE drop-frame timecode is supported.
- `Time` rejects `bool`, `inf`, `nan`, and anything above `MAX_TIME_SECONDS`
  (10^9 seconds) with `InvalidTimeError` rather than silently producing a
  broken timeline.

> **Agent note:** always construct times via `Time.from_seconds(...)` /
> `Time.from_frames(...)`, not by doing float arithmetic yourself and hoping
> it coerces. Pydantic validation accepts plain numbers in most places
> (`Time` has a flexible constructor), but the exact-fraction guarantees
> only hold if you let `Time` do the conversion.

## Validation is strict, not permissive

Every model in `visualkit.models` is a Pydantic model configured with:

- **`extra="forbid"`** — an unknown/misspelled keyword argument raises
  `ValidationError` immediately at construction. It does not get silently
  dropped.
- **`validate_assignment=True`** — `clip.speed = -1` re-validates on
  assignment, it doesn't bypass field constraints just because the object
  already exists.

This means "I passed a slightly-wrong shape and it silently produced an
empty/wrong timeline" is a class of bug this library specifically closes
off. If something is wrong, you get an exception, not a quiet no-op.

## `flatten()`: the one thing that touches everything

```python
flat = timeline.flatten()
```

`flatten()` (used internally by both exporters, and callable directly) does
three things, in order:

1. **Resolve variables** — recursively apply `CompoundClip.parameters`
   down through all compound clips.
2. **Compile coded visuals** — render every `CodedVisualClip` (including
   ones nested inside compounds) to a real PNG/MP4 via
   `CodedVisualCompiler`.
3. **Flatten compound clips** — expand every `CompoundClip` into plain
   clips with absolute timeline coordinates, composing the compound's own
   `transform` onto its children and trimming inner content to the
   compound's `duration`.

The result is a `Timeline` made only of `MediaClip` / `TextClip` /
`AudioClip` — no more `CompoundClip` or `CodedVisualClip` — ready for either
exporter.

**`flatten()` never mutates the timeline you call it on.** Templates you
built (with default parameter values baked into the model) stay exactly as
you built them; exporting from the same template twice with different
`set_parameter(...)` calls in between is the intended workflow, not a
footgun.

`export_to_video()` and `export_to_resolve()` both call `flatten()`
internally, so you don't normally call it yourself unless you want to
inspect the resolved timeline (e.g. to check `flattened.duration()`, or to
serialize it) before choosing an exporter.

## Atomicity of timeline edits

`Timeline.split_clip`, `Timeline.move_clip_track`, and
`Timeline.add_clip` (including a batch of several clips in one call) are
**atomic**: validation happens in a pass separate from mutation, so a
rejected edit — including one that fails partway through a batch, or
mid-ripple — leaves the timeline **exactly as it was before the call**.
You never need to catch an exception and then manually figure out what
partial state was left behind.

## Errors

Every library-raised error derives from `visualkit.VisualKitError`. See
[08-errors-and-validation.md](08-errors-and-validation.md) for the full
hierarchy and what each one means for your control flow.

## Serialization

Every model is a Pydantic model, so the whole timeline round-trips through
JSON for free:

```python
json_str = timeline.model_dump_json(indent=2)
restored = vk.Timeline.model_validate_json(json_str)
```

This is the natural way to persist a project, hand a timeline across a
process boundary, or let an agent inspect/diff a timeline as structured
data instead of re-deriving it from your own code.
