from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from .visual import VisualClip


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

    @property
    def clip_type(self) -> str:
        return "text"

    # properties specific to text clips
    text: str = Field(
        ..., description="Content of the text clip"
    )  # todo: later keyframe this property for animated text effects

    style: TextStyle = Field(
        default_factory=TextStyle, description="Typography and styling options for the text clip"
    )
