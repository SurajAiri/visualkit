from visualkit.models.animation import AnimationPreset, ClipAnimation
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
    LintIssue,
    MediaClip,
    Position,
    RenderMode,
    Size,
    Source,
    TextClip,
    TextGradient,
    TextStyle,
    Transform,
    VisualClip,
    VisualContent,
)
from visualkit.models.effects import MASK_PROPERTIES, ChromaKey, Mask, color_to_rgb
from visualkit.models.keyframes import (
    KEYFRAMEABLE_PROPERTIES,
    CurveSpec,
    Easing,
    Keyframe,
    PropertyCurve,
)
from visualkit.models.timeline import (
    AddClipResult,
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
    "TextGradient",
    "CodedVisualClip",
    "CompileStatus",
    "RenderMode",
    "LintIssue",
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
    "AddClipResult",
    "Variable",
    "VariableType",
    "ExposedParameter",
    "AnimationPreset",
    "ClipAnimation",
    "ChromaKey",
    "Mask",
    "MASK_PROPERTIES",
    "color_to_rgb",
    "Easing",
    "Keyframe",
    "PropertyCurve",
    "CurveSpec",
    "KEYFRAMEABLE_PROPERTIES",
]
