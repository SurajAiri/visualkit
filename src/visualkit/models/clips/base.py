import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.time import Time


class Position(VisualKitModel):
    x: float = Field(default=0.0, description="X coordinate of the position")
    y: float = Field(default=0.0, description="Y coordinate of the position")


class Size(VisualKitModel):
    width: float = Field(default=0.0, description="Width of the size")
    height: float = Field(default=0.0, description="Height of the size")


class Source(VisualKitModel):
    """Represents a media source for a clip."""

    source: str = Field(..., description="Reference to the asset or media source for the clip")
    start: Time = Field(default=Time.zero(), description="Start time of the clip in the source media")

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
        default_factory=lambda: f"clip_{uuid.uuid4().hex[:8]}", description="Unique identifier for the clip"
    )

    # changable properties
    timeline_start: Time = Field(default=Time.zero(), description="Start time of the clip on the timeline")
    duration: Time = Field(default=Time.zero(), description="Duration of the clip")
    speed: float = Field(default=1.0, ge=0.0, description="Playback speed of the clip")
