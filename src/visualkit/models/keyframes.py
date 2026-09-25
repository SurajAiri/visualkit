"""Keyframe animation model: named easings, keyframes, and per-property curves.

A `PropertyCurve` is a list of `Keyframe`s for one animatable property (for
example ``"opacity"`` or ``"position.x"``). Two evaluators are provided and are
tested against each other:

* `PropertyCurve.value_at` -- pure Python, used by splits/trims, previews and tests.
* `PropertyCurve.to_expr`  -- an ffmpeg filter expression, used by the exporter.

Semantics (see also `VisualClip.keyframes`)
------------------------------------------
* Keyframe times are **clip-local timeline time**: ``Time(1)`` is one second
  after the clip's ``timeline_start``. They are *not* affected by the clip's
  ``speed`` -- ``speed`` retimes source content only.
* Before the first keyframe the curve holds the first value; after the last it
  holds the last value.
* A keyframe's ``easing`` shapes the segment that *starts* at that keyframe.
* Easings never overshoot, so a curve always stays within the range of its own
  keyframe values.

Why the expression is "flat"
----------------------------
ffmpeg fails on deeply nested ``if(lt(t,..),..,if(..))`` chains (it broke at 99
keyframes with an unhelpful error). `to_expr` therefore emits a sum of clamped
ramps whose nesting depth is constant regardless of the keyframe count::

    v0 + (v1-v0)*ease(clip((T-t0)/(t1-t0),0,1)) + (v2-v1)*ease(clip((T-t1)/...

Easing windows
--------------
Splitting or trimming a clip can cut *through* an eased segment. Restarting a
cubic ease from the cut point would change the shape of the motion, so a cut
keyframe records which part of the original easing it still covers in
`Keyframe.ease_window` (default ``(0, 1)`` = the whole easing). This keeps
``split_at`` / ``tail`` exact: the curve you had before the edit is the curve
you have after it.
"""

from __future__ import annotations

from bisect import bisect_right
from enum import Enum
from fractions import Fraction
from math import isfinite
from typing import Any, Callable, Iterable

from pydantic import Field, field_validator, model_validator

from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.time import Time


class Easing(str, Enum):
    """How a segment interpolates from its keyframe to the next one."""

    LINEAR = "linear"
    #: Stay at this keyframe's value until the next keyframe, then jump.
    HOLD = "hold"
    #: Cubic ease-in (slow start).
    EASE_IN = "ease_in"
    #: Cubic ease-out (slow finish).
    EASE_OUT = "ease_out"
    #: Cubic ease-in-out (slow start and finish).
    EASE_IN_OUT = "ease_in_out"


# --------------------------------------------------------------------------- easing maths
def _ease_in(u: float) -> float:
    return u**3


def _ease_out(u: float) -> float:
    return 1.0 - (1.0 - u) ** 3


def _ease_in_out(u: float) -> float:
    return 4.0 * u**3 if u < 0.5 else 1.0 - (-2.0 * u + 2.0) ** 3 / 2.0


_EASE_FUNCS: dict[Easing, Callable[[float], float]] = {
    Easing.LINEAR: lambda u: u,
    Easing.EASE_IN: _ease_in,
    Easing.EASE_OUT: _ease_out,
    Easing.EASE_IN_OUT: _ease_in_out,
}


def _ease_expr(easing: Easing, u: str) -> str:
    """ffmpeg expression for `easing` applied to the (already clamped) ramp `u`."""
    if easing == Easing.LINEAR:
        return u
    if easing == Easing.EASE_IN:
        return f"pow({u},3)"
    if easing == Easing.EASE_OUT:
        return f"(1-pow(1-{u},3))"
    if easing == Easing.EASE_IN_OUT:
        return f"if(lt({u},0.5),4*pow({u},3),1-pow(-2*{u}+2,3)/2)"
    raise ValueError(f"no expression form for easing {easing!r}")  # HOLD is handled by the caller


def fmt_num(x: float | Fraction | int) -> str:
    """Format a number for an ffmpeg expression: fixed-point, never scientific notation.

    ffmpeg's expression parser mishandles some exponent spellings, and a
    number like ``1e-05`` would otherwise appear for tiny values. Nine
    decimals is well below one video frame of time and far below one pixel.
    """
    value = float(x)
    if not isfinite(value):
        raise ValueError(f"cannot format non-finite number {x!r} into an ffmpeg expression")
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    if text in ("", "-", "-0"):
        return "0"
    return text


def _paren(x: float | Fraction | int) -> str:
    """`fmt_num` with negatives parenthesised so they are safe in any position."""
    text = fmt_num(x)
    return f"({text})" if text.startswith("-") else text


