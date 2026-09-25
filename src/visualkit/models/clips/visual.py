from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from visualkit.models.animation import ClipAnimation, compile_animation
from visualkit.models.effects import ChromaKey, Mask
from visualkit.models.keyframes import PropertyCurve, validate_curves
from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.time import Time

from .base import BaseClip, Position, Size


class Transform(VisualKitModel):
    """Visual placement/appearance applied when compositing a clip onto the
    target canvas. Exporters apply these fields in a fixed order:
    1. Fit the clip's natural content to `size` (or to the canvas, if
       `size` is (0, 0) -- see `Size`), preserving aspect ratio.
    2. Crop into the result by `zoom` (a punch-in: cropping happens
       first, then the cropped region is scaled back up to fill the same
       frame -- unlike `scale`, this only affects how much of the source
       is visible, not the frame's own footprint).
    3. Scale the whole frame by `scale` (a uniform size multiplier of the
       already zoomed/cropped frame; 1.0 is the identity -- unlike
       `opacity`, this is a multiplier, not a percent).
    4. Rotate by `rotation` degrees, about the frame's own center.
    5. Offset by `position` (pixels on the target canvas, from center).
    6. Apply `opacity` (0-100 percent) last, when compositing over
       whatever is beneath it.

    These are the *static* values. To animate any of them, put a
    `PropertyCurve` in the owning clip's `VisualClip.keyframes`; a keyed
    property ignores its static value here. `is_identity` looks only at the
    static values on purpose: DaVinci Resolve export reads `Transform` alone
    (it ignores keyframes) and must not treat an untouched transform as modified.
    """

    position: Position = Field(
        default_factory=Position, description="Offset from center on the target canvas, in pixels"
    )
    size: Size = Field(
        default_factory=Size, description="Explicit target size in pixels, or (0, 0) to fit the canvas"
    )
    rotation: float = Field(
        default=0.0,
        ge=-3600.0,
        le=3600.0,
        description=(
            "Rotation of the transform in degrees. Not clamped to a single "
            "turn: negative values (counter-clockwise) and values beyond "
            "360 (multiple full turns, useful for spin animations once "
            "keyframing lands) are both valid."
        ),
    )
    scale: float = Field(
        default=1.0,
        gt=0.0,
        le=100.0,
        description=(
            "Uniform size multiplier applied to the whole frame after "
            "zoom/crop (1.0 = 100% = identity; 0.5 = half size; 2.0 = "
            "double size). Unlike `opacity`, this is a multiplier, not a "
            "0-100 percent -- the field's upper bound of 100.0 permits up "
            "to 100x, not 100%."
        ),
    )
    zoom: float = Field(
        default=1.0,
        gt=0.0,
        le=100.0,
        description=(
            "Digital punch-in (1.0 = no zoom = identity): crops into the "
            "center of the frame by this multiplier before scaling the "
            "cropped region back up to fill the original frame footprint. "
            "Distinct from `scale`, which resizes the frame's own "
            "footprint rather than cropping into its content."
        ),
    )
    opacity: int = Field(
        default=100,
        ge=0,
        le=100,
        description="Opacity as a 0-100 percent (100 = fully opaque), applied when compositing.",
    )

    @property
    def is_identity(self) -> bool:
        """True if this transform changes nothing (default position, size, rotation, scale, zoom, opacity).

        Exporters skip emitting motion/opacity effects for identity transforms so imported clips
        stay "clean" (no spurious modified-clip state in an NLE's inspector).
        """
        return (
            self.position.x == 0
            and self.position.y == 0
            and self.size.width == 0
            and self.size.height == 0
            and self.rotation == 0
            and self.scale == 1
            and self.zoom == 1
            and self.opacity == 100
        )

    @classmethod
    def at_anchor(
        cls,
        anchor: str,
        margin: float = 0.0,
        *,
        canvas_size: tuple[float, float] = (1920.0, 1080.0),
        **kwargs: Any,
    ) -> "Transform":
        """Build a `Transform` positioned at one of `Position`'s 9 standard
        screen anchors -- see `Position.from_anchor` for `anchor`,
        `margin`, and `canvas_size`. Any other `Transform` field can be
        passed through as a keyword, e.g.
        `Transform.at_anchor("bottom", margin=80, scale=0.9)` for a
        caption sitting 80px above the bottom edge at 90% size.
        """
        return cls(position=Position.from_anchor(anchor, margin, canvas_size=canvas_size), **kwargs)


def _trimmed_animation(
    animation: "ClipAnimation | None", *, keep_in: bool, keep_out: bool
) -> "ClipAnimation | None":
    """`animation` with `in_preset`/`out_preset` dropped for the half of a `split_clip` cut
    that no longer sits at the clip's true start/end (see `visualkit.models.animation`'s module
    docstring for why `trim_in`/`trim_out` don't need this)."""
    if animation is None:
        return None
    new_in = animation.in_preset if keep_in else None
    new_out = animation.out_preset if keep_out else None
    if new_in is None and new_out is None:
        return None
    return animation.model_copy(update={"in_preset": new_in, "out_preset": new_out})


