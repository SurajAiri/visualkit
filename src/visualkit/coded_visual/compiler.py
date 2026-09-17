import hashlib
import json
import re
from pathlib import Path
from typing import Any

from visualkit.coded_visual.project import CodedVisualManifest, load_coded_visual
from visualkit.models.clips.base import Size
from visualkit.models.clips.coded_visual import CodedVisualClip, CompileStatus


class CodedVisualCompiler:
    """Compiles CodedVisualClip projects into prepared, variable-injected HTML bundles

    ready for rendering and headless capture.
    Handles aspect ratio preservation, relative asset resolution, and deterministic caching.
    """

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir or Path(".visualkit_cache/coded_visuals")).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_cache_key(
        source_content: str,
        variables: dict[str, Any],
        canvas_size: Size,
        aspect_ratio: str,
        fps: float,
        duration: float,
    ) -> str:
        """Generate a deterministic SHA256 hash representing the exact render state."""
        hasher = hashlib.sha256()
        hasher.update(source_content.encode("utf-8"))
        # Sort keys for deterministic JSON representation
        sorted_vars = json.dumps(variables, sort_keys=True)
        hasher.update(sorted_vars.encode("utf-8"))
        hasher.update(f"{canvas_size.width}x{canvas_size.height}".encode("utf-8"))
        hasher.update(aspect_ratio.encode("utf-8"))
        hasher.update(f"{fps}:{duration}".encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def prepare_html(
        raw_html: str,
        variables: dict[str, Any],
        canvas_size: Size,
        aspect_ratio: str,
        base_dir: Path | None = None,
    ) -> str:
        """Inject variables, base href for relative assets, and viewport styling to preserve aspect ratio."""
        prepared = raw_html

        # 1. Substitute Jinja-like {{ variable_name }} placeholders
        for var_name, val in variables.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(var_name) + r"\s*\}\}")
            prepared = pattern.sub(str(val), prepared)

        # 2. Build injection script & style blocks
        vars_json = json.dumps(variables, indent=2)
        injected_script = f"""
        <script id="visualkit-variables">
            window.__VARIABLES__ = {vars_json};
            window.VISUALKIT_PARAMS = window.__VARIABLES__;
        </script>
        """

        # Container styling that locks native design aspect ratio and canvas bounds
        injected_style = f"""
        <style id="visualkit-viewport-style">
            html, body {{
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                background-color: transparent;
            }}
            .visualkit-canvas {{
                width: {int(canvas_size.width)}px;
                height: {int(canvas_size.height)}px;
                aspect-ratio: {aspect_ratio};
                box-sizing: border-box;
                position: relative;
                overflow: hidden;
            }}
        </style>
        """

        base_tag = ""
        if base_dir:
            base_url = base_dir.as_uri() + "/"
            base_tag = f'<base href="{base_url}">\n'

        injection = f"{base_tag}\n{injected_style}\n{injected_script}"

        # Inject into <head> if present, otherwise prepend to the document
        if "<head>" in prepared:
            prepared = prepared.replace("<head>", f"<head>\n{injection}", 1)
        elif "<html>" in prepared:
            prepared = prepared.replace("<html>", f"<html><head>\n{injection}</head>", 1)
        else:
            prepared = f"<head>\n{injection}</head>\n{prepared}"

        return prepared

    def prepare_bundle(self, clip: CodedVisualClip) -> tuple[Path, str]:
        """Prepares a standalone, runnable HTML bundle directory for this clip.

        Returns (entrypoint_file_path, cache_key)
        """
        source_ref = clip.source.source
        entrypoint_path, manifest, raw_html = load_coded_visual(source_ref)

        # Merge clip properties with manifest
        canvas_size = clip.canvas_size or manifest.canvas_size
        aspect_ratio = clip.aspect_ratio or manifest.aspect_ratio
        duration = clip.duration.seconds if clip.duration else (manifest.duration or 5.0)
        fps = clip.fps or manifest.fps or 30.0

        # Combine clip variables with manifest defaults
        resolved_vars = clip.get_resolved_variables()
        for k, v in manifest.variables.items():
            if k not in resolved_vars:
                resolved_vars[k] = v.resolve_value()

        cache_key = self.compute_cache_key(
            source_content=raw_html,
            variables=resolved_vars,
            canvas_size=canvas_size,
            aspect_ratio=aspect_ratio,
            fps=fps,
            duration=duration,
        )

        clip_bundle_dir = self.cache_dir / cache_key
        clip_bundle_dir.mkdir(parents=True, exist_ok=True)
        target_html = clip_bundle_dir / "index.html"

        # Base directory for relative asset resolution (images, fonts, scripts)
        base_dir = entrypoint_path.parent

        prepared_html = self.prepare_html(
            raw_html=raw_html,
            variables=resolved_vars,
            canvas_size=canvas_size,
            aspect_ratio=aspect_ratio,
            base_dir=base_dir,
        )

        with open(target_html, "w", encoding="utf-8") as f:
            f.write(prepared_html)

        return target_html, cache_key

    def compile(self, clip: CodedVisualClip, force: bool = False) -> str:
        """Compile the clip by preparing the bundle and updating clip state."""
        clip.compile_status = CompileStatus.COMPILING
        try:
            target_html, cache_key = self.prepare_bundle(clip)
            # The compiled media source points to the prepared HTML bundle entrypoint
            clip.media_source = str(target_html)
            clip.compile_status = CompileStatus.READY
            return str(target_html)
        except Exception as e:
            clip.compile_status = CompileStatus.FAILED
            raise RuntimeError(f"Failed to compile CodedVisualClip '{clip.id}': {e}") from e
