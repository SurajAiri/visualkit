"""Compiling a `CodedVisualClip` into a concrete media file.

Pipeline::

    HTML/CSS/JS + variables  --prepare-->  self-contained page
    page  --headless Chrome-->  PNG (still)  |  frames -> ffmpeg -> video

The compiler is *pure with respect to its inputs*: the output location is a
content hash of everything that affects the pixels (the source HTML, every
resolved variable, canvas, fps, duration, render mode, and the bytes of
files in a bundle directory), so a change to any of them can never serve a
stale render, however it was made.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from visualkit.coded_visual import browser
from visualkit.coded_visual.project import load_coded_visual
from visualkit.models.clips.base import Size
from visualkit.models.clips.coded_visual import (
    CodedVisualClip,
    CompileStatus,
    RenderMode,
    aspect_ratio_for,
    parse_aspect_ratio,
)
from visualkit.utils.exceptions import CodedVisualCompileError

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w.\-]*)\s*\}\}")
_RAW_PLACEHOLDER = re.compile(r"\{\{\{\s*([A-Za-z_][\w.\-]*)\s*\}\}\}")
_HEAD_OPEN = re.compile(r"<head(\s[^>]*)?>", re.IGNORECASE)
_HTML_OPEN = re.compile(r"<html(\s[^>]*)?>", re.IGNORECASE)
_STILL_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

# Files inside a bundle that affect rendering; hashed into the cache key.
_BUNDLE_HASH_LIMIT_BYTES = 64 * 1024 * 1024


def _json_for_script(value: Any) -> str:
    """JSON safe to embed inside an inline <script> (cannot terminate the tag or the string)."""
    text = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _stringify(value: Any) -> str:
    """How a variable renders inside HTML text/attribute content."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class CodedVisualCompiler:
    """Renders `CodedVisualClip`s to PNG (still) or video (animated) media."""

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        *,
        render_timeout: float = 120.0,
        ffmpeg: str = "ffmpeg",
    ):
        self.cache_dir = Path(cache_dir or Path(".visualkit_cache/coded_visuals")).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.render_timeout = render_timeout
        self.ffmpeg = ffmpeg

    # ------------------------------------------------------------------ cache key
    @staticmethod
    def compute_cache_key(
        source_content: str,
        variables: dict[str, Any],
        canvas_size: Size,
        aspect_ratio: str,
        fps: float,
        duration: float,
        *,
        render_mode: str = "auto",
        bundle_digest: str = "",
    ) -> str:
        """Deterministic SHA-256 over everything that can change the rendered pixels."""
        hasher = hashlib.sha256()
        hasher.update(source_content.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(_json_for_script(variables).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(
            f"{canvas_size.width:g}x{canvas_size.height:g}|{aspect_ratio}|{fps:g}|{duration:g}".encode()
        )
        hasher.update(f"|{render_mode}|{bundle_digest}".encode())
        return hasher.hexdigest()

    @staticmethod
    def _bundle_digest(entrypoint: Path) -> str:
        """Hash the *other* files in a bundle dir (css, js, images) so editing one busts the cache.

        A single-file visual (no sibling assets) hashes to "". Files over the
        size limit are hashed by (name, size, mtime) instead of content.
        """
        root = entrypoint.parent
        hasher = hashlib.sha256()
        total = 0
        found = False
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path == entrypoint or path.suffix in {".pyc"}:
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            found = True
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            hasher.update(rel.encode())
            if total + stat.st_size <= _BUNDLE_HASH_LIMIT_BYTES:
                total += stat.st_size
                hasher.update(path.read_bytes())
            else:
                hasher.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        return hasher.hexdigest() if found else ""

    # ------------------------------------------------------------------ HTML preparation
    @staticmethod
    def prepare_html(
        raw_html: str,
        variables: dict[str, Any],
        canvas_size: Size,
        aspect_ratio: str,
        base_dir: Path | None = None,
        *,
        scale_to_fit: bool = True,
    ) -> str:
        """Inject variables and design-canvas handling into a visual's HTML.

        * ``{{ name }}`` is replaced by the **HTML-escaped** value, so a
          variable can never inject markup. Use ``{{{ name }}}`` (triple
          braces) to opt in to raw, unescaped HTML for a trusted variable.
        * Values are inserted literally (no regex-backreference surprises
          from things like ``C:\\new\\1``).
        * ``window.__VARIABLES__`` / ``window.VISUALKIT_PARAMS`` carry the
          same values to JavaScript, JSON-escaped so they cannot close the
          ``<script>`` block.
        * The page is locked to the design canvas: a ``.visualkit-canvas``
          box of exactly ``canvas_size``, with a ``--vk-scale`` factor so a
          viewport of any size shows it scaled (aspect preserved) rather
          than reflowed.
        """
        w, h = int(canvas_size.width), int(canvas_size.height)
        ratio_w, ratio_h = parse_aspect_ratio(aspect_ratio)

        def raw_sub(match: re.Match[str]) -> str:
            name = match.group(1)
            return _stringify(variables[name]) if name in variables else match.group(0)

        def esc_sub(match: re.Match[str]) -> str:
            name = match.group(1)
            return (
                html_lib.escape(_stringify(variables[name]), quote=True)
                if name in variables
                else match.group(0)
            )

        # Triple-brace first so the double-brace pattern can't half-match it.
        prepared = _RAW_PLACEHOLDER.sub(raw_sub, raw_html)
        prepared = _PLACEHOLDER.sub(esc_sub, prepared)

        vars_json = _json_for_script(variables)
        injected_script = (
            '<script id="visualkit-variables">\n'
            f"window.__VARIABLES__ = {vars_json};\n"
            "window.VISUALKIT_PARAMS = window.__VARIABLES__;\n"
            f"window.VISUALKIT_CANVAS = {{width: {w}, height: {h}}};\n"
            "</script>"
        )

        fit_css = ""
        fit_script = ""
        if scale_to_fit:
            # The canvas keeps its design pixel size; a single transform scales it to the
            # viewport (contain-fit, centred). Layout inside never reflows.
            fit_css = (
                f".visualkit-canvas {{ position: absolute; left: 50%; top: 50%; width: {w}px; height: {h}px;"
                " transform-origin: center center;"
                " transform: translate(-50%, -50%) scale(var(--vk-scale, 1)); }"
            )
            fit_script = (
                '<script id="visualkit-fit">\n'
                "(function(){\n"
                f"  var W={w}, H={h};\n"
                "  function fit(){\n"
                "    var s = Math.min(window.innerWidth / W, window.innerHeight / H);\n"
                "    document.documentElement.style.setProperty('--vk-scale', String(s));\n"
                "  }\n"
                "  fit(); window.addEventListener('resize', fit);\n"
                "})();\n"
                "</script>"
            )
        injected_style = (
            '<style id="visualkit-viewport-style">\n'
            "html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden;"
            " background-color: transparent; }\n"
            ".visualkit-canvas { box-sizing: border-box; overflow: hidden;"
            f" aspect-ratio: {ratio_w:g} / {ratio_h:g}; }}\n"
            f"{fit_css}\n"
            "</style>"
        )

        base_tag = ""
        if base_dir is not None:
            base_tag = (
                f'<base href="{html_lib.escape(base_dir.resolve().as_uri().rstrip("/") + "/", quote=True)}">'
            )

        injection = "\n".join(
            part for part in (base_tag, injected_style, injected_script, fit_script) if part
        )

        head = _HEAD_OPEN.search(prepared)
        if head:
            prepared = prepared[: head.end()] + "\n" + injection + prepared[head.end() :]
        else:
            html_tag = _HTML_OPEN.search(prepared)
            if html_tag:
                prepared = (
                    prepared[: html_tag.end()] + f"<head>\n{injection}\n</head>" + prepared[html_tag.end() :]
                )
            else:
                prepared = f"<head>\n{injection}\n</head>\n{prepared}"
        return prepared

    # ------------------------------------------------------------------ resolved inputs
    def _resolve_inputs(self, clip: CodedVisualClip) -> dict[str, Any]:
        """Merge clip settings with the visual's manifest; clip settings win."""
        source_ref = clip.source.source
        try:
            entrypoint, manifest, raw_html = load_coded_visual(source_ref)
        except FileNotFoundError as err:
            raise CodedVisualCompileError(f"Coded visual source not found: {source_ref}") from err

        if clip.canvas_size is not None:
            canvas = clip.canvas_size
        else:
            canvas = manifest.canvas_size
        if clip.aspect_ratio is not None:
            aspect = clip.aspect_ratio
        elif manifest.aspect_ratio and clip.canvas_size is None:
            aspect = manifest.aspect_ratio
        else:
            aspect = aspect_ratio_for(canvas.width, canvas.height)

        duration = clip.duration.seconds if clip.duration.seconds > 0 else (manifest.duration or 5.0)
        fps = clip.fps if "fps" in clip.model_fields_set else (manifest.fps or clip.fps)

        variables = clip.get_resolved_variables()
        for name, var in manifest.variables.items():
            if name not in variables:
                variables[name] = var.resolve_value()
        missing = [
            n
            for n, v in {**manifest.variables, **clip.variables}.items()
            if v.required and variables.get(n) is None
        ]
        if missing:
            raise CodedVisualCompileError(
                f"CodedVisualClip '{clip.id}' is missing required variable(s): {', '.join(sorted(missing))}"
            )

        return {
            "entrypoint": entrypoint,
            "manifest": manifest,
            "raw_html": raw_html,
            "canvas": canvas,
            "aspect": aspect,
            "duration": duration,
            "fps": fps,
            "variables": variables,
        }

    def prepare_bundle(self, clip: CodedVisualClip) -> tuple[Path, str]:
        """Write the prepared, variable-injected page for `clip`. Returns ``(html_path, cache_key)``."""
        info = self._resolve_inputs(clip)
        return self._write_bundle(clip, info)

    def _write_bundle(self, clip: CodedVisualClip, info: dict[str, Any]) -> tuple[Path, str]:
        cache_key = self.compute_cache_key(
            source_content=info["raw_html"],
            variables=info["variables"],
            canvas_size=info["canvas"],
            aspect_ratio=info["aspect"],
            fps=info["fps"],
            duration=info["duration"],
            render_mode=clip.render_mode.value,
            bundle_digest=self._bundle_digest(info["entrypoint"]),
        )
        bundle_dir = self.cache_dir / cache_key
        bundle_dir.mkdir(parents=True, exist_ok=True)
        target_html = bundle_dir / "index.html"
        target_html.write_text(
            self.prepare_html(
                raw_html=info["raw_html"],
                variables=info["variables"],
                canvas_size=info["canvas"],
                aspect_ratio=info["aspect"],
                base_dir=info["entrypoint"].parent,
                scale_to_fit=clip.auto_scale,
            ),
            encoding="utf-8",
        )
        return target_html, cache_key

    # ------------------------------------------------------------------ rendering
    @staticmethod
    def _find_chrome_executable() -> str | None:
        """Kept for backwards compatibility; see `visualkit.coded_visual.browser.find_chrome`."""
        return browser.find_chrome()

    def render_to_image(self, clip: CodedVisualClip, *, force: bool = False) -> Path:
        """Render `clip` to a single PNG at its design size and record it as the clip's media."""
        info = self._resolve_inputs(clip)
        target_html, cache_key = self._write_bundle(clip, info)
        out = target_html.parent / "render.png"
        if force or not out.exists():
            width, height = int(info["canvas"].width), int(info["canvas"].height)
            browser.screenshot(target_html, out, width, height, timeout=self.render_timeout)
        clip.media_source = str(out)
        clip.compile_status = CompileStatus.READY
        return out

    def render_to_video(
        self,
        clip: CodedVisualClip,
        output_path: str | Path | None = None,
        fps: float | None = None,
        force: bool = False,
    ) -> Path:
        """Render `clip`'s animation to a video file (see `visualkit.coded_visual.capture`)."""
        from visualkit.coded_visual.capture import capture_video

        info = self._resolve_inputs(clip)
        target_html, cache_key = self._write_bundle(clip, info)
        bundle_dir = target_html.parent
        cached = bundle_dir / "render.mp4"

        if force or not cached.exists():
            if shutil.which(self.ffmpeg) is None:
                raise CodedVisualCompileError("ffmpeg was not found on PATH; it is required to encode video.")
            capture_video(
                html_path=target_html,
                out_file=cached,
                width=int(info["canvas"].width),
                height=int(info["canvas"].height),
                duration=info["duration"],
                fps=fps or info["fps"],
                ffmpeg=self.ffmpeg,
                timeout=self.render_timeout,
            )

        out = cached
        if output_path is not None:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out)
        clip.media_source = str(out)
        clip.compile_status = CompileStatus.READY
        return out

    def preview_frame(self, clip: CodedVisualClip, time: float = 0.0, *, force: bool = False) -> Path:
        """Render a single frame of `clip` at virtual time `time` seconds, without
        encoding a video and without affecting `clip.media_source`/`compile_status`.

        Cheap way to check an individual instant of an animated coded visual
        (e.g. mid-way through its motion) before committing to a full
        `render_to_video`/`compile()` call. Needs the optional `playwright`
        package, same as `render_to_video`; still visuals can also just use
        `render_to_image` (no browser-clock stepping needed for a static page).
        Cached per `(cache_key, time)` under the bundle dir, so repeated
        previews of the same frame are free.
        """
        from visualkit.coded_visual.capture import capture_frame

        info = self._resolve_inputs(clip)
        target_html, cache_key = self._write_bundle(clip, info)
        # Slug the timestamp into the filename (3dp is sub-frame precision at any
        # realistic fps) so distinct preview times don't collide or overwrite.
        out = target_html.parent / f"preview_{max(0.0, time):.3f}.png"
        if force or not out.exists():
            width, height = int(info["canvas"].width), int(info["canvas"].height)
            capture_frame(target_html, out, width, height, time=time, timeout=self.render_timeout)
        return out

    def is_animated(self, clip: CodedVisualClip) -> bool:
        """Decide whether `clip` needs video (True) or a still image (False).

        Precedence: the clip's explicit ``render_mode``; the visual's own
        ``animated`` manifest/meta flag; otherwise the page is rendered at
        two different virtual times and the frames compared.
        """
        if clip.render_mode == RenderMode.IMAGE:
            return False
        if clip.render_mode == RenderMode.VIDEO:
            return True
        info = self._resolve_inputs(clip)
        declared = info["manifest"].animated
        if declared is not None:
            return declared
        from visualkit.coded_visual.capture import detect_motion

        target_html, _ = self._write_bundle(clip, info)
        return detect_motion(
            target_html,
            int(info["canvas"].width),
            int(info["canvas"].height),
            timeout=self.render_timeout,
        )

    def compile(
        self,
        clip: CodedVisualClip,
        force: bool = False,
        render_video: bool | None = None,
    ) -> str:
        """Render `clip` to media and return the media path.

        `render_video`: ``True`` forces video, ``False`` forces a still image,
        ``None`` (default) follows the clip's ``render_mode`` (auto-detecting
        motion). The result is always a real media file -- a PNG or a video --
        never the intermediate HTML.
        """
        clip.compile_status = CompileStatus.COMPILING
        try:
            if render_video is None:
                animated = self.is_animated(clip)
            else:
                animated = render_video
            path = (
                self.render_to_video(clip, force=force)
                if animated
                else self.render_to_image(clip, force=force)
            )
            return str(path)
        except CodedVisualCompileError:
            clip.compile_status = CompileStatus.FAILED
            raise
        except Exception as err:
            clip.compile_status = CompileStatus.FAILED
            raise CodedVisualCompileError(f"Failed to compile CodedVisualClip '{clip.id}': {err}") from err
