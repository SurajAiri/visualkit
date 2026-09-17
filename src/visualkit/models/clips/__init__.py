from typing import Annotated, Union

from pydantic import Field

from .audio import AudioClip, AudioProperties
from .base import BaseClip, Position, Size, Source
from .coded_visual import CodedVisualClip, CompileStatus
from .compound import CompoundAudioClip, CompoundClip, ExposedParameter
from .media import MediaClip
from .text import TextClip, TextStyle
from .visual import Transform, VisualClip

VisualContent = Annotated[
    Union[MediaClip, CodedVisualClip, TextClip, CompoundClip],
    Field(discriminator="clip_type"),
]
AudioContent = Annotated[Union[AudioClip, CompoundAudioClip], Field(discriminator="clip_type")]  # noqa: F821
Clip = Annotated[
    Union[MediaClip, CodedVisualClip, TextClip, CompoundClip, AudioClip, CompoundAudioClip],
    Field(discriminator="clip_type"),
]

__all__ = [
    "AudioClip",
    "AudioProperties",
    "BaseClip",
    "CodedVisualClip",
    "CompileStatus",
    "ExposedParameter",
    "MediaClip",
    "Position",
    "Size",
    "Source",
    "TextClip",
    "TextStyle",
    "Transform",
    "VisualClip",
    "CompoundClip",
    "CompoundAudioClip",
    "Clip",
    "VisualContent",
    "AudioContent",
]
