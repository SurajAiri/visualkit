import shutil
import subprocess
from pathlib import Path
from typing import Any

from visualkit.exporters.base import BaseExporter
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.media import MediaClip
from visualkit.models.clips.text import TextClip
from visualkit.models.timeline import Timeline
from visualkit.utils.time import Time


class FFmpegVideoExporter(BaseExporter):
    """Renders and composites a Timeline into a standalone video file (MP4/WebM) using FFmpeg."""

    def __init__(
        self,
        fps: float = 30.0,
        resolution: tuple[int, int] = (1920, 1080),
        video_codec: str = "libx264",
        audio_codec: str = "aac",
    ):
        self.fps = fps
        self.resolution = resolution
        self.video_codec = video_codec
        self.audio_codec = audio_codec

    def export(
        self,
        timeline: Timeline,
        output_path: str | Path,
        **kwargs: Any,
    ) -> Path:
        """Render the timeline into a video file.

        Automatically resolves variables, compiles coded visuals to video, and flattens the hierarchy.
        """
        out_path = Path(output_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not shutil.which("ffmpeg"):
            raise RuntimeError("FFmpeg executable not found on system PATH.")

        # Flatten timeline and compile coded visuals into real video assets
        flattened = timeline.flatten(render_video=True)
        total_duration = max(flattened.duration.seconds, 1.0)
        width, height = self.resolution

        # Collect video items and audio items
        video_items: list[tuple[int, Any]] = []
        for track_idx, track in enumerate(flattened.video_tracks):
            for clip in track.clips:
                video_items.append((track_idx, clip))

        audio_items: list[AudioClip] = []
        for track in flattened.audio_tracks:
            for clip in track.clips:
                if isinstance(clip, AudioClip):
                    audio_items.append(clip)

        # Build FFmpeg command
        cmd: list[str] = ["ffmpeg", "-y"]
        filter_complex: list[str] = []

        # Input 0: Base background canvas
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={width}x{height}:r={self.fps}:d={total_duration}",
            ]
        )
        current_video_label = "[0:v]"

        input_index = 1

        # Process Video Inputs
        for track_idx, clip in video_items:
            source_file: Path | None = None
            if isinstance(clip, MediaClip):
                source_file = Path(clip.source.source)
            elif isinstance(clip, TextClip):
                # Render text clip to a styled SVG/PNG for FFmpeg input
                source_file = self._render_text_to_image(clip, width, height)

            if not source_file or not source_file.exists():
                continue

            # Add input
            is_image = source_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")
            if is_image:
                cmd.extend(["-loop", "1", "-t", str(clip.duration.seconds), "-i", str(source_file)])
            else:
                cmd.extend(["-i", str(source_file)])

            # Clip filter: scale and set PTS
            start_s = clip.timeline_start.seconds
            end_s = start_s + clip.duration.seconds
            label_scaled = f"v_scaled_{input_index}"
            label_next = f"v_comp_{input_index}"

            filter_complex.append(
                f"[{input_index}:v]trim=duration={clip.duration.seconds},"
                f"setpts=PTS-STARTPTS+{start_s}/TB,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0[{label_scaled}]"
            )

            # Overlay onto composite
            filter_complex.append(
                f"{current_video_label}[{label_scaled}]overlay=enable='between(t,{start_s},{end_s})'[{label_next}]"
            )
            current_video_label = f"[{label_next}]"
            input_index += 1

        # Process Audio Inputs
        audio_labels: list[str] = []
        for a_clip in audio_items:
            source_file = Path(a_clip.source.source)
            if not source_file.exists():
                continue

            cmd.extend(["-i", str(source_file)])
            start_ms = int(round(a_clip.timeline_start.seconds * 1000))
            vol = a_clip.audio_properties.volume if not a_clip.audio_properties.muted else 0.0

            a_label = f"[a_{input_index}]"
            if start_ms > 0:
                filter_complex.append(
                    f"[{input_index}:a]volume={vol},adelay={start_ms}|{start_ms}{a_label}"
                )
            else:
                filter_complex.append(
                    f"[{input_index}:a]volume={vol}{a_label}"
                )
            audio_labels.append(a_label)
            input_index += 1

        # Audio mix
        has_audio = len(audio_labels) > 0
        final_audio_label = ""
        if has_audio:
            if len(audio_labels) == 1:
                final_audio_label = audio_labels[0]
            else:
                joined_audio = "".join(audio_labels)
                filter_complex.append(
                    f"{joined_audio}amix=inputs={len(audio_labels)}:dropout_transition=0[a_out]"
                )
                final_audio_label = "[a_out]"

        # Assemble final command
        if filter_complex:
            cmd.extend(["-filter_complex", ";".join(filter_complex)])

        cmd.extend(["-map", current_video_label])
        if has_audio:
            cmd.extend(["-map", final_audio_label, "-c:a", self.audio_codec])
        else:
            cmd.extend(["-an"])

        cmd.extend(
            [
                "-c:v",
                self.video_codec,
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(total_duration),
                str(out_path),
            ]
        )

        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return out_path

    @staticmethod
    def _render_text_to_image(clip: TextClip, width: int, height: int) -> Path:
        """Render a TextClip to a transparent PNG snapshot using Chrome for FFmpeg compositing."""
        from visualkit.coded_visual.compiler import CodedVisualCompiler

        font_size = getattr(clip.style, "font_size", 64) if hasattr(clip, "style") else 64
        font_color = getattr(clip.style, "color", "#ffffff") if hasattr(clip, "style") else "#ffffff"

        html_content = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:transparent;width:100vw;height:100vh;""" \
                       f"""display:flex;align-items:center;justify-content:center;">
    <h1 style="margin:0;font-family:system-ui,-apple-system,sans-serif;""" \
                       f"""font-size:{font_size}px;color:{font_color};text-align:center;">
        {clip.text}
    </h1>
</body>
</html>"""

        cache_dir = Path(".visualkit_cache/rendered_text").resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        html_file = cache_dir / f"{clip.id}.html"
        out_png = cache_dir / f"{clip.id}.png"
        html_file.write_text(html_content, encoding="utf-8")


        chrome_bin = CodedVisualCompiler._find_chrome_executable()
        if chrome_bin:
            chrome_cmd = [
                chrome_bin,
                "--headless=new",
                f"--screenshot={out_png}",
                f"--window-size={width},{height}",
                "--default-background-color=00000000",
                html_file.as_uri(),
            ]
            subprocess.run(
                chrome_cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return out_png

        return html_file


