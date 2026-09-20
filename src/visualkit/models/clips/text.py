import re
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from visualkit.utils.base_model import VisualKitModel

from .visual import VisualClip

_NAMED_WEIGHTS = frozenset({"normal", "bold", "lighter", "bolder"})


# Text Clip
class TextAlignment(str, Enum):
    """Text alignment options."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


#: Text is authored against a 1080-pixel-tall reference frame: ``font_size=48``
#: means 48px on a 1920x1080 frame. Exporters scale it by ``frame_height /
#: TEXT_REFERENCE_HEIGHT`` so a clip occupies the same *fraction* of the frame at
#: any export resolution (a 360p preview matches the 1080p final render).
TEXT_REFERENCE_HEIGHT = 1080


class TextStyle(VisualKitModel):
    """Typography and styling options for text clips.

    `font_size` is in pixels of a 1080p reference frame (see
    `TEXT_REFERENCE_HEIGHT`), not of whatever resolution is exported.
    """

    alignment: TextAlignment = Field(default=TextAlignment.CENTER, description="Text alignment")
    font_family: str = Field(default="Inter", min_length=1, description="Font family name")

    # todo: later keyframe these properties for animated text effects
    font_size: int = Field(default=48, gt=0, description="Font size in pixels of a 1080p reference frame")
    color: str = Field(default="#FFFFFF", description="Hex or CSS color string for text")
    background_color: str | None = Field(default=None, description="Optional background highlight color")
    weight: str = Field(default="bold", description="Font weight (e.g. normal, bold, 100-900)")

    @field_validator("color", "background_color")
    @classmethod
    def _validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from visualkit.models.variable import VariableType, coerce_variable_value

        return coerce_variable_value(VariableType.COLOR, value, name="color")

    @field_validator("weight")
    @classmethod
    def _validate_weight(cls, value: str) -> str:
        text = str(value).strip().lower()
        if text in _NAMED_WEIGHTS or (text.isdigit() and 1 <= int(text) <= 1000):
            return text
        raise ValueError(
            f"font weight must be one of {sorted(_NAMED_WEIGHTS)} or a number 1-1000, got {value!r}"
        )

    @field_validator("font_family")
    @classmethod
    def _validate_font_family(cls, value: str) -> str:
        if re.search(r"[<>{};\\]", value):
            raise ValueError(f"font_family contains illegal characters: {value!r}")
        return value.strip()

    @property
    def is_bold(self) -> bool:
        return self.weight in ("bold", "bolder") or (self.weight.isdigit() and int(self.weight) >= 600)


class TextClip(VisualClip):
    """Represents a text clip placed on a track"""

    clip_type: Literal["text"] = Field(default="text", frozen=True, description="Type of the clip (text)")

    # properties specific to text clips
    text: str = Field(
        ..., description="Content of the text clip"
    )  # todo: later keyframe this property for animated text effects

    style: TextStyle = Field(
        default_factory=TextStyle, description="Typography and styling options for the text clip"
    )
