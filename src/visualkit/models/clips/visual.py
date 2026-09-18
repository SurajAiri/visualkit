from enum import Enum
from typing import Literal

from pydantic import Field

from visualkit.utils.base_model import VisualKitModel

from .base import BaseClip, Position, Size


# todo: add keyframes on all these
class Transform(VisualKitModel):
    position: Position = Field(default_factory=Position, description="Position of the transform")
    size: Size = Field(default_factory=Size, description="Size of the transform")
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
    scale: float = Field(default=1.0, ge=0.0, le=100.0, description="Scale of the transform")
    zoom: float = Field(default=1.0, ge=0.0, le=100.0, description="Zoom of the transform")
    opacity: int = Field(default=100, ge=0, le=100, description="Opacity of the transform (0-100)")


class VisualClip(BaseClip):
    """Base Class for all visual clips placed on a track"""

    transform: Transform = Field(
        default_factory=Transform, description="Transform properties of the visual clip"
    )
