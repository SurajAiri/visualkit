"""Render a single `MediaClip` or `TextClip` in isolation to a still PNG.

Both `MediaClip.preview_image()` and `TextClip.preview_image()` delegate to
the functions in this module rather than reimplementing rendering, so a
clip's own preview and its real per-export render (`FFmpegVideoExporter`)
can never drift apart -- the same relationship `CodedVisualClip.preview_image()`
has with `CodedVisualCompiler.render_to_image`.

This draws exactly what `FFmpegVideoExporter` would draw for this one clip
alone -- its own `Transform` on a black canvas of the same size the exporter
uses -- stopped after a single frame instead of a full encode. It does *not*
show how the clip looks stacked with any other clip or track: that
composited view has no equivalent yet (a `Timeline`-level frame preview is
tracked separately).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from visualkit.utils.exceptions import ExportError, MissingSourceError

if TYPE_CHECKING:
    from visualkit.models.clips.media import MediaClip
    from visualkit.models.clips.text import TextClip

#: Matches `FFmpegVideoExporter`'s own default export resolution, so a
#: preview taken with no explicit `resolution` matches what a default
#: `timeline.export_to_video()` call would produce.
DEFAULT_PREVIEW_RESOLUTION = (1920, 1080)

# Same still-image suffixes FFmpegVideoExporter.export() treats as looped
# stills rather than something to seek into.
_STILL_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".svg")


def preview_text_image(
    clip: "TextClip",
    *,
    resolution: tuple[int, int] | None = None,
    cache_dir: str | Path | None = None,
) -> Path:
    """Render `clip` to a transparent PNG via the same Chrome-based path
    `FFmpegVideoExporter` uses to rasterize text for export.

    `cache_dir` defaults to the exporter's own rendered-text cache dir (when
    left unset), so previewing a clip and later exporting it can share one
    cached render instead of producing the same PNG twice.
    """
    from visualkit.exporters.video import FFmpegVideoExporter

    width, height = resolution or DEFAULT_PREVIEW_RESOLUTION
    kwargs: dict[str, Any] = {} if cache_dir is None else {"cache_dir": cache_dir}
    exporter = FFmpegVideoExporter(**kwargs)
    return exporter._render_text_to_image(clip, width, height)


def preview_media_image(
    clip: "MediaClip",
    time: float = 0.0,
    *,
    resolution: tuple[int, int] | None = None,
    cache_dir: str | Path | None = None,
    asset_resolver: Any = None,
    ffmpeg: str = "ffmpeg",
    force: bool = False,
    timeout: float = 60.0,
) -> Path:
    """Render one frame of `clip`'s own source, with `clip.transform`
    applied, onto a `resolution` canvas (default: `clip.resolution`), and
    return the PNG path.

    `time` is timeline-relative seconds into the clip (0.0 = its first
    visible frame); it's converted to a source-file offset via
    `clip.source.start` and `clip.speed`, the same way
    `FFmpegVideoExporter.export` reads the same clip. Ignored for an image
    source. Results are cached by a hash of the resolved source, offset,
    canvas size, and transform, so re-previewing an unchanged clip is free.

    Needs `ffmpeg` on PATH (the same requirement `export_to_video` has).
    Raises `MissingSourceError` if the source file can't be found and
    `ExportError` if ffmpeg itself fails.
    """
    from visualkit.exporters.video import FFmpegVideoExporter, _transform_filters

    width, height = resolution or clip.resolution

    resolved = FFmpegVideoExporter(asset_resolver=asset_resolver)._resolve_source(clip.source.source)
    source_file = Path(resolved)
    if not source_file.exists():
        raise MissingSourceError(
            f"Cannot preview MediaClip '{clip.id}': source file not found ({source_file})."
        )

    resolved_cache_dir = Path(cache_dir or ".visualkit_cache/media_previews").resolve()
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)

    is_image = source_file.suffix.lower() in _STILL_IMAGE_SUFFIXES
    # An image has no timeline of its own, so there's nothing to seek into
    # (matches how CodedVisualClip.to_media_clip() treats a still source).
    source_offset_s = 0.0 if is_image else clip.source.start.seconds + max(0.0, time) * clip.speed

    transform_chain, eff_w, eff_h = _transform_filters(clip.transform, width, height)
    # Same conversion FFmpegVideoExporter.export() uses: overlay's x/y are
    # the top-left corner of the (already scaled) frame, while
    # Transform.position is a center-relative offset.
    overlay_x = (width - eff_w) / 2 + clip.transform.position.x
    overlay_y = (height - eff_h) / 2 + clip.transform.position.y

    digest = hashlib.sha256(
        "\0".join(
            [
                str(source_file),
                f"{source_offset_s:.3f}",
                f"{width}x{height}",
                clip.transform.model_dump_json(),
            ]
        ).encode()
    ).hexdigest()[:24]
    out_png = resolved_cache_dir / f"preview_{digest}.png"
    if out_png.exists() and not force:
        return out_png

    if shutil.which(ffmpeg) is None:
        raise RuntimeError(
            f"Cannot preview MediaClip '{clip.id}': the '{ffmpeg}' executable was not found on PATH. "
            "Install FFmpeg and make sure it is on PATH."
        )

    filter_complex = f"[1:v]{transform_chain}[fg];[0:v][fg]overlay=x={overlay_x}:y={overlay_y}[out]"
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}",
    ]
    if is_image:
        cmd += ["-loop", "1", "-i", str(source_file)]
    else:
        if source_offset_s > 0:
            cmd += ["-ss", str(source_offset_s)]
        cmd += ["-i", str(source_file)]
    cmd += ["-filter_complex", filter_complex, "-map", "[out]", "-frames:v", "1"]

    # Encode to a sibling temp file and rename on success, so a failed or
    # interrupted preview never leaves a broken/partial PNG at the cache path.
    tmp_out = out_png.with_suffix(".part.png")
    cmd.append(str(tmp_out))

    try:
        result = subprocess.run(cmd, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired as err:
        if tmp_out.exists():
            tmp_out.unlink()
        raise ExportError(
            f"FFmpeg did not finish previewing MediaClip '{clip.id}' within {timeout:g}s (killed)."
        ) from err

    if result.returncode != 0 or not tmp_out.exists():
        stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        if tmp_out.exists():
            tmp_out.unlink()
        tail = "\n".join(stderr_text.strip().splitlines()[-8:]) or "(ffmpeg produced no error output)"
        raise ExportError(
            f"FFmpeg failed (exit {result.returncode}) while previewing MediaClip '{clip.id}':\n{tail}",
            returncode=result.returncode,
            stderr=stderr_text,
            command=cmd,
        )

    tmp_out.replace(out_png)
    return out_png
