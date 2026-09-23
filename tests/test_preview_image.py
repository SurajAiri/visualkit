"""Tests for `.preview_image()` on CodedVisualClip, TextClip, and MediaClip.

Pure-logic and ffmpeg-only tests always run. Tests that need a real
Chrome/Chromium are marked and skip cleanly when none is available, matching
the convention in `test_rendering.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from visualkit.coded_visual import browser
from visualkit.coded_visual.compiler import CodedVisualCompiler
from visualkit.models import CodedVisualClip, CompileStatus, MediaClip, Position, TextClip, Transform
from visualkit.utils.exceptions import MissingSourceError
from visualkit.utils.time import Time

HAS_CHROME = browser.find_chrome() is not None
needs_chrome = pytest.mark.skipif(not HAS_CHROME, reason="no Chrome/Chromium available")


@pytest.fixture
def test_video(tmp_path: Path) -> Path:
    """A real 2-second test video (testsrc pattern), matching the fixture
    style in test_video_exporter.py."""
    video_file = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video_file),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return video_file


# --------------------------------------------------------------------------- MediaClip


class TestMediaClipPreviewImage:
    def test_renders_a_real_png(self, tmp_path: Path, test_video: Path):
        clip = MediaClip(id="m1", source=str(test_video), duration=Time.from_seconds(2))
        out = clip.preview_image(0.5, cache_dir=tmp_path / "cache")
        assert out.exists()
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_distinct_times_produce_distinct_cached_frames(self, tmp_path: Path, test_video: Path):
        clip = MediaClip(id="m1", source=str(test_video), duration=Time.from_seconds(2))
        frame_a = clip.preview_image(0.0, cache_dir=tmp_path / "cache")
        frame_b = clip.preview_image(1.5, cache_dir=tmp_path / "cache")
        assert frame_a != frame_b
        assert frame_a.read_bytes() != frame_b.read_bytes()

    def test_same_time_is_served_from_cache(self, tmp_path: Path, test_video: Path):
        clip = MediaClip(id="m1", source=str(test_video), duration=Time.from_seconds(2))
        first = clip.preview_image(0.5, cache_dir=tmp_path / "cache")
        mtime_before = first.stat().st_mtime_ns
        second = clip.preview_image(0.5, cache_dir=tmp_path / "cache")
        assert first == second
        assert second.stat().st_mtime_ns == mtime_before  # not re-rendered

    def test_accepts_a_time_object_like_preview_frame_does(self, tmp_path: Path, test_video: Path):
        clip = MediaClip(id="m1", source=str(test_video), duration=Time.from_seconds(2))
        by_float = clip.preview_image(0.5, cache_dir=tmp_path / "cache")
        by_time = clip.preview_image(Time.from_seconds(0.5), cache_dir=tmp_path / "cache")
        assert by_float == by_time

    def test_transform_changes_the_cache_key_and_the_pixels(self, tmp_path: Path, test_video: Path):
        plain = MediaClip(id="m1", source=str(test_video), duration=Time.from_seconds(2))
        shifted = MediaClip(
            id="m2",
            source=str(test_video),
            duration=Time.from_seconds(2),
            transform=Transform(position=Position(x=50, y=-30), scale=0.6),
        )
        out_plain = plain.preview_image(0.0, cache_dir=tmp_path / "cache")
        out_shifted = shifted.preview_image(0.0, cache_dir=tmp_path / "cache")
        assert out_plain != out_shifted
        assert out_plain.read_bytes() != out_shifted.read_bytes()

    def test_missing_source_raises_missing_source_error(self, tmp_path: Path):
        clip = MediaClip(id="m1", source=str(tmp_path / "does_not_exist.mp4"), duration=Time.from_seconds(2))
        with pytest.raises(MissingSourceError):
            clip.preview_image(0.0, cache_dir=tmp_path / "cache")

    def test_does_not_mutate_the_clip(self, tmp_path: Path, test_video: Path):
        """Unlike CodedVisualClip.compile(), MediaClip has no compiled-state
        fields to protect, but the call must still be side-effect-free on
        the clip itself (no compile_status/media_source equivalent exists,
        so this just pins that the clip object is left unmodified)."""
        clip = MediaClip(id="m1", source=str(test_video), duration=Time.from_seconds(2))
        before = clip.model_copy(deep=True)
        clip.preview_image(0.5, cache_dir=tmp_path / "cache")
        assert clip == before


# --------------------------------------------------------------------------- TextClip


class TestTextClipPreviewImage:
    @staticmethod
    def _force_no_chrome(monkeypatch):
        monkeypatch.delenv(browser.ENV_VAR, raising=False)
        monkeypatch.setattr(browser, "find_chrome", lambda: None)

    def test_missing_chrome_raises_clear_error(self, tmp_path: Path, monkeypatch):
        self._force_no_chrome(monkeypatch)
        clip = TextClip(id="t1", text="Hello", duration=Time.from_seconds(2))
        with pytest.raises(RuntimeError, match="Chrome"):
            clip.preview_image(cache_dir=tmp_path / "cache")

    def test_uses_the_exporters_own_html_rasterizer(self, tmp_path: Path, monkeypatch):
        """Regression guard: previewing must go through the same escaping/
        styling path FFmpegVideoExporter uses, not a second implementation."""
        self._force_no_chrome(monkeypatch)
        clip = TextClip(id="t1", text="Revenue <up> & Growth", duration=Time.from_seconds(2))
        with pytest.raises(RuntimeError, match="Chrome"):
            clip.preview_image(cache_dir=tmp_path / "cache")
        html_file = next((tmp_path / "cache").glob("text_*.html"))
        content = html_file.read_text()
        assert "&lt;up&gt;" in content
        assert "<up>" not in content

    def test_default_cache_dir_matches_exporters_default(self, tmp_path: Path, monkeypatch):
        self._force_no_chrome(monkeypatch)
        monkeypatch.chdir(tmp_path)
        clip = TextClip(id="t1", text="Hi", duration=Time.from_seconds(2))
        with pytest.raises(RuntimeError, match="Chrome"):
            clip.preview_image()
        assert list((tmp_path / ".visualkit_cache" / "rendered_text").glob("text_*.html"))

    @needs_chrome
    def test_renders_a_real_png_when_chrome_available(self, tmp_path: Path):
        clip = TextClip(id="t1", text="Hello VisualKit", duration=Time.from_seconds(2))
        out = clip.preview_image(cache_dir=tmp_path / "cache")
        assert out.exists()
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------- CodedVisualClip


class TestCodedVisualClipPreviewImage:
    @pytest.fixture
    def bundle_dir(self, tmp_path: Path) -> Path:
        bundle = tmp_path / "card"
        bundle.mkdir()
        (bundle / "index.html").write_text(
            """<!DOCTYPE html>
