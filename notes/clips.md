# Clips
**Various editing option based on the clip type**

Clip: timing(source_start_ts, duration, track_id), linked_clip_id, asset_reference, key_frame, speed, animation(in, overall, out)
    - AudioClip: volume, audio_effects
    - VisualClip: transform(zoom, rotation, position, scale, opacity), chroma_key, masking
        - TextClip: text_value, text_style(font, size, color, weight, etc.), text_animations
        - MediaClip: [video, image, gif, etc]: transition
        - CodedVisualClip(MediaClip): code_ref on asset_ref  [rendering step, code -> canvas — a MediaClip subclass]
    - CompoundClip: [a combination of multiple clips, a sort of having secondary timeline for these clips] [templates with changeable parameters for input values, all structured in a single place for ease of use and reusability.]
    - RefinedScriptClip(CompoundClip): [refined main track] (we have to have a special clip for this.) [it's a compound clip that renders the refined main track to compound clip of refined main track timeline. and this can only be on root/track-0 ]

Track:
    items: [Clip | Gap | Transition]     # order is the source of truth, position is derived
    Gap: duration
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


Phase 2: chroma key, masking, transition, text_animations, animation(in, overall, out) 