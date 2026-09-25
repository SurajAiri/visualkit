"""Shared helpers for tests that export real video with ffmpeg and measure pixels.

Fixtures are solid colours (never `testsrc`): a white rectangle on black has exactly one
bounding box, so position, size and centre can be read straight off the decoded frames.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from visualkit.models import MediaClip, Source, Timeline
from visualkit.models.keyframes import PropertyCurve
from visualkit.utils.time import Time

W, H, FPS = 320, 180, 10


def png(path: Path, size=(W, H), color=(255, 255, 255, 255)) -> Path:
    Image.new("RGBA", size, color).save(path)
    return path


def curve(*points) -> PropertyCurve:
    return PropertyCurve.from_points(points)


def make_clip(source: Path, *, start: float, duration: float, clip_id: str = "c", **kw) -> MediaClip:
    return MediaClip(
        id=clip_id,
        source=Source(source=str(source)),
        timeline_start=Time.from_seconds(start),
        duration=Time.from_seconds(duration),
        **kw,
    )


def render(tmp_path: Path, *clips: MediaClip, resolution=(W, H), fps=FPS) -> np.ndarray:
    """Export the clips (first = bottom track) and decode every frame: shape (n, h, w, 3)."""
    timeline = Timeline()
    for index, clip in enumerate(clips):
        timeline.add_clip(clip, track_index=index)
    out = tmp_path / "out.mp4"
    timeline.export_to_video(out, fps=fps, resolution=resolution)
    w, h = resolution
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(int)


def at(frames: np.ndarray, t: float, fps=FPS) -> np.ndarray:
    return frames[round(t * fps)]


def bbox(frame: np.ndarray, threshold=128):
    """(x0, y0, x1, y1) of the bright (green channel) pixels, or None when the frame is black."""
    ys, xs = np.where(frame[:, :, 1] > threshold)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def size(box):
    return box[2] - box[0], box[3] - box[1]
