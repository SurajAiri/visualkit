"""Compound clip — a self-contained composition of multiple clips on an internal timeline.

A CompoundClip can be:
- **Editable** (template): exposes named parameters that can be swapped to reuse
  the same structure with different content (e.g., an infographic template).
- **Sealed** (non-editable): a baked composition with no external parameters
  (e.g., the refined main track).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from visualkit.models.variable import Variable
from visualkit.utils.time import Time

from .base import BaseClip

if TYPE_CHECKING:
    from visualkit.models.timeline import Timeline


class ExposedParameter(BaseModel):
    """Maps a top-level compound clip parameter to a specific inner clip's variable or property.

    Enables compound clips to act as reusable templates with AI-friendly descriptions
    and human-friendly labels.
    """

    name: str = Field(..., description="External parameter name exposed to caller/agent")
    target_clip_id: str = Field(..., description="ID of the target clip inside inner_timeline")
    target_variable: str = Field(
        ...,
        description="Property or variable name on the target clip (e.g. 'text', 'headline', 'bg_color')",
    )
    label: str | None = Field(default=None, description="Human-friendly label for UI")
    description: str | None = Field(
        default=None,
        description="Guidance for AI agents explaining what this parameter controls and format constraints",
    )
    default: Any = Field(default=None, description="Default fallback value")
    required: bool = Field(
        default=False, description="Whether this parameter must be provided before rendering"
    )


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
    inner_timeline: Timeline | None = Field(
        default=None,
        description="Internal timeline containing the compound clip's tracks and clips",
    )

    linked_clip_id: str | None = Field(
        default=None,
        description="Optional ID of a linked companion clip (e.g. CompoundAudioClip)",
    )

    # Template parameter mappings and configured values
    exposed_parameters: list[ExposedParameter] = Field(
        default_factory=list,
        description="Definitions of parameters exposed to external callers/agents",
    )

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Configured values for exposed template parameters (e.g. {'title': 'Intro'})",
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

    def expose_parameter(
        self,
        name: str,
        target_clip_id: str,
        target_variable: str,
        label: str | None = None,
        description: str | None = None,
        default: Any = None,
        required: bool = False,
    ) -> ExposedParameter:
        """Register an exposed parameter mapping for template reuse."""
        param = ExposedParameter(
            name=name,
            target_clip_id=target_clip_id,
            target_variable=target_variable,
            label=label,
            description=description,
            default=default,
            required=required,
        )
        # Replace if already exists with same name
        self.exposed_parameters = [p for p in self.exposed_parameters if p.name != name]
        self.exposed_parameters.append(param)
        return param

    def get_set_parameters(self) -> dict[str, Any]:
        """Return all parameter names and values that have been set on this compound clip."""
        return dict(self.parameters)

    def get_unset_parameters(self) -> list[ExposedParameter]:
        """Return exposed parameter definitions that have not been assigned a value."""
        return [p for p in self.exposed_parameters if p.name not in self.parameters]

    def get_missing_required_parameters(self) -> list[str]:
        """Return names of required exposed parameters that have neither an assigned value nor a default."""
        missing = []
        for p in self.exposed_parameters:
            if p.required:
                val = self.parameters.get(p.name, p.default)
                if val is None:
                    missing.append(p.name)
        return missing

    def get_child_variables(self) -> dict[str, dict[str, Variable]]:
        """Collect and return variables from all inner clips, grouped by clip ID.

        Allows inspecting variables cleanly separated per child clip.
        """
        grouped: dict[str, dict[str, Variable]] = {}
        if not self.inner_timeline:
            return grouped

        for track in self.inner_timeline.all_tracks:
            for clip in track.clips:
                clip_vars: dict[str, Variable] = {}
                if hasattr(clip, "variables") and isinstance(clip.variables, dict):
                    clip_vars = clip.variables
                elif hasattr(clip, "get_child_variables"):
                    # Nested compound clip
                    nested = clip.get_child_variables()
                    for nested_id, n_vars in nested.items():
                        grouped[f"{clip.id}.{nested_id}"] = n_vars
                if clip_vars:
                    grouped[clip.id] = clip_vars
        return grouped

    def set_parameter(self, name: str, value: Any) -> None:
        """Set an exposed parameter value and immediately apply it to child clips."""
        self.parameters[name] = value
        self.apply_parameters()

    def apply_parameters(self) -> None:
        """Propagate current parameters down to child clips in the inner timeline."""
        if not self.inner_timeline:
            return

        # 1. Apply mapped parameters
        mapping_by_name = {p.name: p for p in self.exposed_parameters}
        for name, value in self.parameters.items():
            if name in mapping_by_name:
                mapping = mapping_by_name[name]
                _, clip = self.inner_timeline.get_clip(mapping.target_clip_id)
                if clip is not None:
                    self._apply_val_to_clip(clip, mapping.target_variable, value)

            # 2. Support direct namespaced parameters: 'clip_id.property'
            elif "." in name:
                target_clip_id, var_name = name.split(".", 1)
                _, clip = self.inner_timeline.get_clip(target_clip_id)
                if clip is not None:
                    self._apply_val_to_clip(clip, var_name, value)

    @staticmethod
    def _apply_val_to_clip(clip: Any, var_name: str, value: Any) -> None:
        """Helper to inject a value into a clip variable or attribute."""
        if hasattr(clip, "set_parameter"):
            clip.set_parameter(var_name, value)
        elif hasattr(clip, "set_variable"):
            clip.set_variable(var_name, value)
        elif hasattr(clip, "variables") and isinstance(clip.variables, dict):
            if var_name in clip.variables:
                clip.variables[var_name].value = value
            else:
                clip.variables[var_name] = Variable(name=var_name, value=value, default=value)
        elif hasattr(clip, var_name):
            setattr(clip, var_name, value)
