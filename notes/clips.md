# Clips
**Various editing option based on the clip type**

```md
Clip
├── AudioClip
│   └── Audio content placed on an audio track.
│
├── VisualClip
│   ├── TextClip
│   │   └── Text content rendered as a visual clip.
│   │
│   └── MediaClip
│       ├── Represents visual media such as video, images, GIFs, etc.
│       │
│       └── CodedVisualClip
│           └── References code that is executed during rendering to
│               generate a media asset; the resulting output then behaves
│               as a normal MediaClip.
│
└── CompoundClip
    └── Represents a self-contained composition made up of multiple clips
        arranged on its own internal timeline. & has both a audio visual track.

```
Clip: timing(source_start_ts, duration), linked_clip_id, asset_reference, key_frame, speed, animation(in, overall, out), start
    - AudioClip: volume, audio_effects
    - VisualClip: transform(zoom, rotation, position, scale, opacity), chroma_key, masking
        - TextClip: text_value, text_style(font, size, color, weight, etc.), text_animations
        - MediaClip: [video, image, gif, etc]: transition
        - CodedVisualClip(MediaClip): code_ref on asset_ref  [rendering step, code -> canvas — a MediaClip subclass]
    - CompoundClip: [a combination of multiple clips, a sort of having secondary timeline for these clips] [templates with changeable parameters for input values, all structured in a single place for ease of use and reusability.]
    - RefinedScriptClip(CompoundClip): (doesn't exist, ignore this) [refined main track] (we have to have a special clip for this.) [it's a compound clip that renders the refined main track to compound clip of refined main track timeline. and this can only be on root/track-0 ]

Track:
    items: [Clip | Transition]     
    Transition: type, duration # requires clip_before/clip_after continuous & touching 


Variables:
1. Identity/Reference (fixed, set at creation, not animated, not stackable): one value per clip, editing this changes WHAT the clip is, not its state over time.
    -> asset_reference, text_value, timing(source_start_ts, duration, track_id), linked_clip_id, speed
2. Properties (EACH independently keyframable): keyframe system operates HERE, on these fields, generically.
    -> transform: zoom, rotation, position, scale, opacity
    -> text_style: font, size, color, weight
    -> volume
3. Add-ons
    -> audio_effects, chroma_key, masking, transition, text_animations, animation(in, overall, out)


Skip for now: keyframe system, add-ons, compound clip, refined script clip, transition
Phase 2: chroma key, masking, transition, text_animations, animation(in, overall, out) 
---

## Shipped (FFmpeg exporter + previews only; Resolve export ignores all of this)

- **Keyframe system**: `VisualClip.keyframes: dict[str, PropertyCurve]` -- position.x/y, scale,
  rotation, zoom, opacity, plus mask.x/y/width/height/feather when `mask` is set. Clip-local
  time, unaffected by `speed`. See `visualkit.models.keyframes`.
- **chroma_key / masking**: `VisualClip.chroma_key: ChromaKey | None`,
  `VisualClip.mask: Mask | None` (rect/ellipse, feather, invert; geometry is keyframeable). See
  `visualkit.models.effects`.
- **animation(in, out)**: `VisualClip.animation: ClipAnimation | None` -- `fade`,
  `slide_up/down/left/right`, `pop`, `wipe` presets, compiled to the same keyframes/mask above
  (no second render path). Applies to `TextClip` too. See `visualkit.models.animation`. No
  "overall" animation phase was requested by the handoff and none was built.
- **text_animations**: covered by `animation` above (a `TextClip` is a `VisualClip`); there is
  no separate per-character/typewriter system (measured to fail with real ffmpeg -- see the
  handoff's §2.9 -- and out of scope).
- **text_style growth**: outline (`stroke_width`/`stroke_color`), drop shadow, `letter_spacing`,
  `line_height`, gradient fill (`TextGradient`). See `visualkit.models.clips.text.TextStyle`.
- **Video alpha**: an animated `CodedVisualClip` renders to lossless FFV1 `render.mkv`
  (`yuva420p`, or `yuva444p` for odd dimensions) instead of a flat H.264 `render.mp4`, so
  transparency survives into the exported video. The Resolve export still uses the flat
  `render.mp4`.

## Not shipped

- **transition**: still unbuilt, as before.
- **Compound-level keyframes/chroma_key/masking/animation**: `CompoundClip` does not carry
  these fields itself (only `transform`, unchanged). A `VisualClip` *inside* a compound keeps
  its own keyframes/chroma_key/mask/animation when the compound is flattened, unless the
  compound's own `transform` is non-identity and the child is animated (keyframes or
  `animation`) -- composing an animated curve with a parent transform is refused with a clear
  `NotImplementedError` rather than silently rendered wrong (the handoff's documented escape
  hatch for the "compound bake" phase).
