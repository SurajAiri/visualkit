# audio clip
from typing import Literal

from pydantic import Field

from visualkit.utils.base_model import VisualKitModel

from .base import BaseClip, Source


class AudioProperties(VisualKitModel):
    volume: float = Field(default=1.0, ge=0.0, le=1.0, description="Volume level (0.0 to 1.0)")
    muted: bool = Field(default=False, description="Whether the audio is muted")


class AudioClip(BaseClip):
    """Represents an audio clip placed on a track"""

    clip_type: Literal["audio"] = Field(default="audio", frozen=True, description="Type of the clip (audio)")

    # properties specific to audio clips
    source: Source = Field(..., description="Reference to the asset or media source for the clip")

    audio_properties: AudioProperties = Field(
        default_factory=AudioProperties, description="Audio properties for the audio clip"
    )

    linked_clip_id: str | None = Field(
        default=None, description="Optional ID of a linked clip (e.g., for split clips or related media)"
    )  # todo: add validation to ensure linked clip exists in the same track or project, and that it is of a compatible type (e.g., media clip) #noqa: E501