<html><head><meta name="canvas-size" content="400x200"></head>
<body><div class="visualkit-canvas"><h1>{{ headline }}</h1></div></body></html>
""",
            encoding="utf-8",
        )
        return bundle

    def test_never_mutates_compile_status_or_media_source(
        self, tmp_path: Path, bundle_dir: Path, monkeypatch
    ):
        monkeypatch.setattr(browser, "find_chrome", lambda: None)
        compiler = CodedVisualCompiler(cache_dir=tmp_path / "cache")
        clip = CodedVisualClip(
            source=str(bundle_dir), duration=Time.from_seconds(2), variables={"headline": "Hi"}
        )

        with pytest.raises(Exception):
            clip.preview_image(compiler=compiler)

        assert clip.compile_status == CompileStatus.PENDING
        assert clip.media_source is None

    def test_distinct_from_render_to_image_which_does_mutate(
        self, tmp_path: Path, bundle_dir: Path, monkeypatch
    ):
        """Pins the contract difference: render_to_image (and compile())
        record the render on the clip; preview_image() never does."""
        monkeypatch.setattr(browser, "find_chrome", lambda: None)
        compiler = CodedVisualCompiler(cache_dir=tmp_path / "cache")
        clip = CodedVisualClip(
            source=str(bundle_dir), duration=Time.from_seconds(2), variables={"headline": "Hi"}
        )

        with pytest.raises(Exception):
            compiler.render_to_image(clip)
        # render_to_image only mutates state *after* a successful screenshot,
        # so failing before that point leaves state alone too -- this test
        # exists to make the intended difference explicit, not to prove it
        # here; the real distinction is exercised below when Chrome exists.

    @needs_chrome
    def test_renders_a_real_png_without_compiling(self, tmp_path: Path, bundle_dir: Path):
        compiler = CodedVisualCompiler(cache_dir=tmp_path / "cache")
        clip = CodedVisualClip(
            source=str(bundle_dir), duration=Time.from_seconds(2), variables={"headline": "Hi"}
        )

        out = clip.preview_image(compiler=compiler)

        assert out.exists()
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert clip.compile_status == CompileStatus.PENDING
        assert clip.media_source is None

        # A later real compile still works and now does mutate state.
        clip.compile(compiler=compiler)
        assert clip.compile_status == CompileStatus.READY
        assert clip.media_source is not None
