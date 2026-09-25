import contextlib
import hashlib
import html
import logging
import shutil
import subprocess
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any

from visualkit.exporters._ffmpeg import filter_script_option, filtergraph_script
from visualkit.exporters._render_plan import build_clip_stage, build_static_stage
from visualkit.exporters.base import BaseExporter
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.media import MediaClip
from visualkit.models.clips.text import TEXT_REFERENCE_HEIGHT, TextClip
from visualkit.models.clips.visual import Transform, VisualClip
from visualkit.models.timeline import Timeline
from visualkit.utils.exceptions import BrowserNotFoundError, ExportError, MissingSourceError, VisualKitError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _file_has_audio_stream(path: str) -> bool:
    """Probe whether a media file has at least one audio stream, via
    `ffprobe`. Needed because `MediaClip.source_audio` only controls
    whether an *existing* embedded audio stream should be included --
    it can't turn a genuinely video-only file into one that has audio.
    Mapping `N:a` from an input with no audio stream at all is an ffmpeg
    hard error, so this must be checked before attempting to map it.
    Cached since the same source file is commonly referenced by more
    than one clip (e.g. after a split) within one export.
    Returns False (rather than raising) if ffprobe itself is unavailable
    or the file can't be probed, since silently omitting audio when in
    doubt was also the prior (if for the wrong reason) default behavior,
    and it is safer than crashing the whole export over a probe failure.
    """
    if not shutil.which("ffprobe"):
        logger.warning("ffprobe not found on PATH; assuming '%s' has no audio stream.", path)
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return bool(result.stdout.decode("utf-8", errors="replace").strip())


def _atempo_chain(speed: float) -> str:
    """Build an ffmpeg audio filter chain implementing an arbitrary speed
    multiplier via `atempo`.

    `atempo` only accepts a single stage's tempo factor in [0.5, 100.0]
    (see `ffmpeg -h filter=atempo`); values outside that range are
    achieved by chaining multiple `atempo` stages whose product is the
    desired speed (e.g. speed=0.1 -> atempo=0.5,atempo=0.2). This
    decomposes `speed` into a sequence of factors each within [0.5, 100.0].
    """
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")

    stages: list[float] = []
    remaining = speed
    # Repeatedly peel off a factor of at most 100.0 or at least 0.5 until
    # the remaining multiplier itself fits in one stage.
    while remaining > 100.0:
        stages.append(100.0)
        remaining /= 100.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(remaining)

    return ",".join(f"atempo={s:.6f}" for s in stages)


def _transform_filters(transform: Transform, width: int, height: int) -> tuple[str, int, int]:
    """Build the ffmpeg video-filter chain implementing a *static* `transform` for a clip being
    composited onto a `width`x`height` canvas.

    Returns (filter_chain_without_labels, effective_w, effective_h) -- the effective size is what
    the caller needs to compute the overlay x/y, since `overlay`'s own x/y refer to the *scaled*
    frame, not the original source resolution.

    Thin wrapper kept for callers that only have a `Transform`; the real logic (including
    keyframes) lives in `visualkit.exporters._render_plan`, shared with the single-clip preview.
    Order: fit -> zoom -> scale -> rotate -> opacity; position is applied by the caller via `overlay`.
    """
    stage = build_static_stage(transform, width, height)
    assert stage.chain is not None and stage.effective_size is not None  # static stages are single chains
    return stage.chain, stage.effective_size[0], stage.effective_size[1]


