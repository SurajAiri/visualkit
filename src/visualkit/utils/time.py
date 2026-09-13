"""Time representation for VisualKit.

Provides frame-accurate, rational-time arithmetic to eliminate
floating-point drift across multi-clip timelines.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema

from .exceptions import InvalidTimeError

TIMECODE_REGEX = re.compile(r"^(\d{2}):(\d{2}):(\d{2})[:;](\d{2})$")

# Any float-derived Fraction is snapped to the nearest fraction with a
# denominator no larger than this. This bounds (but does not eliminate)
# the precision loss inherent to accepting floats at all. See from_seconds
# / the float branch of __init__ for where this actually applies.
_FLOAT_DENOMINATOR_LIMIT = 1_000_000


def _fraction_round(frac: Fraction) -> int:
    """Round a Fraction to the nearest int, half-to-even, without ever
    going through float. This is the rounding `to_frames` needs: exact
    all the way to the final integer decision.
    """
    floor_val = frac.numerator // frac.denominator
    remainder = frac - floor_val
    half = Fraction(1, 2)
    if remainder < half:
        return floor_val
    if remainder > half:
        return floor_val + 1
    # Exactly .5 -> round to even, matching Python's own `round()` semantics
    return floor_val if floor_val % 2 == 0 else floor_val + 1


def _fps_to_fraction(fps: Fraction | int | float) -> Fraction:
    """Convert an fps value to an exact Fraction.

    Fraction/int inputs are treated as exact (this is how you should pass
    NTSC rates: Fraction(30000, 1001), not 29.97). float inputs are
    accepted for convenience but are inherently lossy -- 29.97 as a float
    is not exactly 30000/1001 -- so they're limit_denominator'd as a
    best-effort recovery, not a guarantee of the canonical rate.
    """
    if isinstance(fps, Fraction):
        return fps
    if isinstance(fps, int):
        return Fraction(fps, 1)
    if isinstance(fps, float):
        return Fraction(fps).limit_denominator(_FLOAT_DENOMINATOR_LIMIT)
    raise InvalidTimeError(f"Unsupported fps type: {type(fps)}")


class Time:
    """Represents a duration or timestamp on a timeline with exact rational precision.

    Time values are always non-negative. Attempting to construct a Time
    with a negative value, or to produce one via arithmetic, raises
    InvalidTimeError.
    """

    __slots__ = ("_value",)

    def __init__(self, value: Fraction | int | float | str | Time = 0) -> None:
        if isinstance(value, Time):
            candidate = value._value
        elif isinstance(value, Fraction):
            candidate = value
        elif isinstance(value, int):
            candidate = Fraction(value, 1)
        elif isinstance(value, float):
            # Lossy: floats are snapped to the nearest simple fraction.
            # Prefer constructing from Fraction, int, or from_frames/
            # from_timecode wherever the value's provenance is exact.
            candidate = Fraction(value).limit_denominator(_FLOAT_DENOMINATOR_LIMIT)
        elif isinstance(value, str):
            candidate = self._parse_str(value)._value
        else:
            raise InvalidTimeError(f"Unsupported time value type: {type(value)}")

        if candidate < 0:
            raise InvalidTimeError(f"Time cannot be negative, got {candidate} ({float(candidate)}s)")

        self._value = candidate

    @property
    def value(self) -> Fraction:
        """The underlying exact Fraction of seconds."""
        return self._value

    @property
    def seconds(self) -> float:
        """Time expressed in seconds as a float. Lossy for display/interop only --
        prefer `.value` (exact Fraction) for any further computation."""
        return float(self._value)

    @classmethod
    def zero(cls) -> Time:
        """Returns zero time."""
        return cls(Fraction(0, 1))

    @classmethod
    def from_seconds(cls, seconds: float | int | str) -> Time:
        """Creates a Time instance from seconds.

        Note: float input is lossy (see class docstring / __init__). If you
        have an exact rational number of seconds, pass a Fraction or an
        int-valued string like "7/3" instead.
        """
        if isinstance(seconds, (int, float)):
            return cls(seconds)
        if isinstance(seconds, str):
            clean = seconds.strip().rstrip("sS")
            try:
                # Try exact parse first (handles ints and "n/d" forms)
                # before falling back to the lossy float path.
                return cls(Fraction(clean))
            except ValueError:
                pass
            return cls(float(clean))
        raise InvalidTimeError(f"Invalid seconds value: {seconds}")

    @classmethod
    def from_frames(cls, frames: int, fps: Fraction | int | float = 30) -> Time:
        """Creates a Time instance from frame count at a given framerate.

        This is exact when fps is given as a Fraction or int (e.g.
        Fraction(30000, 1001) for 29.97 NTSC). Passing fps as a float is
        accepted for convenience but is a lossy approximation of the true
        rate -- see _fps_to_fraction.
        """
        if fps <= 0:
            raise InvalidTimeError(f"Framerate must be positive, got {fps}")
        frac_fps = _fps_to_fraction(fps)
        return cls(Fraction(frames, 1) / frac_fps)

    @classmethod
    def from_timecode(cls, timecode: str, fps: int = 30) -> Time:
        """Parses SMPTE timecode (HH:MM:SS:FF or HH:MM:SS;FF) into Time."""
        match = TIMECODE_REGEX.match(timecode.strip())
        if not match:
            raise InvalidTimeError(f"Invalid timecode format: '{timecode}'. Expected HH:MM:SS:FF")
        hours, minutes, seconds, frames = map(int, match.groups())
        total_seconds = Fraction(hours * 3600 + minutes * 60 + seconds, 1)
        frame_seconds = Fraction(frames, fps)
        return cls(total_seconds + frame_seconds)

    def to_frames(self, fps: Fraction | int | float = 30) -> int:
        """Converts to total frames at given framerate (rounded to nearest
        frame, half-to-even), computed entirely in exact rational
        arithmetic -- no float is involved in the rounding decision."""
        frac_fps = _fps_to_fraction(fps)
        frame_count = self._value * frac_fps  # exact Fraction
        return _fraction_round(frame_count)

    def to_timecode(self, fps: int = 30) -> str:
        """Formats into SMPTE timecode HH:MM:SS:FF at given fps."""
        total_frames = self.to_frames(fps)

        frames_per_sec = fps
        frames_per_min = frames_per_sec * 60
        frames_per_hour = frames_per_min * 60

        hours = total_frames // frames_per_hour
        rem = total_frames % frames_per_hour
        minutes = rem // frames_per_min
        rem = rem % frames_per_min
        seconds = rem // frames_per_sec
        frames = rem % frames_per_sec

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

    @classmethod
    def _parse_str(cls, text: str) -> Time:
        text = text.strip()
        if TIMECODE_REGEX.match(text):
            return cls.from_timecode(text)
        if text.endswith(("s", "S")):
            return cls.from_seconds(text[:-1])
        if "/" in text:
            parts = text.split("/")
            if len(parts) == 2:
                return cls(Fraction(int(parts[0]), int(parts[1])))
        try:
            return cls(float(text))
        except ValueError as err:
            raise InvalidTimeError(f"Cannot parse time string: '{text}'") from err

    # Arithmetic
    # Note: subtraction (and any other op that can go negative) raises
    # InvalidTimeError via the Time() constructor if the result is negative.
    # This is deliberate -- see class docstring. If you need a signed
    # delta between two timeline positions (e.g. "is A before or after B"),
    # compare/subtract the underlying `.value` Fractions directly instead
    # of going through Time subtraction.
    def __add__(self, other: Any) -> Time:
        if isinstance(other, Time):
            return Time(self._value + other._value)
        if isinstance(other, (int, float, Fraction)):
            return Time(self._value + Time(other)._value)
        return NotImplemented

    def __radd__(self, other: Any) -> Time:
        return self.__add__(other)

    def __sub__(self, other: Any) -> Time:
        if isinstance(other, Time):
            return Time(self._value - other._value)
        if isinstance(other, (int, float, Fraction)):
            return Time(self._value - Time(other)._value)
        return NotImplemented

    def __rsub__(self, other: Any) -> Time:
        if isinstance(other, (int, float, Fraction)):
            return Time(Time(other)._value - self._value)
        return NotImplemented

    @staticmethod
    def _as_exact_fraction(scalar: int | float | Fraction) -> Fraction:
        """Coerce a plain number to a Fraction for use as a multiplier/divisor.
        float is lossy (limit_denominator'd); int/Fraction are exact."""
        if isinstance(scalar, Fraction):
            return scalar
        if isinstance(scalar, float):
            return Fraction(scalar).limit_denominator(_FLOAT_DENOMINATOR_LIMIT)
        return Fraction(scalar)

    def __mul__(self, scalar: Any) -> Time:
        if isinstance(scalar, (int, float, Fraction)):
            return Time(self._value * self._as_exact_fraction(scalar))
        return NotImplemented

    def __rmul__(self, scalar: Any) -> Time:
        return self.__mul__(scalar)

    def __truediv__(self, other: Any) -> Any:
        if isinstance(other, Time):
            if other._value == 0:
                raise ZeroDivisionError("Cannot divide by zero Time")
            return float(self._value / other._value)
        if isinstance(other, (int, float, Fraction)):
            if other == 0:
                raise ZeroDivisionError("Cannot divide by zero")
            return Time(self._value / self._as_exact_fraction(other))
        return NotImplemented

    def __neg__(self) -> Time:
        # A Time is never negative, so negating a non-zero Time is always
        # invalid. Time(0) negates to Time(0). This exists mainly so
        # `-Time.zero()` doesn't blow up; negating any real duration
        # should raise, which Time()'s own validation handles.
        return Time(-self._value)

    def __abs__(self) -> Time:
        # Time is already non-negative by construction, so this is a no-op,
        # kept only for interface compatibility with numeric types.
        return Time(self._value)

    # Comparisons
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return self._value == other._value
        if isinstance(other, (int, float, Fraction)):
            try:
                return self._value == Time(other)._value
            except InvalidTimeError:
                return False
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return self._value < other._value
        if isinstance(other, (int, float, Fraction)):
            return self._value < Time(other)._value
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        result = self.__lt__(other)
        if result is NotImplemented:
            return result
        return result or self == other

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return self._value > other._value
        if isinstance(other, (int, float, Fraction)):
            return self._value > Time(other)._value
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        result = self.__gt__(other)
        if result is NotImplemented:
            return result
        return result or self == other

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"Time({self.seconds:.4f}s [{self._value}])"

    def __str__(self) -> str:
        return f"{self.seconds:.3f}s"

    def __float__(self) -> float:
        return self.seconds

    # Pydantic v2 Core Schema Integration
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        def validate(val: Any) -> Time:
            if isinstance(val, Time):
                return val
            if isinstance(val, (int, float, str, Fraction)):
                return Time(val)
            if isinstance(val, dict):
                if "numerator" in val and "denominator" in val:
                    return Time(Fraction(val["numerator"], val["denominator"]))
                if "seconds" in val:
                    return Time.from_seconds(val["seconds"])
            raise InvalidTimeError(f"Cannot convert {val!r} to Time")

        def serialize(t: Time) -> dict[str, int]:
            # Serialize as an exact numerator/denominator pair so
            # save/load round-trips lose no precision. This matters most
            # for persistence: repeated save/reload cycles must not
            # accumulate float rounding error the way a float
            # serialization would.
            frac = t.value
            return {"numerator": frac.numerator, "denominator": frac.denominator}

        python_schema = core_schema.chain_schema(
            [
                core_schema.no_info_plain_validator_function(validate),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=core_schema.chain_schema(
                [
                    core_schema.no_info_plain_validator_function(validate),
                ]
            ),
            python_schema=python_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize,
                return_schema=core_schema.typed_dict_schema(
                    {
                        "numerator": core_schema.typed_dict_field(core_schema.int_schema()),
                        "denominator": core_schema.typed_dict_field(core_schema.int_schema()),
                    }
                ),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {
            "type": "object",
            "properties": {
                "numerator": {"type": "integer"},
                "denominator": {"type": "integer"},
            },
            "required": ["numerator", "denominator"],
            "description": (
                "Duration or timestamp as an exact fraction of seconds "
                "(numerator/denominator), to avoid floating-point drift on "
                "save/load. Also accepts a plain number of seconds, an "
                "'n/d' string, or SMPTE timecode 'HH:MM:SS:FF' as input."
            ),
        }
