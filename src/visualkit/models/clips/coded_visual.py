"""CodedVisualClip: an HTML/CSS/JS visual that is *rendered* into media.

A coded visual is a small web project (a single ``.html`` file or a
directory bundle with ``index.html`` + assets) that draws an infographic or
animation. It is **not** itself media: the compiler renders it, in a
headless browser, into a concrete file -- a PNG (for a still visual) or a
video (for an animated one) -- and that file is what the timeline and the
exporters treat as an ordinary media clip.

Design canvas and scaling
-------------------------
The visual is authored against a fixed *design canvas* (``canvas_size``,
e.g. 1920x1080, or 1080x1920 for vertical). It is always rendered at that
design size, so the layout never reflows or breaks, and is then scaled --
preserving its aspect ratio -- to fit whatever target the exporter
composites it into (see `Transform`/`Size`). Changing the export
resolution therefore rescales the picture instead of re-laying it out.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from visualkit.models.clips.base import Size, Source
from visualkit.models.variable import Variable, VariableType, infer_variable_type
from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.time import Time

from .media import MediaClip

_ASPECT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)\s*$")


def parse_aspect_ratio(text: str) -> tuple[float, float]:
    """Parse ``'16:9'`` / ``'16/9'`` into ``(16.0, 9.0)``. Raises ValueError."""
    match = _ASPECT_RE.match(text)
    if not match:
        raise ValueError(f"aspect ratio must look like '16:9' or '16/9', got {text!r}")
    w, h = float(match.group(1)), float(match.group(2))
    if w <= 0 or h <= 0:
        raise ValueError(f"aspect ratio components must be positive, got {text!r}")
    return w, h


def aspect_ratio_for(width: float, height: float) -> str:
    """Reduce a pixel size to the simplest integer ratio string, e.g. 1920x1080 -> '16:9'."""
    from math import gcd

    w, h = int(round(width)), int(round(height))
    if w <= 0 or h <= 0:
        raise ValueError("width and height must be positive")
    g = gcd(w, h)
    return f"{w // g}:{h // g}"


class CompileStatus(str, Enum):
    PENDING = "pending"
    COMPILING = "compiling"
    READY = "ready"
    FAILED = "failed"


class RenderMode(str, Enum):
    """How a coded visual becomes media."""

    AUTO = "auto"  # still if the page has no motion, video otherwise
    IMAGE = "image"  # always a single PNG frame
    VIDEO = "video"  # always an animated video


class LintIssue(VisualKitModel):
    """One problem found by `CodedVisualClip.lint()`.

    `severity="error"` means the render is very likely blank, wrong, or
    will fail outright; `"warning"` means it's worth a look but may be
    intentional (e.g. a variable that's only read from JavaScript).
    """

    severity: Literal["error", "warning"] = Field(description="How serious this issue is.")
    code: str = Field(
        description=(
            "Short machine-readable identifier for this kind of issue, e.g. "
            "'missing_canvas', 'unresolved_variable', 'unused_variable', 'resolve_failed'."
        )
    )
    message: str = Field(description="Human-readable description of the problem.")


class CodedVisualClip(MediaClip):
    """An HTML/CSS/JS visual that is rendered to an image or video, then used as a normal media clip.

    ``source.source`` references the ``.html`` file or bundle directory (kept
    as a reference so timeline JSON stays small). Once compiled,
    ``media_source`` points at the rendered PNG/video.
    """

    clip_type: Literal["coded_visual"] = Field(
        default="coded_visual", frozen=True, description="Type of the clip (coded visual)"
    )

    aspect_ratio: str | None = Field(
        default=None,
        description=(
            "Design aspect ratio ('16:9', '9:16', '1:1'). Left unset it is derived from "
            "`canvas_size`; if both are given they must agree."
        ),
    )
    canvas_size: Size | None = Field(
        default=None,
        description=(
            "Design canvas in pixels. Left unset it is taken from the visual's own "
            "manifest/meta tags (falling back to 1920x1080)."
        ),
    )
    auto_scale: bool = Field(
        default=True,
        description=(
            "Scale the rendered visual, preserving aspect ratio, to fit the target frame. "
            "When False it is placed at its native design size."
        ),
    )
    render_mode: RenderMode = Field(
        default=RenderMode.AUTO,
        description="Render a still image, a video, or decide automatically from the page's motion.",
    )

    variables: dict[str, Variable] = Field(
        default_factory=dict,
        description="Named variables/parameters for dynamic infographic templating",
    )

    compile_status: CompileStatus = Field(default=CompileStatus.PENDING)
    media_source: str | None = Field(
        default=None,
        description="Rendered media (PNG or video). Set by the compiler.",
    )

    # ------------------------------------------------------------------ validation
    @field_validator("aspect_ratio")
    @classmethod
    def _validate_aspect(cls, value: str | None) -> str | None:
        if value is None:
            return None
        w, h = parse_aspect_ratio(value)
        return f"{w:g}:{h:g}"

    @field_validator("canvas_size")
    @classmethod
    def _validate_canvas(cls, value: Size | None) -> Size | None:
        if value is not None and (value.width <= 0 or value.height <= 0):
            raise ValueError(f"canvas_size must have positive width and height, got {value}")
        return value

    @model_validator(mode="before")
    @classmethod
    def _prepare_source_and_vars(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)  # never mutate the caller's dict

        src = data.get("source")
        if isinstance(src, (str, Path)):
            data["source"] = Source(source=str(src))
        elif src is None:
            raise ValueError("CodedVisualClip requires a `source` (an .html file or bundle directory)")

        raw_vars = data.get("variables")
        if isinstance(raw_vars, dict):
            data["variables"] = {k: cls._normalise_variable(k, v) for k, v in raw_vars.items()}
        elif isinstance(raw_vars, list):
            normalised: dict[str, Any] = {}
            for item in raw_vars:
                name = item.name if isinstance(item, Variable) else item["name"]
                normalised[name] = cls._normalise_variable(name, item)
            data["variables"] = normalised
        return data

    @staticmethod
    def _looks_like_variable_spec(raw: dict[str, Any]) -> bool:
        """True if `raw` is a serialized `Variable` (not merely a dict-*valued* variable).

        A variable spec uses only Variable's own field names and declares its
        ``value`` or ``default`` (or an explicit ``type``). A plain payload such as
        ``{"a": 1}`` or ``{"label": "x"}`` is data and must become a JSON variable.
        """
        allowed = set(Variable.model_fields)
        if not raw or not set(raw) <= allowed:
            return False
        return bool({"value", "default", "type"} & set(raw))

    @classmethod
    def _normalise_variable(cls, name: str, raw: Any) -> Any:
        if isinstance(raw, Variable):
            return raw
        if isinstance(raw, dict) and cls._looks_like_variable_spec(raw):
            return raw if "name" in raw else {**raw, "name": name}
        return Variable(name=name, type=infer_variable_type(raw), value=raw, default=raw)

    @model_validator(mode="after")
    def _check_canvas_matches_ratio(self) -> "CodedVisualClip":
        if self.canvas_size is not None and self.aspect_ratio is not None:
            rw, rh = parse_aspect_ratio(self.aspect_ratio)
            if abs(self.canvas_size.width / self.canvas_size.height - rw / rh) > 0.01:
                raise ValueError(
                    f"canvas_size {self.canvas_size.width:g}x{self.canvas_size.height:g} does not match "
                    f"aspect_ratio {self.aspect_ratio}; give only one, or make them agree"
                )
        return self

    # ------------------------------------------------------------------ design canvas
    @property
    def design_size(self) -> tuple[int, int]:
        """Effective design canvas (width, height): explicit, else manifest, else 1920x1080."""
        if self.canvas_size is not None:
            return int(self.canvas_size.width), int(self.canvas_size.height)
        return self._manifest_design_size() or (1920, 1080)

    @property
    def design_aspect_ratio(self) -> str:
        """Effective aspect ratio string, derived from the design canvas unless set explicitly."""
        if self.aspect_ratio is not None:
            return self.aspect_ratio
        w, h = self.design_size
        return aspect_ratio_for(w, h)

    def _manifest_design_size(self) -> tuple[int, int] | None:
        try:
            from visualkit.coded_visual.project import load_coded_visual

            _, manifest, _ = load_coded_visual(self.source.source)
        except (OSError, ValueError):
            return None
        return int(manifest.canvas_size.width), int(manifest.canvas_size.height)

    # ------------------------------------------------------------------ variables
    def define_variable(
        self,
        name: str,
        type: VariableType = VariableType.STRING,
        value: Any = None,
        default: Any = None,
        label: str | None = None,
        description: str | None = None,
        required: bool = False,
    ) -> Variable:
        """Define or replace a template variable with metadata."""
        var = Variable(
            name=name,
            type=type,
            value=value,
            default=default,
            label=label,
            description=description,
            required=required,
        )
        self.variables[name] = var
        self.invalidate_compile()
        return var

    def set_variable(self, name: str, value: Any) -> None:
        """Assign a value to a variable (creating it, typed by inference, if new)."""
        if name in self.variables:
            self.variables[name].value = value
        else:
            self.variables[name] = Variable(
                name=name, type=infer_variable_type(value), value=value, default=value
            )
        self.invalidate_compile()

    def invalidate_compile(self) -> None:
        """Mark the rendered output stale so the next compile re-renders.

        Called by every mutator on this clip. The compiler additionally
        keys its cache on the *current* state, so even a direct mutation
        (``clip.variables["x"].value = ...``) that bypasses this method
        can never serve a stale render from the cache; this just also
        clears `media_source` so nothing downstream reads the old file.
        """
        if self.compile_status != CompileStatus.PENDING or self.media_source is not None:
            self.compile_status = CompileStatus.PENDING
            self.media_source = None

    _invalidate_compile = invalidate_compile  # backwards-compatible alias

    def get_variable(self, name: str) -> Variable | None:
        return self.variables.get(name)

    def get_resolved_variables(self) -> dict[str, Any]:
        """Resolve all variables to their assigned values or defaults."""
        return {name: var.resolve_value() for name, var in self.variables.items()}

    def get_set_variables(self) -> dict[str, Any]:
        return {name: var.value for name, var in self.variables.items() if var.is_set}

    def get_unset_variables(self) -> dict[str, Variable]:
        return {name: var for name, var in self.variables.items() if not var.is_set}

    def get_missing_required_variables(self) -> list[str]:
        """Names of required variables that have neither a value nor a default."""
        return [n for n, v in self.variables.items() if v.required and v.resolve_value() is None]

    def load_manifest(self, path: str | Path | None = None) -> None:
        """Pull canvas, aspect ratio, fps and variable declarations from the visual's own manifest/meta.

        Explicit clip settings win; the manifest only fills what is unset.
        """
        from visualkit.coded_visual.project import load_coded_visual

        target = path or self.source.source
        _, manifest, _ = load_coded_visual(target)

        if self.canvas_size is None:
            self.canvas_size = manifest.canvas_size
        if self.aspect_ratio is None and self.canvas_size is not None:
            self.aspect_ratio = aspect_ratio_for(self.canvas_size.width, self.canvas_size.height)
        if manifest.fps and "fps" not in self.model_fields_set:
            self.fps = manifest.fps
        # duration has no sentinel "unset" the way canvas_size/aspect_ratio do (its
        # default is Time.zero(), a legitimate-looking value), so this only backfills
        # when the clip's duration is exactly zero AND the caller never set it
        # explicitly -- matching what the compiler falls back to at compile time
        # (see CodedVisualCompiler._resolve_inputs), so `clip.duration` stops lying
        # about how long the clip will actually render for.
        if manifest.duration and self.duration.seconds == 0 and "duration" not in self.model_fields_set:
            self.duration = Time.from_seconds(manifest.duration)

        for var_name, var in manifest.variables.items():
            existing = self.variables.get(var_name)
            if existing is None:
                self.variables[var_name] = var.model_copy(deep=True)
            else:
                if existing.default is None and var.default is not None:
                    existing.default = var.default
                for attr in ("label", "description"):
                    if getattr(existing, attr) is None and getattr(var, attr) is not None:
                        setattr(existing, attr, getattr(var, attr))
                if var.required and not existing.required:
                    existing.required = True
        self.invalidate_compile()

    # ------------------------------------------------------------------ compile
    def compile(self, compiler: Any = None, *, force: bool = False) -> "CodedVisualClip":
        """Render this visual to media now (blocking). Returns self.

        Raises `CodedVisualCompileError` on failure; `compile_status` is FAILED.
        """
        if self.compile_status == CompileStatus.READY and self.media_source and not force:
            return self
        if compiler is None:
            from visualkit.coded_visual.compiler import CodedVisualCompiler

            compiler = CodedVisualCompiler()
        compiler.compile(self, force=force)
        return self

    def lint(self, compiler: Any = None) -> list[LintIssue]:
        """Pure-Python pre-flight checks, independent of Chrome, and return
        a list of `LintIssue`s (empty means nothing was found).

        Checks: the source/manifest load and every declared-required
        variable is resolved (same checks `compile()` would hit), a
        `class="visualkit-canvas"` element is present, and every
        `{{ variable }}` / `{{{ variable }}}` placeholder in the HTML
        matches a declared variable. Never raises for anything a real
        compile could hit -- those become "error"-severity issues instead
        -- so it's safe to call speculatively before deciding whether to
        compile at all. Catches the majority of agent-authoring mistakes
        before spending a browser launch on them.
        """
        if compiler is None:
            from visualkit.coded_visual.compiler import CodedVisualCompiler

            compiler = CodedVisualCompiler()
        return compiler.lint(self)

    def preview_image(self, compiler: Any = None, *, force: bool = False) -> Path:
        """Render this visual as a single still PNG and return its path,
        without compiling it (`media_source`/`compile_status` are left
        untouched).

        The forced-still counterpart to `compile()`/`preview_frame`:
        always takes the same cheap Chrome-CLI screenshot path
        `render_to_image` uses (no `playwright` package needed), regardless
        of `render_mode` or whether the page is animated. A quick way to
        catch a missing `.visualkit-canvas`, a malformed `{{ variable }}`,
        or broken layout before spending a full `compile()` or timeline
        round trip on it. For a deterministic look at a specific instant of
        an animated visual, use `preview_frame(t)` instead.
        """
        if compiler is None:
            from visualkit.coded_visual.compiler import CodedVisualCompiler

            compiler = CodedVisualCompiler()
        return compiler.preview_image(self, force=force)

    def preview_frame(self, time: "Time | float" = 0.0, compiler: Any = None, *, force: bool = False) -> Path:
        """Render one frame of this visual at `time` into the cache and return its PNG path.

        A cheap way to check what this visual looks like partway through its
        animation without encoding a full video or touching `media_source`/
        `compile_status` (unlike `compile()`). `time` may be a `Time` or a
        plain number of seconds; values past the visual's own duration still
        render (the page's clock simply keeps advancing / animations hold
        their end state). Needs the optional `playwright` package.
        """
        seconds = time.seconds if isinstance(time, Time) else float(time)
        if compiler is None:
            from visualkit.coded_visual.compiler import CodedVisualCompiler

            compiler = CodedVisualCompiler()
        return compiler.preview_frame(self, seconds, force=force)

    async def _compile(self) -> None:
        """Async wrapper: runs the blocking compile in a worker thread so it doesn't stall an event loop."""
        import asyncio

        await asyncio.to_thread(self.compile)

    def to_media_clip(self) -> MediaClip:
        """Convert a *compiled* clip into an ordinary `MediaClip` (synchronous)."""
        if self.compile_status != CompileStatus.READY or not self.media_source:
            from visualkit.utils.exceptions import CodedVisualCompileError

            raise CodedVisualCompileError(
                f"CodedVisualClip '{self.id}' has not been compiled (status={self.compile_status.value}); "
                "call .compile() or flatten via a Timeline first."
            )
        width, height = self.design_size
        is_image = Path(self.media_source).suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".svg",
        }
        return MediaClip(
            id=self.id,
            timeline_start=self.timeline_start,
            duration=self.duration,
            speed=self.speed,
            # A still image has no timeline of its own, so the trim offset must not
            # be carried over; for video it is the offset into the *rendered* file.
            source=Source(source=self.media_source, start=Time.zero() if is_image else self.source.start),
            fps=self.fps,
            resolution=(width, height),
            transform=self.transform.model_copy(deep=True),
            source_audio=self.source_audio.model_copy(deep=True),
        )

    async def resolve(self) -> MediaClip:
        """Compile (off the event loop) and return the concrete `MediaClip`."""
        await self._compile()
        return self.to_media_clip()
