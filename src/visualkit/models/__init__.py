from visualkit.models.clips import (
    AudioClip,
    AudioContent,
    BaseClip,
    Clip,
    CodedVisualClip,
    CompoundAudioClip,
    CompoundClip,
    MediaClip,
    Position,
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
    "AudioClip",
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
]
