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


class Variable(VisualKitModel):
    """Represents a template or coded visual parameter/variable.

    Attributes:
        name: Unique identifier for the variable (e.g. 'headline_text', 'chart_color').
        type: Data type of the variable.
        value: Current assigned value. If None, resolves to default.
        default: Fallback value when no value is explicitly supplied.
        label: Human-readable label for UI controls.
        description: AI agent guidance explaining what this controls and format constraints.
    """

    name: str = Field(..., description="Unique variable name / key")
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
        """Returns True if this variable has been explicitly assigned a non-None value."""
        return self.value is not None

    def resolve_value(self) -> Any:
        """Returns the assigned value if present, else fallback to default."""
        return self.value if self.value is not None else self.default

    @model_validator(mode="after")
    def _validate_types(self) -> "Variable":
        target_val = self.value if self.value is not None else self.default
        if target_val is None:
            return self

        if self.type == VariableType.STRING and not isinstance(target_val, str):
            self.value = str(target_val) if self.value is not None else self.value
        elif self.type == VariableType.NUMBER and not isinstance(target_val, (int, float)):
            try:
                converted = float(target_val)
                if self.value is not None:
                    self.value = converted
                elif self.default is not None:
                    self.default = converted
            except (ValueError, TypeError):
                pass
        elif self.type == VariableType.BOOLEAN and not isinstance(target_val, bool):
            if isinstance(target_val, str):
                bool_val = target_val.lower() in ("true", "1", "yes")
                if self.value is not None:
                    self.value = bool_val
                elif self.default is not None:
                    self.default = bool_val
        return self
