import uuid
from abc import ABC, abstractmethod
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from visualkit.utils.time import Time


class Position(BaseModel):
    x: float = Field(default=0.0, description="X coordinate of the position")
    y: float = Field(default=0.0, description="Y coordinate of the position")


class Size(BaseModel):
    width: float = Field(default=0.0, description="Width of the size")
    height: float = Field(default=0.0, description="Height of the size")


class Source(BaseModel):
    """Represents a media source for a clip."""

    source: str = Field(..., description="Reference to the asset or media source for the clip")
    start: Time = Field(default=Time.zero(), description="Start time of the clip in the source media")


# todo: separate input variable properties
class BaseClip(BaseModel, ABC):
    """Base Class for all media & visual clips placed on a track"""

    id: str = Field(
        default_factory=lambda: f"clip_{uuid.uuid4().hex[:8]}", description="Unique identifier for the clip"
    )

    # changable properties
    timeline_start: Time = Field(default=Time.zero(), description="Start time of the clip on the timeline")
    duration: Time = Field(default=Time.zero(), description="Duration of the clip")
    speed: float = Field(default=1.0, ge=0.0, description="Playback speed of the clip")
