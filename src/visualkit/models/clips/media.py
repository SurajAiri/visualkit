from typing import Literal

from pydantic import Field

from .audio import AudioProperties
from .base import Source
from .visual import VisualClip


class MediaClip(VisualClip):
    """Represents a media clip (video or image) placed on a track"""

    clip_type: Literal["media"] = Field(default="media", frozen=True, description="Type of the clip (media)")

    # properties specific to media clips
    source: Source = Field(..., description="Reference to the asset or media source for the clip")
    fps: float = Field(default=30.0, gt=0.0, description="Frames per second of the media clip")
    resolution: tuple[int, int] = Field(
        default=(1920, 1080), description="Resolution of the media clip (width, height)"
    )

    # Whether/how to include this clip's own embedded audio stream (e.g. a
    # video file's soundtrack) in exports, distinct from any separate
    # AudioClip placed on an audio track. Defaults to including it at full
    # volume, matching what a person would expect from dropping a video
    # with sound onto a track. For an image (no embedded audio), exporters
    # simply find no audio stream to map and this field has no effect.
    source_audio: AudioProperties = Field(
        default_factory=AudioProperties,
        description="Volume/mute controls for this clip's own embedded audio stream, if it has one",
    )

    linked_clip_id: str | None = Field(
        default=None, description="Optional ID of a linked clip (e.g., for split clips or related media)"
    )  # todo: add validation to ensure linked clip exists in the same track or project, and that it is of a compatible type (e.g., media clip) # noqa: E501
