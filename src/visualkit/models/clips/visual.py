from enum import Enum
from typing import Literal

from pydantic import Field

from visualkit.utils.base_model import VisualKitModel

from .base import BaseClip, Position, Size


# todo: add keyframes on all these
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
        ge=0.0,
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
        ge=0.0,
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


class VisualClip(BaseClip):
    """Base Class for all visual clips placed on a track"""

    transform: Transform = Field(
        default_factory=Transform, description="Transform properties of the visual clip"
    )
