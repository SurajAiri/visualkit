from visualkit.models.clips import (
    AudioClip,
    AudioContent,
    AudioProperties,
    BaseClip,
    Clip,
    CodedVisualClip,
    CompileStatus,
    CompoundAudioClip,
    CompoundClip,
    ExposedParameter,
    MediaClip,
    Position,
    RenderMode,
    Size,
    Source,
    TextClip,
    TextStyle,
    Transform,
    VisualClip,
    VisualContent,
)
from visualkit.models.timeline import (
    AudioTrack,
    InsertMode,
    Timeline,
    Track,
    TrackKind,
    VideoTrack,
)
from visualkit.models.variable import (
    Variable,
    VariableType,
)

# Rebuild models so Pydantic resolves 'Timeline' in CompoundClip
CompoundClip.model_rebuild(_types_namespace={"Timeline": Timeline})
Track.model_rebuild()
VideoTrack.model_rebuild()
AudioTrack.model_rebuild()
Timeline.model_rebuild()

__all__ = [
    "BaseClip",
    "Position",
    "Size",
    "Source",
    "Transform",
    "VisualClip",
    "MediaClip",
    "TextClip",
    "TextStyle",
    "CodedVisualClip",
    "CompileStatus",
    "RenderMode",
    "AudioClip",
    "AudioProperties",
    "CompoundClip",
    "CompoundAudioClip",
    "Clip",
    "VisualContent",
    "AudioContent",
    "Track",
    "VideoTrack",
    "AudioTrack",
    "TrackKind",
    "Timeline",
    "InsertMode",
    "Variable",
    "VariableType",
    "ExposedParameter",
]
