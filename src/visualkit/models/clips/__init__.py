from typing import Annotated, Union

from pydantic import Field

from .audio import AudioClip, AudioProperties
from .base import BaseClip, Position, Size, Source
from .coded_visual import CodedVisualClip, CompileStatus
from .media import MediaClip
from .text import TextClip, TextStyle
from .visual import Transform, VisualClip

Clip = Annotated[Union[AudioClip, TextClip, MediaClip, CodedVisualClip], Field(discriminator="clip_type")]

__all__ = [
    "AudioClip",
    "AudioProperties",
    "BaseClip",
    "CodedVisualClip",
    "CompileStatus",
    "MediaClip",
    "Position",
    "Size",
    "Source",
    "TextClip",
    "TextStyle",
    "Transform",
    "VisualClip",
    "Clip",
]
