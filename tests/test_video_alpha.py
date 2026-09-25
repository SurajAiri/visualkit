"""Animated coded visuals keep their transparency all the way into the exported video.

`capture_video` used to encode H.264 `yuv420p`, which flattens transparency to black. It now
writes lossless FFV1 `yuva420p` in Matroska, and the exporter composites it like any overlay.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import visualkit as vk
from visualkit.coded_visual import browser, capture
from visualkit.coded_visual import compiler as compiler_module
from visualkit.coded_visual.compiler import CodedVisualCompiler

try:
    import playwright  # noqa: F401

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

needs_stack = pytest.mark.skipif(
    not (browser.find_chrome() and HAS_PLAYWRIGHT and shutil.which("ffmpeg")),
    reason="needs Chrome + playwright + ffmpeg",
)

# A blue bar growing left to right over a *transparent* page.
BAR = """<!DOCTYPE html><html><head>
<meta name="canvas-size" content="200x100">
<style>#b{position:absolute;left:0;top:0;height:100px;width:0;background:%s;
animation:g 2s linear forwards}@keyframes g{from{width:0}to{width:200px}}</style>
</head><body><div id="b"></div></body></html>"""

ODD = """<!DOCTYPE html><html><head><meta name="canvas-size" content="101x77">
<style>#b{position:absolute;inset:0;background:#f00;animation:g 1s linear forwards}
@keyframes g{from{opacity:1}to{opacity:.99}}</style></head><body><div id="b"></div></body></html>"""


def _probe(path: Path, entries: str) -> list[str]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            entries,
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return out.split(",")


def _frame(video: Path, t: float, pix_fmt="rgba") -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-"],
        capture_output=True,
        check=True,
    ).stdout
    w, h = (int(v) for v in _probe(video, "stream=width,height")[:2])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4 if pix_fmt == "rgba" else 3).astype(int)


@pytest.fixture
def compiler(tmp_path):
    return CodedVisualCompiler(cache_dir=tmp_path / "cache")


@needs_stack
class TestCompiledVideoKeepsAlpha:
    def _clip(self, tmp_path, html, dur=2):
        (tmp_path / "a.html").write_text(html)
        return vk.CodedVisualClip(
            id="a", source=str(tmp_path / "a.html"), duration=vk.Time(dur), render_mode=vk.RenderMode.VIDEO
        )

    def test_default_render_is_lossless_ffv1_mkv_with_alpha(self, tmp_path, compiler):
        out = Path(compiler.compile(self._clip(tmp_path, BAR % "#00f")))
        assert out.name == "render.mkv"
        assert _probe(out, "stream=codec_name,pix_fmt") == ["ffv1", "yuva420p"]
        frame = _frame(out, 1.0)
        assert frame[50, 20, 3] == 255  # inside the bar: opaque blue
        assert tuple(frame[50, 20, :3]) == pytest.approx((0, 0, 255), abs=2)
        assert frame[50, 180, 3] == 0  # beyond the bar: fully transparent

    def test_partial_alpha_survives(self, tmp_path, compiler):
        out = Path(compiler.compile(self._clip(tmp_path, BAR % "rgba(0,0,255,0.5)")))
        assert _frame(out, 1.0)[50, 20, 3] == pytest.approx(128, abs=2)

    def test_alpha_false_still_writes_the_flat_h264_mp4(self, tmp_path, compiler):
        out = compiler.render_to_video(self._clip(tmp_path, BAR % "#00f"), alpha=False)
        assert out.name == "render.mp4"
        assert _probe(out, "stream=codec_name")[0] == "h264"

    def test_odd_canvas_keeps_its_size_and_edge_colours(self, tmp_path, compiler):
        """4:2:0 would mix the last odd row/column with padding and shift its colour."""
        out = Path(compiler.compile(self._clip(tmp_path, ODD, dur=1)))
        assert [int(v) for v in _probe(out, "stream=width,height")] == [101, 77]
        assert _probe(out, "stream=pix_fmt") == ["yuva444p"]
        frame = _frame(out, 0.0)
        assert tuple(frame[76, 100, :3]) == pytest.approx((255, 0, 0), abs=3)
        assert frame[76, 100, 3] == pytest.approx(255, abs=3)


@needs_stack
class TestExportedVideoComposites:
    def test_transparent_regions_show_what_is_underneath(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # keep the default coded-visual cache out of the repo
        Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(tmp_path / "red.png")
        (tmp_path / "bar.html").write_text(BAR % "#00f")

        timeline = vk.Timeline()
        timeline.add_clip(
            vk.MediaClip(id="bg", source=str(tmp_path / "red.png"), duration=vk.Time(2)), track_index=0
        )
        timeline.add_clip(
            vk.CodedVisualClip(
                id="bar",
                source=str(tmp_path / "bar.html"),
                duration=vk.Time(2),
                render_mode=vk.RenderMode.VIDEO,
            ),
            track_index=1,
        )
        out = timeline.export_to_video(tmp_path / "o.mp4", fps=10, resolution=(200, 100))
        frame = _frame(out, 1.0, "rgb24")
        assert tuple(frame[50, 20]) == pytest.approx((0, 0, 255), abs=12)  # bar
        assert tuple(frame[50, 180]) == pytest.approx((255, 0, 0), abs=12)  # red shows through

    def test_partial_alpha_blends_with_the_background(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(tmp_path / "red.png")
        (tmp_path / "bar.html").write_text(BAR % "rgba(0,0,255,0.5)")

        timeline = vk.Timeline()
        timeline.add_clip(
            vk.MediaClip(id="bg", source=str(tmp_path / "red.png"), duration=vk.Time(2)), track_index=0
        )
        timeline.add_clip(
            vk.CodedVisualClip(
                id="bar",
                source=str(tmp_path / "bar.html"),
                duration=vk.Time(2),
                render_mode=vk.RenderMode.VIDEO,
            ),
            track_index=1,
        )
        out = timeline.export_to_video(tmp_path / "o.mp4", fps=10, resolution=(200, 100))
        # 50% blue over red -> (127, 0, 128)
        assert tuple(_frame(out, 1.0, "rgb24")[50, 20]) == pytest.approx((127, 0, 128), abs=12)


class TestFormatIsPartOfTheCacheKey:
    def test_key_changes_with_the_video_format_version(self, monkeypatch):
        args = dict(
            source_content="x",
            variables={},
            canvas_size=vk.Size(width=10, height=10),
            aspect_ratio="16:9",
            fps=30,
            duration=1,
        )
        before = CodedVisualCompiler.compute_cache_key(**args)
        monkeypatch.setattr(compiler_module, "VIDEO_FORMAT_VERSION", "something-else")
        assert CodedVisualCompiler.compute_cache_key(**args) != before

    def test_encoder_args_pick_the_right_codec(self):
        assert "yuva420p" in capture.encoder_args(True, 100, 76)
        assert "yuva444p" in capture.encoder_args(True, 101, 76)
        assert "ffv1" in capture.encoder_args(True)
        assert "libx264" in capture.encoder_args(False)
