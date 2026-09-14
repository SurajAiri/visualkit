from enum import Enum
from typing import Literal

from pydantic import Field

from visualkit.models.clips.base import Source

from .media import MediaClip


class CompileStatus(str, Enum):
    PENDING = "pending"
    COMPILING = "compiling"
    READY = "ready"
    FAILED = "failed"


class CodedVisualClip(MediaClip):
    clip_type: Literal["coded_visual"] = "coded_visual"
    compile_status: CompileStatus = Field(default=CompileStatus.PENDING)

    # The media source for the coded visual clip.
    # This will be updated after the code is compiled.
    media_source: str | None = Field(
        None, description="Reference to the media source for the coded visual clip"
    )  # better this is deterministic, so that we can cache the compiled media source based on the code and other properties

    async def _compile(self) -> None:
        """Compile the code for the coded visual clip."""
        # Implement the logic to compile the code and update the compile_status and media_source accordingly

        # if already compiled, skip compilation & make sure media_source is set to the compiled media source
        # else first compile the code, then update the compile_status and media_source accordingly
        pass

    async def resolve(self) -> MediaClip:
        """Resolve the coded visual clip to a media clip."""

        await self._compile()  # Compile the code before resolving

        # todo: later also forward all the transform properties to the resolved media clip
        if self.media_source is None:
            raise ValueError("Media source is not set. Compilation might have failed.")
        return MediaClip(
            clip_type="media",
            source=Source(source=self.media_source, start=self.source.start),
            fps=self.fps,
            resolution=self.resolution,
            transform=self.transform,
        )
