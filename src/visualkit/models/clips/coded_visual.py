from enum import Enum
from pathlib import Path
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

    References an external HTML file or a project directory bundle via source.source,
    preventing bloated timeline metadata. Preserves designed aspect ratio and canvas dimensions.
    """

    clip_type: Literal["coded_visual"] = Field(
        default="coded_visual", frozen=True, description="Type of the clip (coded visual)"
    )

    # Design dimensions and aspect ratio from metadata
    aspect_ratio: str = Field(
        default="16:9",
        description="Aspect ratio defined in code metadata (e.g. '16:9', '9:16', '1:1')",
    )
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
            # Allow passing source as a plain string path
            if "source" in data and isinstance(data["source"], str):
                data["source"] = Source(source=data["source"])
            elif "source" not in data:
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
                        normalized[k] = Variable(name=k, value=v, default=v)
                data["variables"] = normalized
            elif isinstance(raw_vars, list):
                data["variables"] = {(v.name if isinstance(v, Variable) else v["name"]): v for v in raw_vars}
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

    def get_set_variables(self) -> dict[str, Any]:
        """Return names and current assigned values of all explicitly set variables."""
        return {name: var.value for name, var in self.variables.items() if var.is_set}

    def get_unset_variables(self) -> dict[str, Variable]:
        """Return all variables that have not been explicitly assigned a value."""
        return {name: var for name, var in self.variables.items() if not var.is_set}

    def get_missing_required_variables(self) -> list[str]:
        """Return variable names that are marked as required but have no value or default."""
        return [name for name, var in self.variables.items() if var.required and var.resolve_value() is None]

    def load_manifest(self, path: str | Path | None = None) -> None:
        """Load metadata/manifest from the source path and update aspect ratio, canvas size, and variables."""
        from visualkit.coded_visual.project import load_coded_visual

        target_path = path or self.source.source
        if not target_path or target_path == "unspecified":
            return

        _, manifest, _ = load_coded_visual(target_path)
        self.aspect_ratio = manifest.aspect_ratio
        self.canvas_size = manifest.canvas_size
        if manifest.fps:
            self.fps = manifest.fps

        # Merge manifest variables as defaults if not already explicitly set
        for var_name, var in manifest.variables.items():
            if var_name not in self.variables:
                self.variables[var_name] = var
            elif self.variables[var_name].value is None and var.default is not None:
                self.variables[var_name].default = var.default

    async def _compile(self) -> None:
        """Compile the code for the coded visual clip."""
        from visualkit.coded_visual.compiler import CodedVisualCompiler

        if self.compile_status == CompileStatus.READY and self.media_source:
            return

        compiler = CodedVisualCompiler()
        compiler.compile(self)

    async def resolve(self) -> MediaClip:
        """Resolve the coded visual clip to a media clip."""
        await self._compile()
        if self.media_source is None:
            raise ValueError("Media source is not set. Compilation might have failed.")
        return MediaClip(
            id=self.id,
            timeline_start=self.timeline_start,
            duration=self.duration,
            speed=self.speed,
            source=Source(source=self.media_source, start=self.source.start),
            fps=self.fps,
            resolution=(int(self.canvas_size.width), int(self.canvas_size.height)),
            transform=self.transform,
        )
