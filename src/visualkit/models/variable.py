"""Template variables for coded visuals and compound-clip templates."""

from __future__ import annotations

import json
import math
import re
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from visualkit.utils.base_model import VisualKitModel


class VariableType(str, Enum):
    """Supported variable types for templates and coded visuals."""

    STRING = "string"
    NUMBER = "number"
    COLOR = "color"
    ASSET = "asset"
    BOOLEAN = "boolean"
    JSON = "json"


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FUNC_COLOR = re.compile(r"^(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color)\(\s*[-+0-9a-zA-Z.,%/\s]*\)$")
_NAMED_COLOR = re.compile(r"^[a-zA-Z]{3,30}$")
_TRUE_STRINGS = frozenset({"true", "1", "yes", "y", "on"})
_FALSE_STRINGS = frozenset({"false", "0", "no", "n", "off", ""})


def infer_variable_type(value: Any) -> VariableType:
    """Best-effort `VariableType` for a raw Python value.

    Used when a caller passes a bare value (``variables={"count": 10}``)
    instead of a full `Variable`, so a number stays a NUMBER rather than
    being silently stringified.
    """
    if isinstance(value, bool):
        return VariableType.BOOLEAN
    if isinstance(value, (int, float)):
        return VariableType.NUMBER
    if isinstance(value, (dict, list)):
        return VariableType.JSON
    return VariableType.STRING


def coerce_variable_value(var_type: VariableType, value: Any, *, name: str = "variable") -> Any:
    """Coerce `value` to the canonical Python form for `var_type`.

    Raises ValueError with a clear message if `value` cannot be represented
    as `var_type`. ``None`` is passed through (it means "unset").

    Canonical forms: STRING -> str, NUMBER -> int|float (finite), BOOLEAN ->
    bool, COLOR -> str (validated CSS color), ASSET -> str (non-empty
    reference/path), JSON -> any JSON-serialisable Python value (a JSON
    *string* is parsed).
    """
    if value is None:
        return None

    if var_type == VariableType.STRING:
        return value if isinstance(value, str) else str(value)

    if var_type == VariableType.NUMBER:
        if isinstance(value, bool):
            raise ValueError(f"{name}: expected a number, got a bool")
        if isinstance(value, (int, float)):
            number: int | float = value
        elif isinstance(value, str):
            text = value.strip()
            try:
                number = int(text)
            except ValueError:
                try:
                    number = float(text)
                except ValueError as err:
                    raise ValueError(f"{name}: {value!r} is not a valid number") from err
        else:
            raise ValueError(f"{name}: expected a number, got {type(value).__name__}")
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError(f"{name}: number must be finite, got {number}")
        return number

    if var_type == VariableType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUE_STRINGS:
                return True
            if lowered in _FALSE_STRINGS:
                return False
        raise ValueError(f"{name}: {value!r} is not a valid boolean")

    if var_type == VariableType.COLOR:
        if not isinstance(value, str):
            raise ValueError(f"{name}: color must be a string, got {type(value).__name__}")
        text = value.strip()
        if _HEX_COLOR.match(text) or _FUNC_COLOR.match(text) or _NAMED_COLOR.match(text):
            return text
        raise ValueError(f"{name}: {value!r} is not a valid CSS color")

    if var_type == VariableType.ASSET:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}: asset must be a non-empty string reference or path")
        return value.strip()

    if var_type == VariableType.JSON:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as err:
                raise ValueError(f"{name}: invalid JSON: {err.msg}") from err
        try:
            json.dumps(value)
        except (TypeError, ValueError) as err:
            raise ValueError(f"{name}: value is not JSON-serialisable: {err}") from err
        return value

    return value  # pragma: no cover - exhaustive above


class Variable(VisualKitModel):
    """Represents a template or coded visual parameter/variable.

    Attributes:
        name: Unique identifier for the variable (e.g. 'headline_text', 'chart_color').
        type: Data type of the variable.
        value: Current assigned value. If None, resolves to default.
        default: Fallback value when no value is explicitly supplied.
        label: Human-readable label for UI controls.
        description: AI agent guidance explaining what this controls and format constraints.

    `value` and `default` are coerced to `type` on construction *and* on
    assignment, and an unrepresentable value raises instead of being
    silently kept.
    """

    name: str = Field(..., min_length=1, description="Unique variable name / key")
    type: VariableType = Field(default=VariableType.STRING, description="Type of the variable")
    value: Any = Field(default=None, description="Current assigned value")
    default: Any = Field(default=None, description="Default fallback value")
    required: bool = Field(default=False, description="Whether this variable must be set before rendering")
    label: str | None = Field(default=None, description="Human-readable label for UI")
    description: str | None = Field(
        default=None,
        description="Guidance for AI agents describing what this variable controls and constraints",
    )

    @property
    def is_set(self) -> bool:
        """True if this variable has been explicitly assigned a non-None value."""
        return self.value is not None

    def resolve_value(self) -> Any:
        """Returns the assigned value if present, else fallback to default."""
        return self.value if self.value is not None else self.default

    # NOTE: coercion happens in a *wrap* validator that never assigns through
    # `self.x = ...`. The previous `after` validator assigned `self.value`,
    # which with validate_assignment=True re-entered validation and recursed
    # forever (RecursionError) whenever coercion actually changed a value.
    @model_validator(mode="wrap")
    @classmethod
    def _coerce_to_type(cls, data: Any, handler: Any) -> Any:
        model = handler(data)
        if not isinstance(model, Variable):
            return model
        value = coerce_variable_value(model.type, model.value, name=model.name)
        default = coerce_variable_value(model.type, model.default, name=model.name)
        # object.__setattr__ bypasses validate_assignment (already validated here).
        object.__setattr__(model, "value", value)
        object.__setattr__(model, "default", default)
        return model

    def __setattr__(self, name: str, value: Any) -> None:
        # Re-coerce on plain assignment (`var.value = "42"`): pydantic's
        # validate_assignment doesn't re-run the model-level coercion above.
        if name in ("value", "default"):
            value = coerce_variable_value(self.type, value, name=self.name)
        super().__setattr__(name, value)
