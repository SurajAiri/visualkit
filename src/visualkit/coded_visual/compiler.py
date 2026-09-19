import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from visualkit.coded_visual.project import load_coded_visual
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

    @staticmethod
    def _find_chrome_executable() -> str | None:
        """Locate Google Chrome or Chromium executable on the system."""
        import shutil

        # Common macOS paths
        mac_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for p in mac_paths:
            if Path(p).exists():
                return p

        # Search in PATH (Linux / Windows / customized environments)
        for bin_name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(bin_name)
            if found:
                return found
        return None

    def render_to_video(
        self,
        clip: CodedVisualClip,
        output_path: str | Path | None = None,
        fps: float = 30.0,
        force: bool = False,
    ) -> Path:
        """Render the prepared HTML bundle into an actual MP4 video file using headless Chrome and FFmpeg."""
        target_html, cache_key = self.prepare_bundle(clip)
        bundle_dir = target_html.parent
        # A caller-supplied `output_path` is not itself derived from
        # `cache_key`, so its mere existence on disk doesn't prove it was
        # rendered from the *current* variables/state -- it could be a
        # stale file left over from a previous compile of this same clip
        # at a literal path the caller reuses across renders. The
        # actual cache hit/miss signal is whether *this* cache_key's own
        # bundle_dir already has a rendered output; only reuse a
        # caller-supplied output_path once that's confirmed, and copy
        # from the verified cache rather than trusting the path directly.
        default_out_file = bundle_dir / "render.mp4"
        out_file = Path(output_path) if output_path else default_out_file

        if not force and default_out_file.exists():
            if out_file != default_out_file:
                import shutil as _shutil

                out_file.parent.mkdir(parents=True, exist_ok=True)
                _shutil.copyfile(default_out_file, out_file)
            clip.media_source = str(out_file)
            clip.compile_status = CompileStatus.READY
            return out_file

        chrome_bin = self._find_chrome_executable()
        if not chrome_bin:
            raise RuntimeError(
                "Cannot render coded visual to video: Google Chrome or Chromium not found on system."
            )

        duration = clip.duration.seconds if clip.duration and clip.duration.seconds > 0 else 5.0
        width = int(clip.canvas_size.width)
        height = int(clip.canvas_size.height)

        # Render to the cache_key-addressed default location first, so
        # the cache-hit check above (keyed on cache_key, via
        # default_out_file) is always meaningful regardless of what
        # output_path the caller passes; then copy/symlink to the
        # caller's requested path if different.
        self._capture_animated_frames(
            target_html=target_html,
            chrome_bin=chrome_bin,
            bundle_dir=bundle_dir,
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            out_file=default_out_file,
        )

        if out_file != default_out_file:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            import shutil as _shutil

            _shutil.copyfile(default_out_file, out_file)

        clip.media_source = str(out_file)
        clip.compile_status = CompileStatus.READY
        return out_file

    def _capture_animated_frames(
        self,
        *,
        target_html: Path,
        chrome_bin: str,
        bundle_dir: Path,
        width: int,
        height: int,
        duration: float,
        fps: float,
        out_file: Path,
    ) -> None:
        """Capture the coded visual's actual motion over `duration` and
        encode it to `out_file`, instead of screenshotting a single
        instant and looping that one still frame.

        Previously this method took exactly one `--screenshot` and fed
        it to ffmpeg with `-loop 1 -t duration`, so ANY animated HTML/CSS
        (a CSS @keyframes animation, a JS-driven canvas, etc.) exported
        as a frozen still for its entire duration -- there was no
        mechanism to advance time and capture more than one instant.
        This samples `capture_fps` frames evenly across `duration` by
        reloading the page and waiting a computed delay (via Chrome's
        `--virtual-time-budget`, which advances the page's own timers/
        rAF/CSS-animation clock deterministically rather than relying on
        real wall-clock time) before each screenshot, then stitches the
        frame sequence into a video with ffmpeg at the timeline's `fps`.

        Chrome's `--screenshot` flag itself only ever captures a single
        frame per invocation, so one Chrome invocation per sampled frame
        is unavoidable without a more involved CDP (Chrome DevTools
        Protocol) screencast integration; `capture_fps` is deliberately
        lower than typical output `fps` to keep render time reasonable,
        and ffmpeg's own encoder duplicates frames to fill `fps` from
        the sparser capture (motion still advances, just sampled less
        finely than the final encode's frame rate).
        """
        frames_dir = bundle_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for old_frame in frames_dir.glob("frame_*.png"):
            old_frame.unlink()

        # Cap the number of real Chrome launches: each sampled frame is
        # one full headless-Chrome process invocation, so sampling at the
        # full output fps for a long clip would be very slow. 12fps is
        # enough to read most CSS/JS motion as animated rather than
        # janky, while keeping a multi-second clip's render time bounded.
        capture_fps = min(fps, 12.0)
        frame_count = max(1, round(duration * capture_fps))

        for i in range(frame_count):
            # virtual-time-budget advances the page's own clock (CSS
            # animations, rAF callbacks, setTimeout/setInterval) by this
            # many milliseconds before the screenshot is taken, rather
            # than depending on real elapsed wall-clock time -- so the
            # capture is deterministic and not at the mercy of how fast
            # this machine happens to render each frame.
            virtual_time_ms = int(round((i / capture_fps) * 1000))
            frame_file = frames_dir / f"frame_{i:05d}.png"
            chrome_cmd = [
                chrome_bin,
                "--headless=new",
                f"--screenshot={frame_file}",
                f"--window-size={width},{height}",
                "--default-background-color=00000000",
                f"--virtual-time-budget={max(virtual_time_ms, 1)}",
                target_html.as_uri(),
            ]
            subprocess.run(
                chrome_cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Stitch the sampled frame sequence into a video at capture_fps,
        # then let ffmpeg's own fps filter interpolate/duplicate up to
        # the timeline's actual `fps` for the final encode.
        ff_cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(capture_fps),
            "-i",
            str(frames_dir / "frame_%05d.png"),
            "-vf",
            f"fps={fps}",
            "-c:v",
            "libx264",
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            str(out_file),
        ]
        subprocess.run(
            ff_cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def compile(
        self,
        clip: CodedVisualClip,
        force: bool = False,
        render_video: bool = False,
    ) -> str:
        """Compile the clip by preparing the bundle and optionally rendering to video."""
        clip.compile_status = CompileStatus.COMPILING
        try:
            if render_video:
                out_path = self.render_to_video(clip, force=force)
                return str(out_path)

            target_html, cache_key = self.prepare_bundle(clip)
            clip.media_source = str(target_html)
            clip.compile_status = CompileStatus.READY
            return str(target_html)
        except Exception as e:
            clip.compile_status = CompileStatus.FAILED
            raise RuntimeError(f"Failed to compile CodedVisualClip '{clip.id}': {e}") from e
