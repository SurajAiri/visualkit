# Errors & validation

## Exception hierarchy

Every error the library itself raises derives from `visualkit.VisualKitError`:

```
VisualKitError
├── ClipNotFoundError               # a requested clip id doesn't exist in the timeline
├── TrackNotFoundError              # a requested track id doesn't exist in the timeline
├── InvalidTimeError                # a Time construction/operation was invalid (bool, inf, nan, > 1e9s)
├── InvalidSplitError               # a split was requested at a point that isn't valid for the clip
├── InvalidTrackOperationError      # e.g. a ripple-insert whose target point falls inside an
│                                   #   existing clip's span (see 02-concepts.md)
├── TimelineValidationError         # structural problem that would corrupt a flatten (validate())
├── TemplateParameterError          # an exposed/dotted parameter targets something that doesn't exist,
│                                   #   or a protected field (id, clip_type, ...)
├── MissingSourceError              # a clip's source file can't be found at export time
├── CodedVisualError
│   ├── CodedVisualCompileError     # a coded visual couldn't be rendered
│   │   └── BrowserNotFoundError    # no usable Chrome/Chromium was found
└── ExportError                     # ffmpeg failed; carries .returncode, .stderr, .command
```

Also raised, but *not* `VisualKitError` subclasses (they come from
Pydantic itself, and are worth catching separately if you're writing a
robust caller):

- `pydantic.ValidationError` — any model constructed or assigned with the
  wrong shape (unknown field, wrong type, out-of-range value). This is the
  common case for "an agent generated a slightly wrong clip" — every
  model uses `extra="forbid"` (unknown fields raise immediately) and
  `validate_assignment=True` (so does `clip.speed = -1` after the fact).
- `ValueError` — e.g. an unknown property name in `keyframes`, a bad color
  string for a `color`-typed variable, `Transform.scale <= 0`.

## What's validated, and when

VisualKit deliberately validates **early and loudly** rather than
"eventually, at export":

- Constructing a clip with a bad field value, or assigning one afterward,
  raises immediately — not when you later try to render it.
- Setting a `CodedVisualClip` variable to a value of the wrong type raises
  immediately (`set_variable("accent", "not; a } color")` raises before
  any Chrome process is ever started).
- `Timeline.validate_tracks()` and `TimelinePipeline.validate(timeline)`
  catch structural problems (overlaps, dangling references) before a
  `flatten()`/export is attempted, so a bad timeline fails fast with a
  clear message rather than partway through an expensive render.
- What is *not* checked until export time: whether a clip's `source` file
  actually exists on disk (`MissingSourceError`), and whether ffmpeg/Chrome
  themselves succeed.

## Atomic edits

`Timeline.split_clip`, `Timeline.move_clip_track`, and `Timeline.add_clip`
(including a batch of several clips passed in one call) validate in a pass
separate from mutation. A rejected edit — including one that fails on the
second clip of a batch, or mid-ripple — leaves the timeline **exactly as
it was before the call**. You do not need to snapshot state yourself before
attempting a risky edit, and a caught exception never implies "go inspect
what partially happened."

## Practical guidance for a caller (especially a code-generating agent)

- Prefer constructing valid objects over catching `ValidationError` as
  control flow — the strict validation exists so mistakes surface at the
  line that made them, with a message naming the exact field.
- Catch `TemplateParameterError` specifically when applying parameters to
  a `CompoundClip` you didn't author yourself (e.g. a template fetched from
  a library) — it's the one place "does this template actually have the
  field I think it has" is a runtime question rather than a typo you'd
  catch by reading your own code.
- Catch `ExportError` around `export_to_video()` and read `.stderr` — it's
  FFmpeg's own diagnostic and is almost always more useful than the
  Python-side message.
- Catch `BrowserNotFoundError` specifically (rather than the broader
  `CodedVisualCompileError`) if you want to give a user/agent a distinct
  "set `VISUALKIT_CHROME`" remediation path versus a generic render
  failure.