class VisualClip(BaseClip):
    """Base Class for all visual clips placed on a track"""

    transform: Transform = Field(
        default_factory=Transform, description="Transform properties of the visual clip"
    )
    keyframes: dict[str, PropertyCurve] = Field(
        default_factory=dict,
        description=(
            "Animation curves keyed by property name: 'position.x', 'position.y', 'scale', "
            "'rotation', 'zoom', 'opacity'. A keyed property ignores its static value in "
            "`transform`. Keyframe times are clip-local timeline time (seconds after "
            "`timeline_start`) and are NOT affected by `speed`. Rendered by the FFmpeg video "
            "exporter only; DaVinci Resolve export ignores keyframes. The mask geometry can be "
            "keyed too: 'mask.x', 'mask.y', 'mask.width', 'mask.height', 'mask.feather'."
        ),
    )
    chroma_key: ChromaKey | None = Field(
        default=None,
        description=(
            "Remove a green/blue screen. Applied first, before the clip is fitted or transformed. "
            "FFmpeg exporter only."
        ),
    )
    mask: Mask | None = Field(
        default=None,
        description=(
            "Show only a rectangle or ellipse of the clip, in the clip's own frame (before its "
            "transform is applied). FFmpeg exporter only."
        ),
    )
    animation: ClipAnimation | None = Field(
        default=None,
        description=(
            "In/out animation presets (fade, slide, pop, wipe), sugar over `keyframes`/`mask` -- "
            "see `visualkit.models.animation`. An explicit `keyframes`/`mask` entry for a property "
            "a preset would drive always wins. FFmpeg exporter only."
        ),
    )

    @field_validator("keyframes")
    @classmethod
    def _check_keyframe_names_and_bounds(cls, curves: dict[str, PropertyCurve]) -> dict[str, PropertyCurve]:
        validate_curves(curves)
        return curves

    @model_validator(mode="after")
    def _check_keyframe_times_fit_the_clip(self) -> "VisualClip":
        validate_curves(self.keyframes, self.duration)
        if self.mask is None:
            orphans = sorted(name for name in self.keyframes if name.startswith("mask."))
            if orphans:
                raise ValueError(f"keyframes for {orphans} need a `mask` on the clip to animate")
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        """Assignment that leaves the clip unchanged when validation rejects it.

        Pydantic runs model-level validators (like the keyframe-vs-duration check above)
        *after* it has stored the new value and does not undo that if the validator raises,
        so a rejected ``clip.duration = ...`` would otherwise leave the clip half-mutated.
        """
        if name not in type(self).model_fields:
            super().__setattr__(name, value)
            return
        missing = object()
        previous = self.__dict__.get(name, missing)
        previous_set = set(self.__pydantic_fields_set__)
        try:
            super().__setattr__(name, value)
        except Exception:
            if previous is missing:
                self.__dict__.pop(name, None)
            else:
                self.__dict__[name] = previous
            object.__setattr__(self, "__pydantic_fields_set__", previous_set)
            raise

    @property
    def is_animated(self) -> bool:
        """True if any property is keyframed or an `animation` preset is set."""
        return bool(self.keyframes) or self.animation is not None

    def transform_at(self, time: "Time | float") -> Transform:
        """A static `Transform` with every keyed property resolved at clip-local `time` (seconds).

        `opacity` is rounded to the nearest whole percent because `Transform.opacity` is an int.
        """
        seconds = time
        data = self.transform.model_dump()
        for name, curve in self.effective_keyframes().items():
            value = curve.value_at(seconds)
            if name.startswith("mask."):
                continue  # mask geometry is not part of `Transform`; see `mask_at`
            if name == "position.x":
                data["position"]["x"] = value
            elif name == "position.y":
                data["position"]["y"] = value
            elif name == "opacity":
                data["opacity"] = round(value)
            else:
                data[name] = value
        return Transform.model_validate(data)

    def effective_keyframes(self) -> dict[str, PropertyCurve]:
        """`keyframes`, plus any curve `animation` compiles in for a property not already keyed.

        This is what `transform_at`/`mask_at` and the FFmpeg exporter actually render from --
        `animation` itself is never baked into `keyframes` (see `visualkit.models.animation`).
        A `wipe` preset's `mask.width` curve is dropped when the clip has its own `mask`: that
        mask's own `width` should not be silently overridden by the (then-inapplicable) wipe.
        """
        if self.animation is None:
            return self.keyframes
        compiled = compile_animation(self.animation, self.duration, self.transform, self.keyframes)
        if self.mask is not None:
            compiled = {k: v for k, v in compiled.items() if not k.startswith("mask.")}
        return {**compiled, **self.keyframes}

    def effective_mask(self) -> Mask | None:
        """`mask`, or a full-frame rect mask if `animation` has an unopposed `wipe` preset."""
        if self.mask is not None:
            return self.mask
        if self.animation is not None and "mask.width" in self.effective_keyframes():
            return Mask(
                shape="rect", x=0.5, y=0.5, width=1.0, height=1.0, feather=self.animation.wipe_feather
            )
        return None

    def mask_at(self, time: "Time | float") -> Mask | None:
        """The clip's effective `Mask` with any keyed geometry resolved at clip-local `time`."""
        mask = self.effective_mask()
        if mask is None:
            return None
        data = mask.model_dump()
        for name, curve in self.effective_keyframes().items():
            if name.startswith("mask."):
                data[name.removeprefix("mask.")] = curve.value_at(time)
        return Mask.model_validate(data)

    def set_duration_and_keyframes(
        self, duration: Time, keyframes: dict[str, PropertyCurve] | None = None
    ) -> None:
        """Change `duration` and `keyframes` together without ever tripping the clip's own validation.

        Keyframe times must not exceed `duration`, and both fields validate on assignment, so
        the order matters: when the clip shrinks, the (already shortened) keyframes go first;
        when it grows, the duration goes first. Use this from any code that retimes a clip.
        """
        new_keys = self.keyframes if keyframes is None else keyframes
        if duration <= self.duration:
            self.keyframes = new_keys
            self.duration = duration
        else:
            self.duration = duration
            self.keyframes = new_keys
