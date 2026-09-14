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
    ├── Represents a self-contained composition made up of multiple clips
    │   arranged on its own internal timeline.
    │
    └── RefinedScriptClip
        └── A specialized CompoundClip containing the refined main-track
            composition; restricted to root/track-0.
```
Clip: timing(source_start_ts, duration), linked_clip_id, asset_reference, key_frame, speed, animation(in, overall, out), start
    - AudioClip: volume, audio_effects
    - VisualClip: transform(zoom, rotation, position, scale, opacity), chroma_key, masking
        - TextClip: text_value, text_style(font, size, color, weight, etc.), text_animations
        - MediaClip: [video, image, gif, etc]: transition
        - CodedVisualClip(MediaClip): code_ref on asset_ref  [rendering step, code -> canvas — a MediaClip subclass]
    - CompoundClip: [a combination of multiple clips, a sort of having secondary timeline for these clips] [templates with changeable parameters for input values, all structured in a single place for ease of use and reusability.]
    - RefinedScriptClip(CompoundClip): [refined main track] (we have to have a special clip for this.) [it's a compound clip that renders the refined main track to compound clip of refined main track timeline. and this can only be on root/track-0 ]

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