from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from visualkit.models.clips.base import Size, Source
from visualkit.models.variable import Variable, VariableType

from .media import MediaClip


class CompileStatus(str, Enum):
    PENDING = "pending"
    COMPILING = "compiling"
    READY = "ready"
    FAILED = "failed"


class CodedVisualClip(MediaClip):
    """Represents an HTML/CSS/JS or code-based animated visual or infographic clip.

    Can be defined via an inline code string, a single .html file, or a full project directory bundle.
    Supports variables with labels and AI descriptions for template reusability.
    """

    clip_type: Literal["coded_visual"] = Field(
        default="coded_visual", frozen=True, description="Type of the clip (coded visual)"
    )

    # Optional inline code if not loading from an external file/folder
    code: str | None = Field(
        default=None,
        description="Inline HTML/CSS/JS code content. If provided, source defaults to inline://",
    )

    # Project directory if bundle-based (contains index.html, assets/, manifest.json)
    project_path: str | None = Field(
        default=None,
        description="Path to bundle directory if loading as a multi-asset project folder",
    )

    # Canvas dimensions and responsive scaling
    canvas_size: Size = Field(
        default_factory=lambda: Size(width=1920, height=1080),
        description="Design canvas dimensions (width and height) for the infographic",
    )
    auto_scale: bool = Field(
        default=True,
        description="Automatically scale the rendered media keeping aspect ratio to fit target",
    )

    # Variables definition and assignments
    variables: dict[str, Variable] = Field(
        default_factory=dict,
        description="Named variables/parameters for dynamic infographic templating",
    )

    compile_status: CompileStatus = Field(default=CompileStatus.PENDING)

    # Media source updated after compilation
    media_source: str | None = Field(
        default=None,
        description="Reference to the compiled media source (e.g. rendered video or image)",
    )

    @model_validator(mode="before")
    @classmethod
    def _prepare_source_and_vars(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If code or project_path is provided without source, default source
            if "source" not in data:
                if "project_path" in data and data["project_path"]:
                    data["source"] = Source(source=data["project_path"])
                elif "code" in data and data["code"]:
                    data["source"] = Source(source="inline://coded_visual")
                else:
                    data["source"] = Source(source="unspecified")

            # Allow passing raw dict of variables: {"title": "Hello", "count": 10}
            # or {"title": Variable(...)} or {"title": {"type": "string", "value": "..."}}
            raw_vars = data.get("variables")
            if isinstance(raw_vars, dict):
                normalized: dict[str, Any] = {}
                for k, v in raw_vars.items():
                    if isinstance(v, Variable):
                        normalized[k] = v
                    elif isinstance(v, dict):
                        if "name" not in v:
                            v = {**v, "name": k}
                        normalized[k] = v
                    else:
                        # Raw primitive value
                        normalized[k] = Variable(name=k, value=v, default=v)
                data["variables"] = normalized
            elif isinstance(raw_vars, list):
                # Allow passing list of Variable objects
                data["variables"] = {
                    (v.name if isinstance(v, Variable) else v["name"]): v for v in raw_vars
                }
        return data

    def define_variable(
        self,
        name: str,
        type: VariableType = VariableType.STRING,
        value: Any = None,
        default: Any = None,
        label: str | None = None,
        description: str | None = None,
    ) -> Variable:
        """Define or update a template variable with metadata."""
        var = Variable(
            name=name,
            type=type,
            value=value,
            default=default,
            label=label,
            description=description,
        )
        self.variables[name] = var
        return var

    def set_variable(self, name: str, value: Any) -> None:
        """Assign a value to an existing or new variable."""
        if name in self.variables:
            self.variables[name].value = value
        else:
            self.variables[name] = Variable(name=name, value=value, default=value)

    def get_variable(self, name: str) -> Variable | None:
        """Get the Variable model for a given variable name."""
        return self.variables.get(name)

    def get_resolved_variables(self) -> dict[str, Any]:
        """Resolve all variables to their assigned values or defaults."""
        return {name: var.resolve_value() for name, var in self.variables.items()}

    async def _compile(self) -> None:
        """Compile the code for the coded visual clip."""
        # Will be driven by the CodedVisualCompiler
        pass

    async def resolve(self) -> MediaClip:
        """Resolve the coded visual clip to a media clip."""
        await self._compile()
        if self.media_source is None:
            raise ValueError("Media source is not set. Compilation might have failed.")
        return MediaClip(
            source=Source(source=self.media_source, start=self.source.start),
            fps=self.fps,
            resolution=self.resolution,
            transform=self.transform,
        )