def _as_fraction(t: Time | Fraction | float | int) -> Fraction:
    if isinstance(t, Time):
        return t.value
    if isinstance(t, Fraction):
        return t
    if isinstance(t, bool):
        raise TypeError("time must be a number, not a bool")
    return Fraction(t)


# --------------------------------------------------------------------------- keyframe
class Keyframe(VisualKitModel):
    """One (time, value) sample of a property, plus how to leave it."""

    time: Time = Field(description="Clip-local time (seconds after the clip starts); not affected by speed")
    value: float = Field(allow_inf_nan=False, description="Property value at this time")
    easing: Easing = Field(
        default=Easing.LINEAR,
        description="Interpolation of the segment that STARTS at this keyframe",
    )
    ease_window: tuple[float, float] = Field(
        default=(0.0, 1.0),
        description=(
            "Advanced -- set by split/trim, rarely by hand. The part [a, b] of `easing` this segment "
            "covers, so cutting a clip through an eased segment does not reshape the motion."
        ),
    )

    @field_validator("ease_window")
    @classmethod
    def _check_window(cls, v: tuple[float, float]) -> tuple[float, float]:
        a, b = v
        if not (isfinite(a) and isfinite(b) and 0.0 <= a < b <= 1.0):
            raise ValueError(f"ease_window must satisfy 0 <= a < b <= 1, got {v}")
        return v

    def eased(self, u: float) -> float:
        """The 0..1 progress of this keyframe's segment at raw progress `u` (0..1)."""
        if self.easing == Easing.HOLD:
            return 1.0 if u >= 1.0 else 0.0
        e = _EASE_FUNCS[self.easing]
        a, b = self.ease_window
        if (a, b) == (0.0, 1.0):
            return e(u)
        ea, eb = e(a), e(b)
        return (e(a + (b - a) * u) - ea) / (eb - ea)

    def eased_expr(self, u: str) -> str:
        """ffmpeg expression equivalent of `eased` for the ramp expression `u`."""
        a, b = self.ease_window
        if (a, b) == (0.0, 1.0):
            return _ease_expr(self.easing, u)
        e = _EASE_FUNCS[self.easing]
        ea, eb = e(a), e(b)
        inner = _ease_expr(self.easing, f"({fmt_num(a)}+{fmt_num(b - a)}*{u})")
        return f"(({inner}-{_paren(ea)})/{fmt_num(eb - ea)})"


