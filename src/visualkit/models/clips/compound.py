"""Compound clip — a self-contained composition of multiple clips on an internal timeline.

A CompoundClip can be:
- **Editable** (template): exposes named parameters that can be swapped to reuse
  the same structure with different content (e.g., an infographic template).
- **Sealed** (non-editable): a baked composition with no external parameters
  (e.g., the refined main track).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from visualkit.utils.time import Time

from .base import BaseClip

if TYPE_CHECKING:
    from visualkit.models.timeline import Timeline


class CompoundAudioClip(BaseClip):
    """Audio counterpart for a CompoundClip.

    Represents the audio portion of a compound clip's internal timeline.
    Linked to the visual CompoundClip via compound_clip_id and linked_clip_id.
    """

    clip_type: Literal["compound_audio"] = Field(
        default="compound_audio", frozen=True, description="Type of the clip (compound audio)"
    )

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

    clip_type: Literal["compound"] = Field(
        default="compound", frozen=True, description="Type of the clip (compound)"
    )

    # The internal timeline this compound clip encapsulates.
    # Uses a forward reference to avoid circular imports; Timeline is
    # imported at model_rebuild() time (see visualkit/models/__init__.py).
    inner_timeline: Timeline | None = Field(
        default=None,
        description="Internal timeline containing the compound clip's tracks and clips",
    )

    linked_clip_id: str | None = Field(
        default=None,
        description="Optional ID of a linked companion clip (e.g. CompoundAudioClip)",
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
            timeline_start=self.timeline_start,
            duration=self.duration,
            speed=self.speed,
            compound_clip_id=self.id,
        )
        self.linked_clip_id = audio_clip.id
        return audio_clip
