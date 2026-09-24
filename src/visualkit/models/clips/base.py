import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.time import Time


class Position(VisualKitModel):
    """Offset of a visual clip's transform, in pixels of the *target* canvas
    (the exporter's `resolution` for MediaClip/TextClip, or the compositing
    canvas a CompoundClip is flattened into). (0, 0) is the top-left corner
    of the canvas; positive x is right, positive y is down. This is an
    offset applied on top of the clip's default placement (see `Size` for
    what that default is), not an absolute placement of the clip's
    top-left corner.
    """

    x: float = Field(default=0.0, description="Horizontal offset in target-canvas pixels from center")
    y: float = Field(default=0.0, description="Vertical offset in target-canvas pixels from center")

    #: The 9 standard screen anchors `from_anchor` accepts, mapped to the
    #: (horizontal, vertical) direction each pushes away from center.
    _ANCHORS: ClassVar[dict[str, tuple[float, float]]] = {
        "center": (0, 0),
        "top": (0, -1),
        "bottom": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
        "top-left": (-1, -1),
        "top-right": (1, -1),
        "bottom-left": (-1, 1),
        "bottom-right": (1, 1),
    }

    @classmethod
    def from_anchor(
        cls, anchor: str, margin: float = 0.0, *, canvas_size: tuple[float, float] = (1920.0, 1080.0)
    ) -> "Position":
        """Build a `Position` for one of the 9 standard screen anchors
        (`"center"`, `"top"`, `"bottom"`, `"left"`, `"right"`,
        `"top-left"`, `"top-right"`, `"bottom-left"`, `"bottom-right"`),
        `margin` pixels in from that edge (ignored for `"center"`).

        Replaces manually computing e.g. `Position(y=canvas_height/2 - 80)`
        to hit "80px above the bottom edge." `canvas_size` defaults to
        VisualKit's standard 1920x1080 export resolution -- pass your real
        target size explicitly if you're exporting to something else, the
        same way you would with any other target-canvas-pixel value (see
        the class docstring); the result is only correct for the
        `canvas_size` it was computed against, it does not auto-rescale if
        you later export at a different resolution.
        """
        key = anchor.strip().lower()
        try:
            dx, dy = cls._ANCHORS[key]
        except KeyError:
            raise ValueError(
                f"Unrecognized anchor {anchor!r}. Expected one of: {', '.join(sorted(cls._ANCHORS))}."
            ) from None
        width, height = canvas_size
        return cls(x=dx * (width / 2 - margin), y=dy * (height / 2 - margin))


class Size(VisualKitModel):
    """Explicit width/height for a visual clip's transform, in pixels of the
    target canvas (see `Position`). (0, 0) -- the default -- is not a
    zero-size clip; it means "no explicit size requested", so the exporter
    falls back to the clip's natural size scaled to fit the canvas
    (preserving aspect ratio) before any `Transform.scale`/`zoom` is
    applied. Set both width and height to request an explicit target size
    instead of the fit-to-canvas default.
    """

    width: float = Field(
        default=0.0, ge=0.0, description="Explicit target width in pixels (0 = fit to canvas)"
    )
    height: float = Field(
        default=0.0, ge=0.0, description="Explicit target height in pixels (0 = fit to canvas)"
    )


class Source(VisualKitModel):
    """Represents a media source for a clip."""

    source: str = Field(..., min_length=1, description="Reference to the asset or media source for the clip")
    start: Time = Field(default_factory=Time.zero, description="Start time of the clip in the source media")

    @model_validator(mode="wrap")
    @classmethod
    def _validate_source(cls, v: Any, handler: Any) -> Any:
        if isinstance(v, (str, Path)):
            return cls(source=str(v))
        return handler(v)


# todo: separate input variable properties
class BaseClip(VisualKitModel, ABC):
    """Base Class for all media & visual clips placed on a track"""

    id: str = Field(
        default_factory=lambda: f"clip_{uuid.uuid4().hex[:8]}",
        min_length=1,
        description="Unique identifier for the clip",
    )

    # changable properties
    timeline_start: Time = Field(
        default_factory=Time.zero, description="Start time of the clip on the timeline"
    )
    duration: Time = Field(default_factory=Time.zero, description="Duration of the clip")
    speed: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Playback speed of the clip. Must be strictly positive: a "
            "speed of 0 would mean the clip occupies timeline duration "
            "while consuming zero seconds of source/inner-timeline "
            "content, which both `flatten()` (dividing duration by "
            "speed) and `split_clip`/`trim_in` (dividing a source-time "
            "delta by speed) treat as an undefined, divide-by-zero "
            "operation rather than a valid freeze-frame -- there is no "
            "consistent way to reverse-scale a delta through speed=0. "
            "Reverse playback is not currently supported either (negative "
            "speed is rejected the same way)."
        ),
    )