# --------------------------------------------------------------------------- curve
class PropertyCurve(VisualKitModel):
    """The keyframes of a single animatable property."""

    keyframes: list[Keyframe] = Field(min_length=1, description="Strictly increasing in time")

    @field_validator("keyframes")
    @classmethod
    def _check_order(cls, frames: list[Keyframe]) -> list[Keyframe]:
        for i in range(1, len(frames)):
            prev, cur = frames[i - 1].time, frames[i].time
            if cur == prev:
                raise ValueError(
                    f"keyframes {i - 1} and {i} share time {cur}; times must be strictly increasing "
                    "(two values at one instant would divide by zero when interpolated)"
                )
            if cur < prev:
                raise ValueError(
                    f"keyframe {i} at {cur} is earlier than keyframe {i - 1} at {prev}; "
                    "keyframes must be sorted (use PropertyCurve.from_points to sort automatically)"
                )
        return frames

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_points(
        cls,
        points: Iterable[
            tuple[Time | float | Fraction, float] | tuple[Time | float | Fraction, float, Easing]
        ],
        easing: Easing = Easing.LINEAR,
    ) -> "PropertyCurve":
        """Build a curve from ``(time, value)`` or ``(time, value, easing)`` tuples, sorting by time.

        `easing` is the default for tuples that do not name their own. Times may be
        `Time` or plain seconds. Duplicate times still raise (they are ambiguous).
        """
        frames: list[Keyframe] = []
        for point in points:
            if len(point) == 3:
                t, v, e = point  # type: ignore[misc]
            else:
                (t, v), e = point, easing  # type: ignore[misc]
            frames.append(Keyframe(time=Time(t), value=v, easing=Easing(e)))
        frames.sort(key=lambda k: k.time.value)
        return cls(keyframes=frames)

    # ------------------------------------------------------------------ introspection
    @property
    def min_value(self) -> float:
        return min(k.value for k in self.keyframes)

    @property
    def max_value(self) -> float:
        return max(k.value for k in self.keyframes)

    @property
    def end_time(self) -> Time:
        return self.keyframes[-1].time

    def _times(self) -> list[Fraction]:
        return [k.time.value for k in self.keyframes]

    # ------------------------------------------------------------------ evaluation
    def value_at(self, t: Time | Fraction | float | int) -> float:
        """The property's value at clip-local time `t` (seconds). Pure Python, exact segment maths."""
        frames = self.keyframes
        moment = _as_fraction(t)
        if moment <= frames[0].time.value:
            return frames[0].value
        if moment >= frames[-1].time.value:
            return frames[-1].value
        i = bisect_right(self._times(), moment) - 1
        k0, k1 = frames[i], frames[i + 1]
        u = float((moment - k0.time.value) / (k1.time.value - k0.time.value))
        return k0.value + (k1.value - k0.value) * k0.eased(u)

    def to_expr(self, clip_start_s: Time | Fraction | float | int, *, var: str = "t") -> str:
        """A flat ffmpeg expression giving this curve's value at timeline time `var`.

        `var` inside overlay/scale/rotate is **absolute timeline time**, because the
        exporter shifts each clip with ``setpts=...+start/TB``. Keyframe times are
        clip-local, so every ramp is written against ``clip_start + keyframe_time``
        (computed exactly, then formatted once).

        Expressions never contain scientific notation or anything except numbers
        formatted here and ffmpeg's own function names.
        """
        start = _as_fraction(clip_start_s)
        frames = self.keyframes
        terms = [fmt_num(frames[0].value)]
        for k0, k1 in zip(frames, frames[1:]):
            delta = k1.value - k0.value
            if delta == 0:
                continue  # a flat segment contributes nothing
            abs1 = start + k1.time.value
            if k0.easing == Easing.HOLD:
                ramp_or_step = f"gte({var},{fmt_num(abs1)})"
            else:
                abs0 = start + k0.time.value
                dt = k1.time.value - k0.time.value
                ramp = f"clip(({var}-{fmt_num(abs0)})/{fmt_num(dt)},0,1)"
                ramp_or_step = k0.eased_expr(ramp)
            terms.append(f"{_paren(delta)}*{ramp_or_step}")
        return "+".join(terms)

    # ------------------------------------------------------------------ editing (split / trim)
    def _key_at_or_before(self, moment: Fraction) -> int:
        """Index of the last keyframe whose time <= moment (assumes moment >= first time)."""
        return bisect_right(self._times(), moment) - 1

    def _cut_key(self, moment: Fraction) -> Keyframe:
        """A keyframe at `moment` carrying the curve's value there and the *remainder* of the
        segment it falls in (so the motion after the cut keeps its exact shape)."""
        frames = self.keyframes
        value = self.value_at(moment)
        i = self._key_at_or_before(moment)
        k0 = frames[i]
        if i + 1 >= len(frames) or k0.easing in (Easing.LINEAR, Easing.HOLD):
            # Linear and hold restart cleanly from any interior point.
            return Keyframe(time=Time(moment), value=value, easing=k0.easing)
        t0, t1 = k0.time.value, frames[i + 1].time.value
        u_cut = float((moment - t0) / (t1 - t0))
        a, b = k0.ease_window
        new_a = a + (b - a) * u_cut
        return Keyframe(time=Time(moment), value=value, easing=k0.easing, ease_window=(new_a, b))

    def head(self, end: Time | Fraction | float | int) -> "PropertyCurve":
        """The curve limited to local times ``[0, end]`` (for the first half of a split / a trim-out).

        Keyframes after `end` are dropped and a boundary keyframe at `end` carries the value
        there, so the curve is continuous. The keyframe before `end` records that its segment
        now stops part-way through its easing.
        """
        cut = _as_fraction(end)
        frames = self.keyframes
        if cut >= frames[-1].time.value:
            return self.model_copy(deep=True)
        if cut <= frames[0].time.value:
            return PropertyCurve(keyframes=[Keyframe(time=Time(cut), value=frames[0].value)])

        i = self._key_at_or_before(cut)
        kept = [k.model_copy(deep=True) for k in frames[: i + 1]]
        if frames[i].time.value == cut:
            kept[-1] = kept[-1].model_copy(update={"easing": Easing.LINEAR, "ease_window": (0.0, 1.0)})
            return PropertyCurve(keyframes=kept)

        k0, k1 = frames[i], frames[i + 1]
        boundary_value = self.value_at(cut)
        if k0.easing not in (Easing.LINEAR, Easing.HOLD):
            u_cut = float((cut - k0.time.value) / (k1.time.value - k0.time.value))
            a, b = k0.ease_window
            kept[-1] = k0.model_copy(update={"ease_window": (a, a + (b - a) * u_cut)})
        kept.append(Keyframe(time=Time(cut), value=boundary_value))
        return PropertyCurve(keyframes=kept)

    def tail(self, offset: Time | Fraction | float | int) -> "PropertyCurve":
        """The curve as seen from `offset` seconds later: ``tail(o).value_at(x) == value_at(x + o)``.

        For the second half of a split / a trim-in. Keyframes at or after `offset` shift earlier
        by `offset`; if `offset` falls inside a segment a keyframe at local 0 carries the
        interpolated value (and the rest of that segment's easing). A negative `offset`
        (revealing pre-roll) shifts everything later; the first value is held before it.
        """
        shift = _as_fraction(offset)
        frames = self.keyframes
        if shift < 0:
            return PropertyCurve(
                keyframes=[k.model_copy(update={"time": Time(k.time.value - shift)}) for k in frames]
            )
        if shift == 0:
            return self.model_copy(deep=True)
        last_t = frames[-1].time.value
        if shift >= last_t:
            return PropertyCurve(keyframes=[Keyframe(time=Time.zero(), value=frames[-1].value)])

        first_t = frames[0].time.value
        remaining = [k for k in frames if k.time.value >= shift]
        shifted = [k.model_copy(update={"time": Time(k.time.value - shift)}) for k in remaining]
        needs_cut_key = shift > first_t and remaining[0].time.value != shift
        if needs_cut_key:
            shifted.insert(0, self._cut_key(shift).model_copy(update={"time": Time.zero()}))
        return PropertyCurve(keyframes=shifted)

    def time_scaled(self, factor: Fraction | float | int) -> "PropertyCurve":
        """Every keyframe time multiplied by `factor` (> 0); values and easings are unchanged."""
        f = _as_fraction(factor)
        if f <= 0:
            raise ValueError(f"time scale factor must be positive, got {factor}")
        return PropertyCurve(
            keyframes=[k.model_copy(update={"time": Time(k.time.value * f)}) for k in self.keyframes]
        )


