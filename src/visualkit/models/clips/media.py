from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from visualkit.utils.time import Time

from .audio import AudioProperties
from .base import Source
from .visual import VisualClip


class MediaClip(VisualClip):
    """Represents a media clip (video or image) placed on a track"""

    clip_type: Literal["media"] = Field(default="media", frozen=True, description="Type of the clip (media)")

    # properties specific to media clips
    source: Source = Field(..., description="Reference to the asset or media source for the clip")
    fps: float = Field(default=30.0, gt=0.0, description="Frames per second of the media clip")
    resolution: tuple[int, int] = Field(
        default=(1920, 1080), description="Resolution of the media clip (width, height)"
    )

    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, value: tuple[int, int]) -> tuple[int, int]:
        width, height = value
        if width <= 0 or height <= 0:
            raise ValueError(f"resolution must be positive (width, height), got {value}")
        return value

    # Whether/how to include this clip's own embedded audio stream (e.g. a
    # video file's soundtrack) in exports, distinct from any separate
    # AudioClip placed on an audio track. Defaults to including it at full
    # volume, matching what a person would expect from dropping a video
    # with sound onto a track. For an image (no embedded audio), exporters
    # simply find no audio stream to map and this field has no effect.
    source_audio: AudioProperties = Field(
        default_factory=AudioProperties,
        description="Volume/mute controls for this clip's own embedded audio stream, if it has one",
    )

    linked_clip_id: str | None = Field(
        default=None, description="Optional ID of a linked clip (e.g., for split clips or related media)"
    )  # todo: add validation to ensure linked clip exists in the same track or project, and that it is of a compatible type (e.g., media clip) # noqa: E501

    def preview_image(
        self,
        time: "Time | float" = 0.0,
        *,
        resolution: tuple[int, int] | None = None,
        cache_dir: "str | Path | None" = None,
        asset_resolver: Any = None,
        force: bool = False,
    ) -> Path:
        """Render one frame of this clip's own source, with its own
        `transform` applied, onto a `resolution` canvas (default: this
        clip's own `resolution`), and return the PNG path.

        Shows the clip in isolation -- exactly what `FFmpegVideoExporter`
        would draw for it alone, stopped after a single frame -- not how it
        looks stacked with any other clip or track on a timeline. `time` is
        seconds into this clip (0.0 = its first visible frame, i.e.
        `source.start`); accepts a `Time` or a plain number of seconds, the
        same as `CodedVisualClip.preview_frame`. Ignored for an image
        source. `asset_resolver` is used the same way `export_to_video`'s
        is, for a source like `asset://b_roll`.

        Needs `ffmpeg` on PATH (the same requirement `export_to_video`
        has). Raises `MissingSourceError` if the source file can't be
        found, `ExportError` if ffmpeg itself fails.
        """
        from visualkit.exporters.single_clip import preview_media_image

        seconds = time.seconds if isinstance(time, Time) else float(time)
        return preview_media_image(
            self,
            seconds,
            resolution=resolution,
            cache_dir=cache_dir,
            asset_resolver=asset_resolver,
            force=force,
        )
