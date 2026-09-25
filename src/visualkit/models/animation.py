"""Animation presets: `fade`, `slide_*`, `pop`, `wipe` as sugar over keyframes.

A `ClipAnimation` is declarative ("fade in over 0.5s"), not a second render path: it compiles
to the same `PropertyCurve`/`Mask` objects a hand-authored keyframe would use, so
`_render_plan.py` never needs to know a preset was involved. It is recompiled from `duration`
on every read rather than baked into `VisualClip.keyframes` once, so it always matches the
clip's *current* start and end -- important because `Track.split_clip`/`trim_in`/`trim_out`
change `duration` after the clip (and its animation) already exists.

Because the "in" and "out" halves are compiled independently against the clip's current
`timeline_start`/`duration`, they automatically follow `trim_in`/`trim_out`: relocating the
head or tail still leaves exactly one real start and one real end, so "fade in over the first
0.5s" or "fade out over the last 0.5s" keeps meaning the same thing at the (new) edge.

`split_clip` is different: it introduces a brand-new cut in the *middle* of the clip that has
nothing to do with either original edge. Recompiling both halves from their own duration would
otherwise replay the fade-in at the cut (for the second half) and the fade-out at the cut (for
the first half) -- exactly where nothing should happen. `Track.split_clip` therefore drops the
now-inapplicable preset from each half (see `visualkit.models.clips.visual._trimmed_animation`):
the first half keeps `in_preset` but not `out_preset`, the second keeps `out_preset` but not
`in_preset`.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.time import Time

from .effects import Mask
from .keyframes import Easing, Keyframe, PropertyCurve

if TYPE_CHECKING:
    from .clips.visual import Transform


class AnimationPreset(str, Enum):
    FADE = "fade"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    POP = "pop"
    WIPE = "wipe"


#: Properties each preset drives. `wipe` animates a mask, not a `Transform` field.
_PRESET_PROPERTY: dict[AnimationPreset, str] = {
    AnimationPreset.FADE: "opacity",
    AnimationPreset.SLIDE_UP: "position.y",
    AnimationPreset.SLIDE_DOWN: "position.y",
    AnimationPreset.SLIDE_LEFT: "position.x",
    AnimationPreset.SLIDE_RIGHT: "position.x",
    AnimationPreset.POP: "scale",
    AnimationPreset.WIPE: "mask.width",
}


class ClipAnimation(VisualKitModel):
    """In/out motion presets, compiled to keyframes by `VisualClip.effective_keyframes()`.

    `in_preset` plays over the clip's first `in_duration` seconds, `out_preset` over its last
    `out_duration` seconds; either may be omitted. `slide_distance` is in the same pixels as
    `Transform.position`; `pop_from` is the starting fraction of the clip's own (static)
    `scale` for a `pop`. `wipe` reveals left-to-right and needs the clip to have no `mask` of
    its own -- see `effective_mask()`.

    A property a preset would animate is left alone if the clip already has an explicit
    keyframe for that exact property: hand-authored keyframes always win over a preset.
    """

    in_preset: AnimationPreset | None = Field(default=None, description="Entrance animation")
    out_preset: AnimationPreset | None = Field(default=None, description="Exit animation")
    in_duration: float = Field(default=0.5, gt=0.0, le=3600.0, description="Entrance length, seconds")
    out_duration: float = Field(default=0.5, gt=0.0, le=3600.0, description="Exit length, seconds")
    easing: Easing = Field(default=Easing.EASE_OUT, description="Easing used for both in and out")
    slide_distance: float = Field(default=120.0, gt=0.0, description="Slide travel distance, pixels")
    pop_from: float = Field(default=0.4, gt=0.0, lt=1.0, description="Starting scale as a fraction of final")
    wipe_feather: float = Field(default=0.0, ge=0.0, le=1.0, description="Softness of the wipe edge")

    @model_validator(mode="after")
    def _check_something_is_set(self) -> "ClipAnimation":
        if self.in_preset is None and self.out_preset is None:
            raise ValueError("ClipAnimation needs at least one of in_preset/out_preset set")
        return self


def _edge_for(preset: AnimationPreset, animation: ClipAnimation, base: float) -> float:
    if preset is AnimationPreset.FADE:
        return 0.0
    if preset is AnimationPreset.SLIDE_UP:
        return base + animation.slide_distance
    if preset is AnimationPreset.SLIDE_DOWN:
        return base - animation.slide_distance
    if preset is AnimationPreset.SLIDE_LEFT:
        return base + animation.slide_distance
    if preset is AnimationPreset.SLIDE_RIGHT:
        return base - animation.slide_distance
    if preset is AnimationPreset.POP:
        return base * animation.pop_from
    return 0.0  # WIPE: hidden


def _curve_for_property(
    prop: str,
    base: float,
    in_spec: tuple[float, float] | None,  # (edge, window)
    out_spec: tuple[float, float] | None,
    total: float,
    easing: Easing,
) -> PropertyCurve:
    """One combined curve for a property driven by an in-preset, an out-preset, or both.

    With both, the value holds at `base` between the two ramps -- unless the clip is shorter
    than `in_window + out_window`, in which case the ramps meet at the clip's midpoint instead
    of overlapping (so an entrance and exit both still play, just closer together).
    """
    if in_spec is None and out_spec is None:
        return PropertyCurve(keyframes=[Keyframe(time=Time(0), value=base)])
    if in_spec is not None and out_spec is None:
        edge, window = in_spec
        window = min(window, total) if total > 0 else window
        if window <= 0:
            return PropertyCurve(keyframes=[Keyframe(time=Time(0), value=base)])
        return PropertyCurve(
            keyframes=[
                Keyframe(time=Time(0), value=edge, easing=easing),
                Keyframe(time=Time(window), value=base),
            ]
        )
    if out_spec is not None and in_spec is None:
        edge, window = out_spec
        start = max(0.0, total - window)
        if start >= total:
            return PropertyCurve(keyframes=[Keyframe(time=Time(0), value=edge)])
        return PropertyCurve(
            keyframes=[
                Keyframe(time=Time(start), value=base, easing=easing),
                Keyframe(time=Time(total), value=edge),
            ]
        )

    in_edge, in_window = in_spec
    out_edge, out_window = out_spec
    if in_window + out_window <= total:
        mid_start, mid_end = in_window, total - out_window
    else:
        mid_start = mid_end = total / 2.0
    points = [(0.0, in_edge, easing), (mid_start, base, Easing.LINEAR)]
    if mid_end > mid_start:
        points.append((mid_end, base, easing))
    points.append((total, out_edge, easing))
    return PropertyCurve(keyframes=[Keyframe(time=Time(t), value=v, easing=e) for t, v, e in points])


def compile_animation(
    animation: ClipAnimation,
    duration: Time,
    transform: "Transform",
    existing: dict[str, PropertyCurve],
) -> dict[str, PropertyCurve]:
    """Curves for `animation`'s presets, at `duration`, for properties not already in `existing`.

    `transform` supplies the clip's own static values: the value a fade/slide/pop holds at
    between its ramps, and returns to afterwards. `wipe` is relative to a full reveal (1.0),
    independent of `transform`.
    """
    total = float(duration.seconds)
    touched: dict[str, tuple[tuple[float, float] | None, tuple[float, float] | None, float]] = {}

    for preset, window, is_in in (
        (animation.in_preset, animation.in_duration, True),
        (animation.out_preset, animation.out_duration, False),
    ):
        if preset is None:
            continue
        prop = _PRESET_PROPERTY[preset]
        if prop in existing:
            continue  # a hand-authored keyframe for this exact property always wins
        base = (
            1.0
            if prop == "mask.width"
            else {
                "opacity": float(transform.opacity),
                "position.y": float(transform.position.y),
                "position.x": float(transform.position.x),
                "scale": float(transform.scale),
            }[prop]
        )
        edge = _edge_for(preset, animation, base)
        in_spec, out_spec, _ = touched.get(prop, (None, None, base))
        if is_in:
            in_spec = (edge, window)
        else:
            out_spec = (edge, window)
        touched[prop] = (in_spec, out_spec, base)

    return {
        prop: _curve_for_property(prop, base, in_spec, out_spec, total, animation.easing)
        for prop, (in_spec, out_spec, base) in touched.items()
    }


__all__ = ["AnimationPreset", "ClipAnimation", "compile_animation"]