# --------------------------------------------------------------------------- allowed properties
class CurveSpec(VisualKitModel):
    """Bounds a curve's values must respect, mirroring the static field it overrides."""

    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False


#: Properties that can be keyframed on a `VisualClip`, with the same bounds as the static
#: `Transform` fields they override (Pydantic's `Field(ge/le)` does not apply to curve values).
KEYFRAMEABLE_PROPERTIES: dict[str, CurveSpec] = {
    "position.x": CurveSpec(),
    "position.y": CurveSpec(),
    "scale": CurveSpec(minimum=0.0, maximum=100.0, exclusive_minimum=True),
    "rotation": CurveSpec(minimum=-3600.0, maximum=3600.0),
    "zoom": CurveSpec(minimum=0.0, maximum=100.0, exclusive_minimum=True),
    "opacity": CurveSpec(minimum=0.0, maximum=100.0),
    # Mask geometry (normalised to the clip frame); needs `VisualClip.mask` to be set.
    "mask.x": CurveSpec(minimum=0.0, maximum=1.0),
    "mask.y": CurveSpec(minimum=0.0, maximum=1.0),
    "mask.width": CurveSpec(minimum=0.0, maximum=1.0),
    "mask.height": CurveSpec(minimum=0.0, maximum=1.0),
    "mask.feather": CurveSpec(minimum=0.0, maximum=1.0),
}


def validate_curves(curves: dict[str, PropertyCurve], duration: Time | None = None) -> None:
    """Raise `ValueError` for unknown property names, out-of-bounds values, or keys past `duration`."""
    for name, curve in curves.items():
        spec = KEYFRAMEABLE_PROPERTIES.get(name)
        if spec is None:
            allowed = ", ".join(sorted(KEYFRAMEABLE_PROPERTIES))
            raise ValueError(f"cannot keyframe unknown property {name!r}; allowed: {allowed}")
        for i, key in enumerate(curve.keyframes):
            v = key.value
            if spec.minimum is not None and (
                v <= spec.minimum if spec.exclusive_minimum else v < spec.minimum
            ):
                op = ">" if spec.exclusive_minimum else ">="
                raise ValueError(f"keyframes[{name!r}][{i}].value={v} must be {op} {spec.minimum}")
            if spec.maximum is not None and v > spec.maximum:
                raise ValueError(f"keyframes[{name!r}][{i}].value={v} must be <= {spec.maximum}")
        if duration is not None and curve.end_time > duration:
            raise ValueError(
                f"keyframes[{name!r}] has a keyframe at {curve.end_time}, after the clip ends "
                f"(duration {duration}); keyframe times are clip-local"
            )


__all__ = [
    "Easing",
    "Keyframe",
    "PropertyCurve",
    "CurveSpec",
    "KEYFRAMEABLE_PROPERTIES",
    "validate_curves",
    "fmt_num",
]
