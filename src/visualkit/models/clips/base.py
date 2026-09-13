import uuid
from abc import ABC, abstractmethod
from enum import Enum
from typing import Literal

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
    source_start: Time = Field(default=Time.zero(), description="Start time of the clip in the source media")


class BaseClip(BaseModel, ABC):
    """Base Class for all media & visual clips placed on a track"""

    id: str = Field(
        default_factory=lambda: f"clip_{uuid.uuid4().hex[:8]}", description="Unique identifier for the clip"
    )
    clip_type: str

    # changable properties
    start: Time = Field(default=Time.zero(), description="Start time of the clip on the timeline")
    duration: Time = Field(default=Time.zero(), description="Duration of the clip")
    speed: float = Field(default=1.0, ge=0.0, description="Playback speed of the clip")


# Visual Clip


class Transform(BaseModel):
    position: Position = Field(default_factory=Position, description="Position of the transform")
    size: Size = Field(default_factory=Size, description="Size of the transform")
    rotation: float = Field(default=0.0, ge=0.0, le=360.0, description="Rotation of the transform in degrees")
    scale: float = Field(default=1.0, ge=0.0, le=100.0, description="Scale of the transform")
    zoom: float = Field(default=1.0, ge=0.0, le=100.0, description="Zoom of the transform")
    opacity: int = Field(default=100, ge=0, le=100, description="Opacity of the transform (0-100)")


class VisualClip(BaseClip, ABC):
    """Base Class for all visual clips placed on a track"""

    clip_type: Literal["media", "text", "coded_visual"]

    transform: Transform = Field(
        default_factory=Transform, description="Transform properties of the visual clip"
    )


class MediaClip(VisualClip):
    """Represents a media clip (video or image) placed on a track"""

    clip_type: Literal["media"] = "media"

    # properties specific to media clips
    source: Source = Field(..., description="Reference to the asset or media source for the clip")
    fps: float = Field(default=30.0, gt=0.0, description="Frames per second of the media clip")
    resolution: tuple[int, int] = Field(
        default=(1920, 1080), description="Resolution of the media clip (width, height)"
    )


# Text Clip
class TextAlignment(str, Enum):
    """Text alignment options."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class TextStyle(BaseModel):
    """Typography and styling options for text clips."""

    alignment: TextAlignment = Field(default=TextAlignment.CENTER, description="Text alignment")
    font_family: str = Field(default="Inter", description="Font family name")

    # todo: later keyframe these properties for animated text effects
    font_size: int = Field(default=48, gt=0, description="Font size in points/pixels")
    color: str = Field(default="#FFFFFF", description="Hex or CSS color string for text")
    background_color: str | None = Field(default=None, description="Optional background highlight color")
    weight: str = Field(default="bold", description="Font weight (e.g. normal, bold, 700)")


class TextClip(VisualClip):
    """Represents a text clip placed on a track"""

    clip_type: Literal["text"] = "text"

    # properties specific to text clips
    text: str = Field(
        ..., description="Content of the text clip"
    )  # todo: later keyframe this property for animated text effects

    style: TextStyle = Field(
        default_factory=TextStyle, description="Typography and styling options for the text clip"
    )


# audio clip
class AudioProperties(BaseModel):
    volume: float = Field(default=1.0, ge=0.0, le=1.0, description="Volume level (0.0 to 1.0)")
    muted: bool = Field(default=False, description="Whether the audio is muted")


class AudioClip(BaseClip):
    """Represents an audio clip placed on a track"""

    clip_type: Literal["audio"] = "audio"

    # properties specific to audio clips
    source: Source = Field(..., description="Reference to the asset or media source for the clip")

    audio_properties: AudioProperties = Field(
        default_factory=AudioProperties, description="Audio properties for the audio clip"
    )
