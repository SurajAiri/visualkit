import re
from enum import Enum
from pathlib import Path
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


def _validated_color(value: str | None) -> str | None:
    """A CSS colour string checked by the same rules as a colour variable (``None`` passes)."""
    if value is None:
        return value
    from visualkit.models.variable import VariableType, coerce_variable_value

    return coerce_variable_value(VariableType.COLOR, value, name="color")


class TextGradient(VisualKitModel):
    """A two-stop linear gradient used as the text fill.

    `angle` follows CSS ``linear-gradient``: 0 runs bottom-to-top, 90 left-to-right, 180
    (the default) top-to-bottom. The gradient spans the text block, not the whole frame.
    """

    start_color: str = Field(description="Colour at the start of the gradient")
    end_color: str = Field(description="Colour at the end of the gradient")
    angle: float = Field(default=180.0, ge=-360.0, le=360.0, description="CSS gradient angle in degrees")

    @field_validator("start_color", "end_color")
    @classmethod
    def _validate_colors(cls, value: str) -> str:
        return _validated_color(value)  # type: ignore[return-value]


class TextStyle(VisualKitModel):
    """Typography and styling options for text clips.

    `font_size` is in pixels of a 1080p reference frame (see
    `TEXT_REFERENCE_HEIGHT`), not of whatever resolution is exported. Every other
    length here (`stroke_width`, `shadow_*`, `letter_spacing`) is in the same reference
    pixels and scales with the export resolution the same way.

    The DaVinci Resolve export ignores the outline, shadow, spacing and gradient fields;
    they only affect the FFmpeg exporter and previews.
    """

    alignment: TextAlignment = Field(default=TextAlignment.CENTER, description="Text alignment")
    font_family: str = Field(default="Inter", min_length=1, description="Font family name")

    # todo: later keyframe these properties for animated text effects
    font_size: int = Field(default=48, gt=0, description="Font size in pixels of a 1080p reference frame")
    color: str = Field(default="#FFFFFF", description="Hex or CSS color string for text")
    background_color: str | None = Field(default=None, description="Optional background highlight color")
    weight: str = Field(default="bold", description="Font weight (e.g. normal, bold, 100-900)")

    # --- outline -------------------------------------------------------------------------
    stroke_width: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Outline thickness outside the glyphs (0 = none)"
    )
    stroke_color: str = Field(default="#000000", description="Outline colour")

    # --- drop shadow ---------------------------------------------------------------------
    shadow_color: str | None = Field(default=None, description="Shadow colour; None means no shadow")
    shadow_offset_x: float = Field(default=0.0, ge=-500.0, le=500.0, description="Shadow x offset")
    shadow_offset_y: float = Field(default=0.0, ge=-500.0, le=500.0, description="Shadow y offset")
    shadow_blur: float = Field(default=0.0, ge=0.0, le=200.0, description="Shadow blur radius")

    # --- spacing and fill ----------------------------------------------------------------
    letter_spacing: float = Field(default=0.0, ge=-20.0, le=100.0, description="Extra space between letters")
    line_height: float = Field(
        default=1.2, gt=0.0, le=10.0, description="Line height as a multiple of font size"
    )
    gradient: TextGradient | None = Field(default=None, description="Gradient fill instead of a flat colour")

    @field_validator("color", "background_color", "stroke_color", "shadow_color")
    @classmethod
    def _validate_color(cls, value: str | None) -> str | None:
        return _validated_color(value)

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

    def preview_image(
        self,
        *,
        resolution: tuple[int, int] | None = None,
        cache_dir: "str | Path | None" = None,
    ) -> Path:
        """Render this clip to a transparent PNG and return its path.

        Uses the same Chrome-based rasterizer `FFmpegVideoExporter` uses to
        turn a `TextClip` into an image for export, so what you see here is
        exactly what export will draw for this clip's own text/style -- not
        how it looks composited over whatever's beneath it on a timeline.
        `resolution` defaults to a 1920x1080 canvas (`font_size` is defined
        against a fixed 1080p reference height regardless of canvas size,
        see `TEXT_REFERENCE_HEIGHT`, so this only changes overall pixel
        density, not the text's proportions). `cache_dir` defaults to the
        exporter's own rendered-text cache, so previewing a clip and then
        exporting it don't render it twice.
        """
        from visualkit.exporters.single_clip import preview_text_image

        return preview_text_image(self, resolution=resolution, cache_dir=cache_dir)
