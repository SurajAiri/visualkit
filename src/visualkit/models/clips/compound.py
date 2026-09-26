"""Compound clip — a self-contained composition of multiple clips on an internal timeline.

A CompoundClip can be:
- **Editable** (template): exposes named parameters that can be swapped to reuse
  the same structure with different content (e.g., an infographic template).
- **Sealed** (non-editable): a baked composition with no external parameters
  (e.g., the refined main track).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, ValidationError

from visualkit.models.variable import Variable
from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.exceptions import TemplateParameterError
from visualkit.utils.time import Time

from .base import BaseClip
from .visual import Transform

if TYPE_CHECKING:
    from visualkit.models.timeline import Timeline


#: Fields of a clip that a template parameter may never overwrite: they are
#: identity/structure, not content, and rewriting them would corrupt the timeline
#: (e.g. changing an inner clip's ``id`` breaks every reference to it).
_PROTECTED_FIELDS = frozenset(
    {"id", "clip_type", "linked_clip_id", "compound_clip_id", "inner_timeline", "exposed_parameters"}
)


class ExposedParameter(VisualKitModel):
    """Maps a top-level compound clip parameter to a specific inner clip's variable or property.

    Enables compound clips to act as reusable templates with AI-friendly descriptions
    and human-friendly labels.
    """

    name: str = Field(..., description="External parameter name exposed to caller/agent")
    target_clip_id: str = Field(..., description="ID of the target clip inside inner_timeline")
    target_variable: str = Field(
        ...,
        description=(
            "Property or variable name on the target clip (e.g. 'text', 'headline', 'bg_color'), "
            "or a dotted path into a nested field (e.g. 'style.color', 'transform.opacity')"
        ),
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

    # CompoundClip extends BaseClip directly rather than VisualClip (see
    # module docstring: it produces both visual and audio output), so it
    # doesn't inherit `transform` for free -- it's added explicitly here
    # instead, so a compound instance (e.g. a template) can be positioned,
    # scaled, or faded like any other visual content when flattened.
    transform: Transform = Field(
        default_factory=Transform,
        description="Transform applied to this compound's composited visual output as a whole",
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
        """Set an exposed parameter value and immediately apply it to child clips.

        A parameter that is neither exposed nor a ``'clip_id.property'`` path
        raises `TemplateParameterError` instead of being stored and ignored.
        """
        known = {p.name for p in self.exposed_parameters}
        if name not in known and "." not in name:
            raise TemplateParameterError(
                f"CompoundClip '{self.id}' has no exposed parameter {name!r}. "
                f"Exposed: {sorted(known) or 'none'}. Use expose_parameter() first, or a "
                "'clip_id.property' path."
            )
        self.parameters[name] = value
        self.apply_parameters()

    def apply_parameters(self, *, strict: bool = False) -> None:
        """Propagate current parameters down to child clips in the inner timeline.

        Applies every exposed parameter's *effective* value (an explicitly
        set value, else its ``default``). A parameter targeting a clip that
        does not exist, or a property the clip does not have, is a template
        authoring error: with ``strict=True`` (used when exporting) it
        raises `TemplateParameterError`; otherwise it is skipped.
        """
        if not self.inner_timeline:
            return

        mapping_by_name = {p.name: p for p in self.exposed_parameters}

        for name, mapping in mapping_by_name.items():
            if name in self.parameters:
                value = self.parameters[name]
            elif mapping.default is not None:
                value = mapping.default
            else:
                continue
            self._apply_to_target(mapping.target_clip_id, mapping.target_variable, value, name, strict)

        for name, value in self.parameters.items():
            if name in mapping_by_name or "." not in name:
                continue
            target_clip_id, var_name = name.split(".", 1)
            self._apply_to_target(target_clip_id, var_name, value, name, strict)

    def _apply_to_target(self, clip_id: str, var_name: str, value: Any, param: str, strict: bool) -> None:
        _, clip = self.inner_timeline.get_clip(clip_id)
        if clip is None:
            if strict:
                raise TemplateParameterError(
                    f"Parameter {param!r} on CompoundClip '{self.id}' targets clip {clip_id!r}, "
                    "which does not exist in its inner_timeline."
                )
            return
        try:
            self._apply_val_to_clip(clip, var_name, value)
        except TemplateParameterError:
            if strict:
                raise

    @classmethod
    def _apply_val_to_clip(cls, clip: Any, var_name: str, value: Any) -> None:
        """Inject `value` into a clip's variable or field; raises `TemplateParameterError` if impossible.

        `var_name` may be dotted (`style.color`, `transform.opacity`) to reach a field nested
        one or more levels inside the clip's own pydantic fields, each of which must itself be
        a model -- e.g. `TextClip.style.color`, `MediaClip.transform.opacity`. A dotted path
        always targets a real field at each step (never `set_variable`/`set_parameter`, which
        only apply to a clip's own top-level variables); every segment, including the first, is
        checked against `_PROTECTED_FIELDS`.
        """
        if var_name.split(".", 1)[0] in _PROTECTED_FIELDS:
            raise TemplateParameterError(
                f"{var_name!r} is a protected field and cannot be set by a template parameter."
            )
        if "." in var_name:
            cls._apply_val_to_nested_field(clip, var_name, value)
            return
        if hasattr(clip, "set_parameter") and isinstance(clip, CompoundClip):
            clip.set_parameter(var_name, value)
        elif hasattr(clip, "set_variable"):
            clip.set_variable(var_name, value)
        elif var_name in type(clip).model_fields:
            setattr(clip, var_name, value)
        else:
            raise TemplateParameterError(
                f"{type(clip).__name__} '{clip.id}' has no variable or property {var_name!r}."
            )

    @classmethod
    def _apply_val_to_nested_field(cls, clip: Any, path: str, value: Any) -> None:
        """Set `value` at a dotted `path` (e.g. `style.color`) by walking the clip's own
        pydantic model fields; the object at each step but the last must be a model instance
        (`None` -- an unset optional field like `TextStyle.gradient` -- is reported clearly
        rather than raising a bare `AttributeError`). The final `setattr` runs through that
        model's own field validator, so an out-of-range or wrong-type value still raises."""
        parts = path.split(".")
        obj, seen = clip, []
        for part in parts[:-1]:
            seen.append(part)
            if part in _PROTECTED_FIELDS or part not in type(obj).model_fields:
                raise TemplateParameterError(
                    f"{type(obj).__name__} '{getattr(clip, 'id', '?')}' has no field {part!r} "
                    f"(from target_variable {path!r})."
                )
            obj = getattr(obj, part)
            if obj is None:
                raise TemplateParameterError(
                    f"{type(clip).__name__} '{clip.id}': {'.'.join(seen)!r} is not set, so "
                    f"{path!r} cannot be reached."
                )
        last = parts[-1]
        if last not in type(obj).model_fields:
            raise TemplateParameterError(
                f"{type(obj).__name__} has no field {last!r} (from target_variable {path!r})."
            )
        try:
            setattr(obj, last, value)
        except ValidationError as err:
            raise TemplateParameterError(f"Invalid value {value!r} for {path!r}: {err}") from err
