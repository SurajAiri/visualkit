"""Shared Pydantic base model for VisualKit.

Every model in the library should inherit from `VisualKitModel` (or
`VisualKitModel, ABC` for abstract base clips) instead of `pydantic.BaseModel`
directly. This gives the whole schema one consistent, strict configuration
instead of leaving each model to (re)discover it independently.

Rationale for `extra="forbid"`
-------------------------------
By default Pydantic v2 silently *drops* unrecognized keyword arguments
instead of raising. For a library whose primary interface is "construct a
clip/timeline with keyword arguments", that default is actively dangerous:
a typo'd field name (`opacty=50` instead of `opacity=50`) or a field from an
older/newer schema version doesn't raise -- it just silently vanishes, and
the caller gets a clip that looks fine but is missing the property they
thought they set. `extra="forbid"` turns that class of mistake into an
immediate, loud `ValidationError` at construction time instead of a
confusing "why doesn't my clip look right" bug discovered much later
(often only after export).
"""

from pydantic import BaseModel, ConfigDict


class VisualKitModel(BaseModel):
    """Base class for all VisualKit Pydantic models.

    - `extra="forbid"`: unknown keyword arguments raise instead of being
      silently discarded. See module docstring.
    - `validate_assignment=True`: mutating an attribute after construction
      (e.g. `clip.speed = 2.0`) re-runs field validation, so invalid
      post-construction mutation is caught the same way invalid
      construction is. Without this, `clip.speed = -1` would silently
      bypass the `ge=0.0` constraint declared on the field.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )
