"""Loading coded-visual projects: a single ``.html`` file or a directory bundle.

Metadata precedence (lowest to highest): built-in defaults, ``manifest.json``
/ ``template.json`` in a bundle, an embedded ``<script id="visualkit-manifest"
type="application/json">``, then ``<meta name="...">`` tags in the HTML.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from pydantic import Field

from visualkit.models.clips.base import Size
from visualkit.models.variable import Variable
from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.exceptions import CodedVisualError

_MANIFEST_SCRIPT_IDS = {"manifest", "visualkit-manifest"}
_MANIFEST_FILENAMES = ("manifest.json", "template.json")


class CodedVisualManifest(VisualKitModel):
    """Metadata schema defining the design specifications and parameters for a coded visual."""

    name: str | None = Field(default=None, description="Display name of the template or infographic")
    aspect_ratio: str | None = Field(
        default=None,
        description="Target aspect ratio (e.g. '16:9', '9:16'). Derived from canvas_size when unset.",
    )
    canvas_size: Size = Field(
        default_factory=lambda: Size(width=1920, height=1080),
        description="Native design canvas resolution (width x height)",
    )
    fps: float = Field(default=30.0, gt=0.0, description="Recommended frames per second")
    duration: float | None = Field(default=None, gt=0.0, description="Recommended duration in seconds")
    animated: bool | None = Field(
        default=None,
        description="Force still (False) or video (True) rendering; None means detect automatically.",
    )
    variables: dict[str, Variable] = Field(
        default_factory=dict,
        description="Declared template variables and their default/AI metadata",
    )


class _HeadScanner(HTMLParser):
    """Collect <meta name=... content=...> tags and the embedded manifest <script>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.manifest_json: str | None = None
        self._in_manifest = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta" and "name" in a and "content" in a:
            self.meta[a["name"].strip().lower()] = a["content"]
        elif tag == "script" and a.get("id", "").lower() in _MANIFEST_SCRIPT_IDS:
            self._in_manifest = True
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_manifest:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_manifest:
            self._in_manifest = False
            if self.manifest_json is None:
                self.manifest_json = "".join(self._buf).strip()


def _parse_dimension(text: str, what: str) -> float:
    try:
        value = float(text)
    except ValueError as err:
        raise CodedVisualError(f'<meta name="{what}"> must be a number, got {text!r}') from err
    if value <= 0:
        raise CodedVisualError(f'<meta name="{what}"> must be positive, got {text!r}')
    return value


def _parse_html_meta(
    html_content: str,
    default_manifest: CodedVisualManifest | None = None,
) -> CodedVisualManifest:
    """Merge metadata declared inside the HTML onto `default_manifest`.

    Malformed metadata raises `CodedVisualError` naming the offending field,
    rather than being ignored (a typo'd canvas size silently falling back to
    1920x1080 is exactly the "why does my layout look wrong" bug to avoid).
    """
    manifest = default_manifest.model_copy(deep=True) if default_manifest else CodedVisualManifest()
    scanner = _HeadScanner()
    scanner.feed(html_content)

    if scanner.manifest_json:
        try:
            data = json.loads(scanner.manifest_json)
            embedded = CodedVisualManifest.model_validate(data)
        except (json.JSONDecodeError, ValueError) as err:
            raise CodedVisualError(f"Invalid embedded manifest <script>: {err}") from err
        fields = embedded.model_fields_set
        merged = manifest.model_dump()
        for f in fields:
            merged[f] = getattr(embedded, f)
        manifest = CodedVisualManifest.model_validate(
            {**merged, "variables": {k: v for k, v in (merged.get("variables") or {}).items()}}
        )

    meta = scanner.meta
    for key in ("aspect-ratio", "aspect_ratio"):
        if key in meta:
            manifest.aspect_ratio = meta[key].strip()

    width, height = manifest.canvas_size.width, manifest.canvas_size.height
    if "canvas-size" in meta:
        parts = meta["canvas-size"].lower().replace("×", "x").split("x")
        if len(parts) != 2:
            raise CodedVisualError(
                f"<meta name=\"canvas-size\"> must look like '1920x1080', got {meta['canvas-size']!r}"
            )
        width, height = _parse_dimension(parts[0], "canvas-size"), _parse_dimension(parts[1], "canvas-size")
    if "canvas-width" in meta:
        width = _parse_dimension(meta["canvas-width"], "canvas-width")
    if "canvas-height" in meta:
        height = _parse_dimension(meta["canvas-height"], "canvas-height")
    manifest.canvas_size = Size(width=width, height=height)

    if "fps" in meta:
        manifest.fps = _parse_dimension(meta["fps"], "fps")
    if "duration" in meta:
        manifest.duration = _parse_dimension(meta["duration"], "duration")
    if "animated" in meta:
        manifest.animated = meta["animated"].strip().lower() in {"true", "1", "yes"}

    return manifest


def resolve_entrypoint(source_path: str | Path) -> Path:
    """Return the HTML entrypoint for a file or bundle directory."""
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Coded visual path does not exist: {path}")
    if path.is_dir():
        index = path / "index.html"
        if index.exists():
            return index
        html_files = sorted(path.glob("*.html"))
        if not html_files:
            raise FileNotFoundError(f"No HTML entrypoint found in bundle directory: {path}")
        return html_files[0]
    if path.is_file():
        return path
    raise ValueError(f"Invalid path type for coded visual: {path}")


def load_coded_visual(source_path: str | Path) -> tuple[Path, CodedVisualManifest, str]:
    """Load a coded visual from a single HTML file or a directory bundle.

    Returns ``(entrypoint_html_path, manifest, raw_html_content)``.
    """
    entrypoint = resolve_entrypoint(source_path)
    manifest = CodedVisualManifest()

    bundle_dir = Path(source_path).expanduser().resolve()
    if bundle_dir.is_dir():
        for manifest_name in _MANIFEST_FILENAMES:
            manifest_file = bundle_dir / manifest_name
            if manifest_file.exists():
                try:
                    manifest = CodedVisualManifest.model_validate(
                        json.loads(manifest_file.read_text(encoding="utf-8"))
                    )
                except (json.JSONDecodeError, ValueError) as err:
                    raise CodedVisualError(f"Failed to parse {manifest_file}: {err}") from err
                break

    raw_html = entrypoint.read_text(encoding="utf-8")
    manifest = _parse_html_meta(raw_html, default_manifest=manifest)
    return entrypoint, manifest, raw_html
