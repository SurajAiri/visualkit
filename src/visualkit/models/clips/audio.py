# audio clip
from typing import Literal

from pydantic import BaseModel, Field

from .base import BaseClip, Source


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
