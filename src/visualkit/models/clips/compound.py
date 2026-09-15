"""Compound clip — a self-contained composition of multiple clips on an internal timeline.

A CompoundClip can be:
- **Editable** (template): exposes named parameters that can be swapped to reuse
  the same structure with different content (e.g., an infographic template).
- **Sealed** (non-editable): a baked composition with no external parameters
  (e.g., the refined main track).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import BaseClip


class CompoundAudioClip(BaseClip):
    """Audio counterpart for a CompoundClip.

    Represents the audio portion of a compound clip's internal timeline.
    Linked to the visual CompoundClip via compound_clip_id and linked_clip_id.
    """

    @property
    def clip_type(self) -> str:
        return "compound_audio"

    # ID of the parent CompoundClip on the visual lane
    compound_clip_id: str = Field(
        ...,
        description="ID of the parent CompoundClip that contains the inner timeline",
    )

    volume: float = Field(
        default=1.0,
        ge=0.0,
        description="Volume multiplier for the compound clip's audio (1.0 = 100%)",
    )

    mute: bool = Field(
        default=False,
        description="Whether to mute this compound clip's audio output",
    )


class CompoundClip(BaseClip):
    """A clip that contains its own internal timeline with multiple tracks.

    Unlike VisualClip, CompoundClip extends BaseClip directly because it
    produces both visual and audio output — its inner timeline can hold
    any mix of clip types.
    """

    @property
    def clip_type(self) -> str:
        return "compound"

    # todo: have to think how to have timeline here
    # The internal timeline this compound clip encapsulates.
    # Uses a forward reference to avoid circular imports; Timeline is
    # imported at model_rebuild() time (see clips/__init__.py).
    inner_timeline: Any = Field(
        default=None,
        description="Internal timeline containing the compound clip's tracks and clips",
    )

    # todo: some way to have children clips' input variables
    # Template parameters — named values that can be swapped when reusing
    # this compound clip as a template.
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Named input parameters for template-based compound clips",
    )

    def create_audio_companion(self) -> Any:
        """Create a linked CompoundAudioClip to represent this compound on the audio lane."""

        audio_clip = CompoundAudioClip(
            id=f"ca-{self.id}",
            start=self.start,
            duration=self.duration,
            speed=self.speed,
            compound_clip_id=self.id,
        )
        self.linked_clip_id = audio_clip.id
        return audio_clip
