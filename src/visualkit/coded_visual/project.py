import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from visualkit.models.clips.base import Size
from visualkit.models.variable import Variable, VariableType


class CodedVisualManifest(BaseModel):
    """Metadata schema defining the design specifications and parameters for a coded visual."""

    name: str | None = Field(default=None, description="Display name of the template or infographic")
    aspect_ratio: str = Field(
        default="16:9",
        description="Target aspect ratio defined for this visual (e.g. '16:9', '9:16', '1:1', '4:5')",
    )
    canvas_size: Size = Field(
        default_factory=lambda: Size(width=1920, height=1080),
        description="Native design canvas resolution (width x height)",
    )
    fps: float = Field(default=30.0, gt=0.0, description="Recommended frames per second")
    duration: float | None = Field(default=None, description="Recommended duration in seconds")
    variables: dict[str, Variable] = Field(
        default_factory=dict,
        description="Declared template variables and their default/AI metadata",
    )


def _parse_html_meta(
    html_content: str,
    default_manifest: CodedVisualManifest | None = None,
) -> CodedVisualManifest:
    """Extract metadata from HTML meta tags or embedded JSON manifest script."""
    manifest = default_manifest or CodedVisualManifest()

    # 1. Check for embedded <script id="manifest" type="application/json">...</script>
    script_match = re.search(
        r'<script[^>]*id=["\'](?:manifest|visualkit-manifest)["\'][^>]*>(.*?)</script>',
        html_content,
        re.DOTALL | re.IGNORECASE,
    )
    if script_match:
        try:
            data = json.loads(script_match.group(1).strip())
            return CodedVisualManifest.model_validate(data)
        except Exception:
            pass

    # 2. Parse <meta name="..." content="..."> tags
    meta_tags = re.findall(
        r'<meta\s+name=["\']([^"\']+)["\']\s+content=["\']([^"\']+)["\']',
        html_content,
        re.IGNORECASE,
    )
    # Also handle reversed content/name order
    meta_tags_rev = re.findall(
        r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']([^"\']+)["\']',
        html_content,
        re.IGNORECASE,
    )
    for content, name in meta_tags_rev:
        meta_tags.append((name, content))

    meta_dict = {k.lower(): v for k, v in meta_tags}

    if "aspect-ratio" in meta_dict:
        manifest.aspect_ratio = meta_dict["aspect-ratio"]
    elif "aspect_ratio" in meta_dict:
        manifest.aspect_ratio = meta_dict["aspect_ratio"]

    # Canvas size from width & height or canvas-size string
    width = manifest.canvas_size.width
    height = manifest.canvas_size.height

    if "canvas-size" in meta_dict:
        parts = meta_dict["canvas-size"].lower().split("x")
        if len(parts) == 2:
            try:
                width, height = float(parts[0]), float(parts[1])
            except ValueError:
                pass
    if "canvas-width" in meta_dict:
        try:
            width = float(meta_dict["canvas-width"])
        except ValueError:
            pass
    if "canvas-height" in meta_dict:
        try:
            height = float(meta_dict["canvas-height"])
        except ValueError:
            pass

    manifest.canvas_size = Size(width=width, height=height)

    if "fps" in meta_dict:
        try:
            manifest.fps = float(meta_dict["fps"])
        except ValueError:
            pass

    if "duration" in meta_dict:
        try:
            manifest.duration = float(meta_dict["duration"])
        except ValueError:
            pass

    return manifest


def load_coded_visual(source_path: str | Path) -> tuple[Path, CodedVisualManifest, str]:
    """Load a coded visual from either a single HTML file or a directory bundle.

    Returns:
        tuple of (entrypoint_html_path, manifest, raw_html_content)
    """
    path = Path(source_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Coded visual path does not exist: {path}")

    # Case A: Directory Bundle
    if path.is_dir():
        entrypoint = path / "index.html"
        if not entrypoint.exists():
            html_files = list(path.glob("*.html"))
            if not html_files:
                raise FileNotFoundError(f"No HTML entrypoint found in bundle directory: {path}")
            entrypoint = html_files[0]

        manifest = CodedVisualManifest()
        for manifest_name in ("manifest.json", "template.json"):
            manifest_file = path / manifest_name
            if manifest_file.exists():
                try:
                    with open(manifest_file, encoding="utf-8") as f:
                        data = json.load(f)
                    manifest = CodedVisualManifest.model_validate(data)
                    break
                except Exception as e:
                    raise ValueError(f"Failed to parse {manifest_file}: {e}") from e

        with open(entrypoint, encoding="utf-8") as f:
            raw_html = f.read()

        # HTML meta tags can augment or override manifest
        manifest = _parse_html_meta(raw_html, default_manifest=manifest)
        return entrypoint, manifest, raw_html

    # Case B: Single HTML File
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            raw_html = f.read()
        manifest = _parse_html_meta(raw_html)
        return path, manifest, raw_html

    raise ValueError(f"Invalid path type for coded visual: {path}")