class FFmpegVideoExporter(BaseExporter):
    """Renders and composites a Timeline into a standalone video file (MP4/WebM) using FFmpeg."""

    def __init__(
        self,
        fps: float = 30.0,
        resolution: tuple[int, int] = (1920, 1080),
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        asset_resolver: Any = None,
        cache_dir: str | Path = ".visualkit_cache/rendered_text",
    ):
        self.fps = fps
        self.resolution = resolution
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.asset_resolver = asset_resolver
        self.cache_dir = Path(cache_dir)

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

        if "asset_resolver" in kwargs and kwargs["asset_resolver"] is not None:
            self.asset_resolver = kwargs["asset_resolver"]

        # Flatten timeline and compile coded visuals into real video assets

        flattened = timeline.flatten(render_video=None)
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
        audio_labels: list[str] = []

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
            source_start_s = 0.0
            speed = getattr(clip, "speed", 1.0)
            if isinstance(clip, MediaClip):
                resolved_src = self._resolve_source(clip.source.source)
                source_file = Path(resolved_src)
                source_start_s = clip.source.start.seconds
            elif isinstance(clip, TextClip):
                # Render text clip to a styled SVG/PNG for FFmpeg input
                source_file = self._render_text_to_image(clip, width, height)

            if not source_file or not source_file.exists():
                # Previously this only logged a warning and `continue`d,
                # so export() returned a "successful" path silently
                # missing this clip's content. A caller has no cheap way
                # to detect that short of inspecting the video by hand, so
                # this now fails the whole export instead.
                raise MissingSourceError(
                    f"Cannot export: source file for clip '{clip.id}' was not found ({source_file})."
                )

            # Add input. For a MediaClip, -ss before -i seeks to
            # source.start before decoding -- previously source.start was
            # never read at all, so every clip (including the second half
            # of a split/trimmed clip) always replayed its file from the
            # very beginning.
            is_image = source_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")
            if is_image:
                # Loop duration must cover the full source span this clip
                # will read (duration * speed, computed below as
                # source_span_s), not just clip.duration -- otherwise a
                # sped-up TextClip/image would run out of looped frames
                # partway through its own trim.
                loop_span_s = clip.duration.seconds * speed
                cmd.extend(["-loop", "1", "-t", str(loop_span_s), "-i", str(source_file)])
            else:
                if source_start_s > 0:
                    cmd.extend(["-ss", str(source_start_s)])
                cmd.extend(["-i", str(source_file)])

            this_input = input_index
            start_s = clip.timeline_start.seconds
            end_s = start_s + clip.duration.seconds
            # Span of source content to actually read for this clip:
            # duration * speed, since a faster-than-1x clip consumes more
            # source per timeline-second (see the same reasoning in the
            # Resolve exporter's in/out handling). Previously always just
            # `clip.duration.seconds`, so `speed` had no effect on either
            # exporter.
            source_span_s = clip.duration.seconds * speed

            # One shared builder (also used by the single-clip preview) turns the clip's transform and
            # keyframes into filters plus overlay options. Keyframe curves are shifted by `start_s`
            # because ffmpeg's `t` is absolute timeline time (each clip is placed with setpts+start).
            if isinstance(clip, VisualClip):
                stage = build_clip_stage(clip, width, height, clip_start_s=start_s)
            else:
                stage = build_static_stage(Transform(), width, height)

            label_scaled = f"v_scaled_{this_input}"
            label_next = f"v_comp_{this_input}"

            # setpts divides by speed (not multiplies): a clip playing at
            # speed=2 should show 2 seconds of source content in 1 second
            # of timeline time, i.e. its presentation timestamps need to
            # run twice as fast, which is PTS/2 not PTS*2. Previously
            # there was no speed-aware term here at all, so `speed` had no
            # effect on playback rate.
            prefix = f"trim=duration={source_span_s},setpts=(PTS-STARTPTS)/{speed}+{start_s}/TB,"
            filter_complex.extend(stage.statements(f"{this_input}:v", label_scaled, str(this_input), prefix))

            # Overlay onto composite
            filter_complex.append(
                f"{current_video_label}[{label_scaled}]overlay="
                f"{stage.overlay_options}:enable='between(t,{start_s},{end_s})'[{label_next}]"
            )
            current_video_label = f"[{label_next}]"

            # A MediaClip's own embedded audio (e.g. a video file's
            # soundtrack) is pulled from the *same* input's `:a` stream --
            # not a second `-i` of the same file -- since ffmpeg indexes
            # audio/video streams of one input together. Previously
            # nothing here ever referenced `{this_input}:a}`, so a video's
            # own audio was always silently dropped from the export even
            # when the source file had a soundtrack.
            source_audio = getattr(clip, "source_audio", None)
            if (
                isinstance(clip, MediaClip)
                and source_audio is not None
                and not source_audio.muted
                and not is_image
                and _file_has_audio_stream(str(source_file))
            ):
                embedded_label = self._add_audio_stream(
                    filter_complex,
                    stream_ref=f"{this_input}:a",
                    volume=source_audio.volume,
                    start_s=start_s,
                    source_start_s=0.0,  # already consumed via -ss on this input, above
                    span_s=source_span_s,
                    speed=speed,
                    label_suffix=f"embed_{this_input}",
                )
                audio_labels.append(embedded_label)

            input_index += 1

        # Process Audio Inputs
        for a_clip in audio_items:
            resolved_a_src = self._resolve_source(a_clip.source.source)
            source_file = Path(resolved_a_src)
            if not source_file.exists():
                raise MissingSourceError(
                    f"Cannot export: source file for audio clip '{a_clip.id}' was not found ({source_file})."
                )

            source_start_s = a_clip.source.start.seconds
            speed = a_clip.speed
            source_span_s = a_clip.duration.seconds * speed

            if source_start_s > 0:
                cmd.extend(["-ss", str(source_start_s)])
            cmd.extend(["-i", str(source_file)])

            vol = a_clip.audio_properties.volume if not a_clip.audio_properties.muted else 0.0
            a_label = self._add_audio_stream(
                filter_complex,
                stream_ref=f"{input_index}:a",
                volume=vol,
                start_s=a_clip.timeline_start.seconds,
                source_start_s=0.0,  # already consumed via -ss above
                span_s=source_span_s,
                speed=speed,
                label_suffix=f"a_{input_index}",
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
        # The filtergraph goes through a script file rather than the command line: keyframed clips
        # emit expressions that grow with the keyframe count and would overflow the OS argument
        # limit. The file is written just before ffmpeg runs and always removed afterwards.
        graph = ";".join(filter_complex)
        graph_arg_index: int | None = None
        if graph:
            graph_arg_index = len(cmd) + 1
            cmd.extend([filter_script_option(cmd[0]), ""])

        if current_video_label == "[0:v]":
            cmd.extend(["-map", "0:v"])
        else:
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

        # Encode to a sibling temp file and rename on success, so a failed or
        # interrupted export never leaves a truncated file at the user's path
        # (or overwrites a previous good export with a broken one).
        tmp_path = out_path.with_name(f".{out_path.stem}.part{out_path.suffix}")
        cmd[-1] = str(tmp_path)

        with contextlib.ExitStack() as stack:
            if graph_arg_index is not None:
                script = stack.enter_context(
                    filtergraph_script(graph, directory=out_path.parent, stem=out_path.stem)
                )
                cmd[graph_arg_index] = str(script)
            try:
                result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except FileNotFoundError as err:
                raise ExportError(
                    f"Cannot export: the '{cmd[0]}' executable was not found. "
                    "Install FFmpeg and make sure it is on PATH."
                ) from err

        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            if tmp_path.exists():
                tmp_path.unlink()
            tail = "\n".join(stderr_text.strip().splitlines()[-8:]) or "(ffmpeg produced no error output)"
            raise ExportError(
                f"FFmpeg failed (exit {result.returncode}) while exporting to {out_path.name}:\n{tail}",
                returncode=result.returncode,
                stderr=stderr_text,
                command=cmd,
            )

        tmp_path.replace(out_path)
        return out_path

    @staticmethod
    def _add_audio_stream(
        filter_complex: list[str],
        *,
        stream_ref: str,
        volume: float,
        start_s: float,
        source_start_s: float,
        span_s: float,
        speed: float,
        label_suffix: str,
    ) -> str:
        """Build the audio filter chain for one audio stream (a standalone
        AudioClip or a MediaClip's own embedded track) and append it to
        `filter_complex`. Returns the output label.

        Applies, in order: atrim (source.start/duration -- previously
        never applied, so e.g. a 2s AudioClip trimmed from a 6s file
        played the whole 6s), speed via an atempo chain (previously
        ignored for audio the same way it was for video), volume/mute,
        and adelay to place it at its timeline start.
        """
        label = f"[a_{label_suffix}]"
        stages = [f"[{stream_ref}]"]
        parts: list[str] = []

        if source_start_s > 0 or span_s > 0:
            trim = f"atrim=start={source_start_s}"
            if span_s > 0:
                trim += f":duration={span_s}"
            parts.append(trim)
            parts.append("asetpts=PTS-STARTPTS")

        if speed != 1.0:
            parts.append(_atempo_chain(speed))

        parts.append(f"volume={volume}")

        start_ms = int(round(start_s * 1000))
        if start_ms > 0:
            parts.append(f"adelay={start_ms}|{start_ms}")

        filter_complex.append("".join(stages) + ",".join(parts) + label)
        return label

    @staticmethod
    def _text_html(clip: TextClip, width: int, height: int) -> str:
        """Standalone HTML for a TextClip, honouring every `TextStyle` field.

        All user-controlled strings are HTML-escaped; `font_family`, colors and
        weight are additionally validated by `TextStyle` itself, so none of them
        can break out of the inline style attribute.
        """
        style = clip.style
        scale = height / TEXT_REFERENCE_HEIGHT
        font_px = max(1, round(style.font_size * scale))
        wrapped_lines = textwrap.wrap(str(clip.text), width=40, replace_whitespace=False) or [str(clip.text)]
        safe_text = "<br>".join(html.escape(line) for line in wrapped_lines)
        justify = {"left": "flex-start", "center": "center", "right": "flex-end"}[style.alignment.value]
        family = html.escape(style.font_family, quote=True)
        bg = (
            f"background:{html.escape(style.background_color, quote=True)};" if style.background_color else ""
        )
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            '<body style="margin:0;padding:0;background:transparent;'
            f"width:{width}px;height:{height}px;display:flex;align-items:center;"
            f'justify-content:{justify};">'
            f"<div style=\"font-family:'{family}',system-ui,-apple-system,sans-serif;"
            f"font-size:{font_px}px;font-weight:{html.escape(style.weight, quote=True)};"
            f"color:{html.escape(style.color, quote=True)};text-align:{style.alignment.value};"
            f'{bg}padding:0 5vw;max-width:90vw;overflow-wrap:break-word;line-height:1.2;">'
            f"{safe_text}</div></body></html>"
        )

    def _render_text_to_image(self, clip: TextClip, width: int, height: int) -> Path:
        """Render a TextClip to a transparent PNG for FFmpeg compositing.

        The cache filename is a hash of everything that affects the pixels
        (text, full style, canvas size) -- *not* the clip id -- so editing a
        clip's text can never serve a stale image, and two clips with
        identical text/style share one render.
        """
        from visualkit.coded_visual import browser

        html_content = self._text_html(clip, width, height)
        digest = hashlib.sha256(f"{width}x{height}\0{html_content}".encode()).hexdigest()[:24]

        cache_dir = self.cache_dir.resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        html_file = cache_dir / f"text_{digest}.html"
        out_png = cache_dir / f"text_{digest}.png"
        if out_png.exists():
            return out_png

        html_file.write_text(html_content, encoding="utf-8")
        try:
            browser.screenshot(html_file, out_png, width, height)
        except BrowserNotFoundError as err:
            raise RuntimeError(
                f"Cannot render TextClip '{clip.id}' to an image: no Google Chrome or Chromium "
                "executable was found. Text clips need a headless browser to rasterize; install "
                "Chrome/Chromium, set VISUALKIT_CHROME, or avoid TextClips with FFmpegVideoExporter."
            ) from err
        return out_png
