# Templates & compound clips

`CompoundClip` is how you package a multi-track scene (title + subtitle +
sound effect, say) into one reusable unit with a small, documented,
typed set of knobs — the mechanism this whole framework leans on for
"reusable video templates" and for letting an agent fill in a scene
without touching its internal structure.

## Building a template

```python
inner = vk.Timeline()

inner.add_clip(
    vk.TextClip(
        id="speaker_name", text="Default Speaker",
        duration=vk.Time.from_seconds(6),
        style=vk.TextStyle(font_size=48, color="#ffffff"),
    ),
    track_index=0,
)
inner.add_clip(
    vk.TextClip(
        id="speaker_role", text="Default Title",
        timeline_start=vk.Time.from_seconds(0.5), duration=vk.Time.from_seconds(5.5),
        style=vk.TextStyle(font_size=28, color="#94a3b8"),
    ),
    track_index=1,
)
inner.add_clip(
    vk.AudioClip(id="sfx_whoosh", source="assets/whoosh.wav", duration=vk.Time.from_seconds(1.5)),
    track_index=0,
)

compound = vk.CompoundClip(
    id="tpl_lower_third",
    duration=vk.Time.from_seconds(6),
    inner_timeline=inner,
)

compound.expose_parameter(
    name="speaker_name", target_clip_id="speaker_name", target_variable="text",
    label="Speaker Name", description="Name of the person being interviewed",
    required=True,
)
compound.expose_parameter(
    name="speaker_role", target_clip_id="speaker_role", target_variable="text",
    label="Speaker Role", description="Professional title or company affiliation",
    default="Software Engineer",
)
```

`expose_parameter(name, target_clip_id, target_variable, *, label=None,
description=None, default=None, required=False)` registers one mapping:
top-level parameter `name` → a specific inner clip's field or variable.
`label`/`description` exist specifically so a UI form builder or an AI
agent can present the parameter to a user without inspecting the inner
timeline at all.

### `target_variable` can reach nested fields

`target_variable` isn't limited to a clip's own top-level fields. A dotted
path (`"style.color"`, `"transform.opacity"`) reaches one or more levels
into a clip's nested Pydantic models:

```python
compound.expose_parameter(
    name="accent_color", target_clip_id="speaker_name", target_variable="style.color",
)
```

A handful of fields are **protected** and can never be a parameter target,
at any position in the dotted path: `id`, `clip_type`, `linked_clip_id`,
`compound_clip_id`, `inner_timeline`, `exposed_parameters`. Targeting one
of these — or any other broken mapping (missing clip, missing property) —
is a *template-authoring* error and is checked with a `strict` flag: it
always raises `TemplateParameterError` at export/flatten time, but
`set_parameter(...)` itself only raises for an unknown parameter *name*
(see below) — a valid name with a broken target is silently skipped unless
you call `apply_parameters(strict=True)` yourself. See
[10-pitfalls.md](10-pitfalls.md) for the exact rule.

## Consuming a template

```python
lower_third.set_parameter("speaker_name", "Dr. Jane Doe")
lower_third.set_parameter("speaker_role", "Principal AI Researcher")

root_timeline = vk.Timeline()
lower_third.timeline_start = vk.Time.from_seconds(3)
root_timeline.add_clip(lower_third)   # auto-creates the audio companion
```

`set_parameter(name, value)` sets the value **and immediately applies it**
to the target clip — you don't need a separate "commit" step, and reading
`lower_third.parameters` afterward reflects what's live. It raises
`TemplateParameterError` immediately if `name` isn't a registered exposed
parameter (or a `clip_id.property` path) — but *not* if `name` is valid
and its mapping is simply broken (see the callout above).

`apply_parameters(*, strict=False)` re-propagates all current parameters to
the inner timeline (mostly useful after directly mutating
`compound.parameters`, which `set_parameter` normally does for you, or to
validate a template you just authored). With `strict=True` — what
`export_to_video()`/`export_to_resolve()` use internally — a parameter
that fails to apply (missing target clip, missing property, protected
field) raises `TemplateParameterError` instead of being silently skipped.

## Discovering what a template needs (agent-facing)

This is the pattern for an agent that receives a `CompoundClip` it didn't
build and needs to know what to fill in, without reading the inner
timeline's Python:

```python
for p in compound.exposed_parameters:
    print(p.name, p.label, p.description, p.required, p.default)

print(compound.get_set_parameters())            # {name: value, ...} currently set
print(compound.get_unset_parameters())          # [ExposedParameter, ...] not yet set
print(compound.get_missing_required_parameters())  # [name, ...] required + no value + no default
print(compound.get_child_variables())           # {clip_id: {var_name: Variable}} — every inner CodedVisualClip's own variables, for templates that also contain coded visuals
```

`ExposedParameter` and `Variable` are both plain Pydantic models — the
whole set above serializes to JSON directly (`p.model_dump()`), so an
agent can hand a template's "what do I need to fill in" schema to an LLM or
a UI form without any bespoke serialization code.

## The audio companion

Adding a `CompoundClip` through `Timeline.add_clip` automatically creates
a linked `CompoundAudioClip` on an audio track (`create_audio_companion()`
is what does this under the hood, but you normally never call it
yourself). This is the mechanism that lets a compound's own inner audio
tracks get mixed correctly when flattened, and why a `CompoundClip`
"reserves a seat" on the audio lane the moment you add it — even if the
inner timeline turns out to have no audio at all.

`Timeline.remove_clip` on a compound removes both the compound and its
companion together. `Timeline.sync_companions()` re-aligns every
companion's start/duration/speed with its compound after edits that might
have moved one but not the other.

## `speed` on a compound

Setting `compound.speed = 2.0` compresses the *entire* inner timeline
proportionally when flattened: 4 seconds of inner content at 2x now
occupies 2 seconds of outer-timeline span, and every leaf clip inside is
retimed to match (both its position and its own effective playback speed).
This composes across nesting: a 2x compound nested inside a 3x compound
flattens to 6x. `speed=1.0` (the default) is a pure no-op.

## Flattening

`CompoundClip.duration` is enforced: inner content is trimmed to the
compound's own `duration` when flattened, even if the inner timeline is
longer. The compound's own `transform` is composed onto each child's
transform (`compose_transforms` in `visualkit.engine.pipeline`) — but see
the callout in [03-clips-reference.md](03-clips-reference.md): composing
an *animated* child (keyframes or an `animation` preset) with a
non-identity compound transform is refused with a clear
`NotImplementedError` rather than silently rendered wrong. Give the child
its final position directly, or keep the compound's own transform at
identity, if the child is animated.

`flatten()` never mutates the timeline you call it on — see
[02-concepts.md](02-concepts.md) — so a template's defaults are never
baked in by exporting from it.
