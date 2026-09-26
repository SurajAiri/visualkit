# Keyframes & effects

> **Scope:** everything on this page is honored by `FFmpegVideoExporter`
> (and the single-clip preview helpers) only. **`DaVinciResolveExporter`
> ignores all of it** — keyframes, `chroma_key`, `mask`, and `animation` —
> and renders each clip's plain, static `transform` instead. If your target
> is a Resolve project, don't reach for these; if you need the effect
> there too, it isn't built yet (see [11-roadmap.md](11-roadmap.md)).

## Keyframes

`VisualClip.keyframes: dict[str, PropertyCurve]` drives any of a fixed set
of properties over clip-local time:

```python
subject.keyframes = {
    "position.x": vk.PropertyCurve.from_points([(0, -300), (2, 300), (4, -300)]),
    "mask.width": vk.PropertyCurve.from_points(
        [(0, 0.2, vk.Easing.EASE_IN_OUT), (2, 0.4), (4, 0.2, vk.Easing.EASE_IN_OUT)]
    ),
}
```

Keyable properties (`KEYFRAMEABLE_PROPERTIES`), each with its own valid
range: `position.x`, `position.y` (unbounded), `scale` (>0, ≤100), `rotation`
(±3600°), `zoom` (>0, ≤100), `opacity` (0–100), and — only meaningful when
`mask` is also set — `mask.x`, `mask.y`, `mask.width`, `mask.height`,
`mask.feather` (all 0–1, normalized to the clip frame). Keying anything
else raises `ValueError` with the full list of allowed names.

Semantics worth internalizing:

- Keyframe **times are clip-local**: `Time(1)` means one second after the
  clip's own `timeline_start`, and keyframes are **not** affected by the
  clip's `speed` — `speed` retimes the *source*, keyframes describe the
  *composited transform* independently of it.
- Before the first keyframe the curve holds the first value; after the
  last it holds the last value (no extrapolation).
- A keyframe's `easing` shapes the segment that *starts* at that keyframe
  (`Easing.LINEAR`, `HOLD` — stay then jump — `EASE_IN`, `EASE_OUT`,
  `EASE_IN_OUT`). Easings never overshoot, so a curve always stays within
  the range of its own keyframe values.
- `PropertyCurve.value_at(t)` (pure Python) and `.to_expr(...)` (an ffmpeg
  filter expression) are two independent evaluators of the same curve and
  are tested against each other — you can trust `value_at` for a preview
  or a test assertion and get the same answer the actual export will
  produce.
- Splitting or trimming a clip mid-segment doesn't restart the easing from
  scratch (which would visibly change the motion's shape) — each half
  keeps an accurate `Keyframe.ease_window` recording which part of the
  original easing it still covers.

`VisualClip.transform_at(time)` resolves every keyed property (plus any
`animation`-compiled curves) to one static `Transform` at a given
clip-local time — handy for a spot-check without exporting anything.

## Chroma key

```python
subject.chroma_key = vk.ChromaKey(color="#00B140", similarity=0.15, despill=True)
```

`ChromaKey(color, similarity, blend, despill, despill_type="green"|"blue",
method="chromakey"|"colorkey")`. `ffmpeg_color()` gives the key color in
ffmpeg's own `0xRRGGBB` spelling.

## Masks

```python
subject.mask = vk.Mask(shape="ellipse", width=0.35, height=0.5, feather=0.08)
```

`Mask(shape="rect"|"ellipse", x, y, width, height, feather, invert)` — a
rectangle or feathered ellipse, normalized to the clip's own frame. Mask
geometry is keyframeable (see `mask.*` properties above).
`VisualClip.mask_at(time)` resolves any keyed mask geometry to a static
`Mask` at a given time; `effective_mask()` also accounts for an
`animation`'s unopposed `wipe` preset, which implies a full-frame rect mask
even if you never set one explicitly.

## Animation presets — sugar over keyframes

```python
title.animation = vk.ClipAnimation(
    in_preset="fade", out_preset="pop", in_duration=0.6, out_duration=0.6,
)
```

`ClipAnimation(in_preset, out_preset, in_duration, out_duration, easing,
slide_distance, pop_from, wipe_feather)`. Presets (`AnimationPreset`):
`fade`, `slide_up`, `slide_down`, `slide_left`, `slide_right`, `pop`,
`wipe`. These compile to the *same* keyframes/mask machinery above —
there's no separate rendering path — via
`compile_animation(animation, duration, transform, existing)`, and only
fill in a property that isn't already explicitly keyed
(`VisualClip.effective_keyframes()` is `keyframes` plus whatever
`animation` contributes for properties you haven't keyed yourself).

Because `TextClip` **is** a `VisualClip`, every one of these applies to
text identically — the caption example below wipes on exactly like a video
clip would.

There is intentionally no separate per-character/typewriter text animation
system; see [11-roadmap.md](11-roadmap.md) for why.

## Putting it together

```python
subject = vk.MediaClip(
    id="subject", source=str(screen_path), duration=duration,
    transform=vk.Transform(size=vk.Size(width=480, height=270)),
    chroma_key=vk.ChromaKey(color="#00B140", similarity=0.15, despill=True),
    mask=vk.Mask(shape="ellipse", width=0.35, height=0.5, feather=0.08),
    keyframes={
        "position.x": vk.PropertyCurve.from_points([(0, -300), (2, 300), (4, -300)]),
    },
)

caption = vk.TextClip(
    id="caption", text="keyframes + chroma key + masks + text animation",
    timeline_start=vk.Time.from_seconds(0.5), duration=vk.Time.from_seconds(3),
    style=vk.TextStyle(font_size=40, color="#e2e8f0", letter_spacing=2, line_height=1.3),
    animation=vk.ClipAnimation(in_preset="wipe", in_duration=0.5),
)
```

See `examples/05_keyframes_and_effects.py` for the full runnable version,
including the checkerboard/green-screen fixtures it generates so it runs
without any real footage.
