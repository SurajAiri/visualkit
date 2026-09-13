from typing import Literal

from pydantic import Field

from .base import Source
from .visual import VisualClip


class MediaClip(VisualClip):
    """Represents a media clip (video or image) placed on a track"""

    clip_type: Literal["media"] = "media"

    # properties specific to media clips
    source: Source = Field(..., description="Reference to the asset or media source for the clip")
    fps: float = Field(default=30.0, gt=0.0, description="Frames per second of the media clip")
    resolution: tuple[int, int] = Field(
        default=(1920, 1080), description="Resolution of the media clip (width, height)"
    )
