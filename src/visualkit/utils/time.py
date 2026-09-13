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


class Time:
    """Represents a duration or timestamp on a timeline with exact rational precision."""

    __slots__ = ("_value",)

    def __init__(self, value: Fraction | int | float | str | Time = 0) -> None:
        if isinstance(value, Time):
            self._value = value._value
        elif isinstance(value, Fraction):
            self._value = value
        elif isinstance(value, int):
            self._value = Fraction(value, 1)
        elif isinstance(value, float):
            # Limit denominator to avoid extreme precision artifacts from IEEE 754 float conversion
            self._value = Fraction(value).limit_denominator(1_000_000)
        elif isinstance(value, str):
            parsed = self._parse_str(value)
            self._value = parsed._value
        else:
            raise InvalidTimeError(f"Unsupported time value type: {type(value)}")

        if self._value < 0:
            # Note: Durations should not be negative in standard timeline operations
            pass

    @property
    def value(self) -> Fraction:
        """The underlying exact Fraction of seconds."""
        return self._value

    @property
    def seconds(self) -> float:
        """Time expressed in seconds as a float."""
        return float(self._value)

    @classmethod
    def zero(cls) -> Time:
        """Returns zero time."""
        return cls(Fraction(0, 1))

    @classmethod
    def from_seconds(cls, seconds: float | int | str) -> Time:
        """Creates a Time instance from seconds."""
        if isinstance(seconds, (int, float)):
            return cls(seconds)
        if isinstance(seconds, str):
            clean = seconds.strip().rstrip("sS")
            return cls(float(clean))
        raise InvalidTimeError(f"Invalid seconds value: {seconds}")

    @classmethod
    def from_frames(cls, frames: int, fps: float | int = 30) -> Time:
        """Creates a Time instance from frame count at a given framerate."""
        if fps <= 0:
            raise InvalidTimeError(f"Framerate must be positive, got {fps}")
        frac_fps = Fraction(fps).limit_denominator(1_000_000)
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

    def to_frames(self, fps: float | int = 30) -> int:
        """Converts to total frames at given framerate (rounded to nearest frame)."""
        frac_fps = Fraction(fps).limit_denominator(1_000_000)
        return round(float(self._value * frac_fps))

    def to_timecode(self, fps: int = 30) -> str:
        """Formats into SMPTE timecode HH:MM:SS:FF at given fps."""
        total_frames = self.to_frames(fps)
        if total_frames < 0:
            total_frames = 0

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

    def __mul__(self, scalar: Any) -> Time:
        if isinstance(scalar, (int, float, Fraction)):
            return Time(self._value * Fraction(scalar).limit_denominator(1_000_000))
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
            return Time(self._value / Fraction(other).limit_denominator(1_000_000))
        return NotImplemented

    def __neg__(self) -> Time:
        return Time(-self._value)

    def __abs__(self) -> Time:
        return Time(abs(self._value))

    # Comparisons
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return self._value == other._value
        if isinstance(other, (int, float, Fraction)):
            return self._value == Time(other)._value
        return False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return self._value < other._value
        if isinstance(other, (int, float, Fraction)):
            return self._value < Time(other)._value
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        return self < other or self == other

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return self._value > other._value
        if isinstance(other, (int, float, Fraction)):
            return self._value > Time(other)._value
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        return self > other or self == other

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
                if "seconds" in val:
                    return Time.from_seconds(val["seconds"])
                if "numerator" in val and "denominator" in val:
                    return Time(Fraction(val["numerator"], val["denominator"]))
            raise InvalidTimeError(f"Cannot convert {val!r} to Time")

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
                lambda t: round(t.seconds, 6),
                return_schema=core_schema.float_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {
            "type": "number",
            "description": (
                "Duration or timestamp in seconds (can also be SMPTE timecode string e.g. '00:00:05:15')"
            ),
        }
