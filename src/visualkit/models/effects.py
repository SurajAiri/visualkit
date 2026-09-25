"""Per-clip effects that are not animated transforms: chroma key and masks.

Both are plain data (validated, JSON-serialisable). `visualkit.exporters._render_plan`
turns them into ffmpeg filters; nothing here knows about ffmpeg beyond formatting a colour.
The DaVinci Resolve export ignores both.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator

from visualkit.utils.base_model import VisualKitModel

#: The 148 CSS named colours as 0xRRGGBB (generated from the CSS Color 4 keyword table).
_NAMED_COLORS: dict[str, int] = {
    "aliceblue": 0xF0F8FF,
    "antiquewhite": 0xFAEBD7,
    "aqua": 0x00FFFF,
    "aquamarine": 0x7FFFD4,
    "azure": 0xF0FFFF,
    "beige": 0xF5F5DC,
    "bisque": 0xFFE4C4,
    "black": 0x000000,
    "blanchedalmond": 0xFFEBCD,
    "blue": 0x0000FF,
    "blueviolet": 0x8A2BE2,
    "brown": 0xA52A2A,
    "burlywood": 0xDEB887,
    "cadetblue": 0x5F9EA0,
    "chartreuse": 0x7FFF00,
    "chocolate": 0xD2691E,
    "coral": 0xFF7F50,
    "cornflowerblue": 0x6495ED,
    "cornsilk": 0xFFF8DC,
    "crimson": 0xDC143C,
    "cyan": 0x00FFFF,
    "darkblue": 0x00008B,
    "darkcyan": 0x008B8B,
    "darkgoldenrod": 0xB8860B,
    "darkgray": 0xA9A9A9,
    "darkgreen": 0x006400,
    "darkgrey": 0xA9A9A9,
    "darkkhaki": 0xBDB76B,
    "darkmagenta": 0x8B008B,
    "darkolivegreen": 0x556B2F,
    "darkorange": 0xFF8C00,
    "darkorchid": 0x9932CC,
    "darkred": 0x8B0000,
    "darksalmon": 0xE9967A,
    "darkseagreen": 0x8FBC8F,
    "darkslateblue": 0x483D8B,
    "darkslategray": 0x2F4F4F,
    "darkslategrey": 0x2F4F4F,
    "darkturquoise": 0x00CED1,
    "darkviolet": 0x9400D3,
    "deeppink": 0xFF1493,
    "deepskyblue": 0x00BFFF,
    "dimgray": 0x696969,
    "dimgrey": 0x696969,
    "dodgerblue": 0x1E90FF,
    "firebrick": 0xB22222,
    "floralwhite": 0xFFFAF0,
    "forestgreen": 0x228B22,
    "fuchsia": 0xFF00FF,
    "gainsboro": 0xDCDCDC,
    "ghostwhite": 0xF8F8FF,
    "gold": 0xFFD700,
    "goldenrod": 0xDAA520,
    "gray": 0x808080,
    "green": 0x008000,
    "greenyellow": 0xADFF2F,
    "grey": 0x808080,
    "honeydew": 0xF0FFF0,
    "hotpink": 0xFF69B4,
    "indianred": 0xCD5C5C,
    "indigo": 0x4B0082,
    "ivory": 0xFFFFF0,
    "khaki": 0xF0E68C,
    "lavender": 0xE6E6FA,
    "lavenderblush": 0xFFF0F5,
    "lawngreen": 0x7CFC00,
    "lemonchiffon": 0xFFFACD,
    "lightblue": 0xADD8E6,
    "lightcoral": 0xF08080,
    "lightcyan": 0xE0FFFF,
    "lightgoldenrodyellow": 0xFAFAD2,
    "lightgray": 0xD3D3D3,
    "lightgreen": 0x90EE90,
    "lightgrey": 0xD3D3D3,
    "lightpink": 0xFFB6C1,
    "lightsalmon": 0xFFA07A,
    "lightseagreen": 0x20B2AA,
    "lightskyblue": 0x87CEFA,
    "lightslategray": 0x778899,
    "lightslategrey": 0x778899,
    "lightsteelblue": 0xB0C4DE,
    "lightyellow": 0xFFFFE0,
    "lime": 0x00FF00,
    "limegreen": 0x32CD32,
    "linen": 0xFAF0E6,
    "magenta": 0xFF00FF,
    "maroon": 0x800000,
    "mediumaquamarine": 0x66CDAA,
    "mediumblue": 0x0000CD,
    "mediumorchid": 0xBA55D3,
    "mediumpurple": 0x9370DB,
    "mediumseagreen": 0x3CB371,
    "mediumslateblue": 0x7B68EE,
    "mediumspringgreen": 0x00FA9A,
    "mediumturquoise": 0x48D1CC,
    "mediumvioletred": 0xC71585,
    "midnightblue": 0x191970,
    "mintcream": 0xF5FFFA,
    "mistyrose": 0xFFE4E1,
    "moccasin": 0xFFE4B5,
    "navajowhite": 0xFFDEAD,
    "navy": 0x000080,
    "oldlace": 0xFDF5E6,
    "olive": 0x808000,
    "olivedrab": 0x6B8E23,
    "orange": 0xFFA500,
    "orangered": 0xFF4500,
    "orchid": 0xDA70D6,
    "palegoldenrod": 0xEEE8AA,
    "palegreen": 0x98FB98,
    "paleturquoise": 0xAFEEEE,
    "palevioletred": 0xDB7093,
    "papayawhip": 0xFFEFD5,
    "peachpuff": 0xFFDAB9,
    "peru": 0xCD853F,
    "pink": 0xFFC0CB,
    "plum": 0xDDA0DD,
    "powderblue": 0xB0E0E6,
    "purple": 0x800080,
    "rebeccapurple": 0x663399,
    "red": 0xFF0000,
    "rosybrown": 0xBC8F8F,
    "royalblue": 0x4169E1,
    "saddlebrown": 0x8B4513,
    "salmon": 0xFA8072,
    "sandybrown": 0xF4A460,
    "seagreen": 0x2E8B57,
    "seashell": 0xFFF5EE,
    "sienna": 0xA0522D,
    "silver": 0xC0C0C0,
    "skyblue": 0x87CEEB,
    "slateblue": 0x6A5ACD,
    "slategray": 0x708090,
    "slategrey": 0x708090,
    "snow": 0xFFFAFA,
    "springgreen": 0x00FF7F,
    "steelblue": 0x4682B4,
    "tan": 0xD2B48C,
    "teal": 0x008080,
    "thistle": 0xD8BFD8,
    "tomato": 0xFF6347,
    "turquoise": 0x40E0D0,
    "violet": 0xEE82EE,
    "wheat": 0xF5DEB3,
    "white": 0xFFFFFF,
    "whitesmoke": 0xF5F5F5,
    "yellow": 0xFFFF00,
    "yellowgreen": 0x9ACD32,
}


_HEX = re.compile(r"^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_FUNC = re.compile(
    r"^rgba?\(\s*(\d{1,3}(?:\.\d+)?%?)\s*[, ]\s*(\d{1,3}(?:\.\d+)?%?)\s*[, ]\s*(\d{1,3}(?:\.\d+)?%?)"
    r"\s*(?:[,/]\s*[0-9.]+%?\s*)?\)$"
)


def color_to_rgb(value: str) -> int:
    """A CSS colour as ``0xRRGGBB`` (alpha, if any, is dropped).

    Accepts ``#rgb``/``#rgba``/``#rrggbb``/``#rrggbbaa``, ``rgb()``/``rgba()`` and the CSS
    named colours. Anything else (``hsl()``, ``oklch()``, an unknown name) raises `ValueError`:
    a key colour has to be an exact RGB value, so guessing is worse than refusing.
    """
    from visualkit.models.variable import VariableType, coerce_variable_value

    text = coerce_variable_value(VariableType.COLOR, value, name="color")
    if (m := _HEX.match(text)) is not None:
        digits = m.group(1)
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits[:3])
        return int(digits[:6], 16)
    if (m := _RGB_FUNC.match(text)) is not None:
        channels = []
        for part in m.groups():
            n = float(part[:-1]) * 2.55 if part.endswith("%") else float(part)
            if not 0 <= n <= 255.5:
                raise ValueError(f"colour channel out of range in {value!r}")
            channels.append(min(255, round(n)))
        return (channels[0] << 16) | (channels[1] << 8) | channels[2]
    named = _NAMED_COLORS.get(text.lower())
    if named is not None:
        return named
    raise ValueError(
        f"{value!r} cannot be used as a key colour: use #rrggbb, rgb(r, g, b) or a CSS colour name"
    )


class ChromaKey(VisualKitModel):
    """Make one colour (a green/blue screen) transparent.

    The key is the *first* stage applied to the clip, before it is fitted, zoomed, scaled or
    rotated, so resampling never blends the key colour into the edges. Parameters are static.

    * ``method="chromakey"`` compares colour in YUV (best for green/blue screens);
      ``"colorkey"`` compares in RGB (for other colours).
    * ``similarity`` is how far from `color` a pixel may be and still be keyed out;
      ``blend`` softens the edge of that range (0 = hard).
    * ``despill`` removes the green (or blue) fringe the screen leaves on the subject.
    """

    color: str = Field(default="#00B140", description="The colour to remove (#rrggbb, rgb() or a CSS name)")
    similarity: float = Field(
        default=0.15, ge=0.01, le=1.0, description="How close a pixel must be to the colour"
    )
    blend: float = Field(default=0.05, ge=0.0, le=1.0, description="Softness of the key edge")
    despill: bool = Field(default=False, description="Suppress colour spill on the subject")
    despill_type: Literal["green", "blue"] = Field(default="green", description="Which spill to remove")
    method: Literal["chromakey", "colorkey"] = Field(default="chromakey", description="Colour distance model")

    @field_validator("color")
    @classmethod
    def _validate_color(cls, value: str) -> str:
        return f"#{color_to_rgb(value):06X}"

    @property
    def ffmpeg_color(self) -> str:
        """The key colour as ffmpeg spells it: ``0xRRGGBB``."""
        return f"0x{color_to_rgb(self.color):06X}"


class Mask(VisualKitModel):
    """Show only part of a clip: a rectangle or ellipse.

    Geometry is normalised to the clip's own frame (0-1), so it survives a change of export
    resolution and follows the clip when it is scaled, rotated or moved. ``x``/``y`` is the
    centre. ``feather`` is the width of the soft edge as a fraction of the frame's shorter
    side, centred on the shape's outline; 0 is a crisp edge. ``invert`` shows everything
    *outside* the shape instead.

    ``x``, ``y``, ``width``, ``height`` and ``feather`` can be animated with clip keyframes
    named ``mask.x``, ``mask.y``, ``mask.width``, ``mask.height`` and ``mask.feather``.
    """

    shape: Literal["rect", "ellipse"] = "rect"
    x: float = Field(default=0.5, ge=0.0, le=1.0, description="Centre x, 0 (left) to 1 (right)")
    y: float = Field(default=0.5, ge=0.0, le=1.0, description="Centre y, 0 (top) to 1 (bottom)")
    width: float = Field(default=0.5, ge=0.0, le=1.0, description="Width as a fraction of the frame")
    height: float = Field(default=0.5, ge=0.0, le=1.0, description="Height as a fraction of the frame")
    feather: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Soft-edge width (fraction of the short side)"
    )
    invert: bool = False


#: Keyframe names that belong to the mask rather than to `Transform`.
MASK_PROPERTIES = ("mask.x", "mask.y", "mask.width", "mask.height", "mask.feather")
