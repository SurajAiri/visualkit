import subprocess
from pathlib import Path

import pytest

from visualkit.exporters import FFmpegVideoExporter
from visualkit.models import (
    AudioClip,
    CodedVisualClip,
    CompoundClip,
    MediaClip,
    Source,
    TextClip,
    Timeline,
)
from visualkit.utils.time import Time


@pytest.fixture
def generate_test_media(tmp_path: Path):
    """Generate real lightweight video and audio files using ffmpeg for testing export."""
    video_file = tmp_path / "sample_video.mp4"
    audio_file = tmp_path / "sample_audio.wav"

    # 1. Generate 2-second test MP4 (color pattern)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=640x360:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video_file),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 2. Generate 2-second test WAV (sine tone)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "pcm_s16le",
            str(audio_file),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return video_file, audio_file


def test_ffmpeg_video_export_multitrack(tmp_path: Path, generate_test_media):
    video_file, audio_file = generate_test_media

    timeline = Timeline()

    # Track 0: Main video clip
    timeline.add_clip(
        MediaClip(
            id="v_main",
            source=Source(source=str(video_file)),
            timeline_start=Time.from_seconds(0),
            duration=Time.from_seconds(2),
        ),
        track_index=0,
    )

    # Track 1: Text overlay clip
    timeline.add_clip(
        TextClip(
            id="title_text",
            text="VisualKit Engine",
            timeline_start=Time.from_seconds(0.5),
            duration=Time.from_seconds(1.5),
        ),
        track_index=1,
    )

    # Audio Track 0: Background tone
    timeline.add_clip(
        AudioClip(
            id="bg_audio",
            source=Source(source=str(audio_file)),
            timeline_start=Time.from_seconds(0),
            duration=Time.from_seconds(2),
        ),
        track_index=0,
    )

    output_mp4 = tmp_path / "final_output.mp4"
    exported_path = timeline.export_to_video(
        output_path=output_mp4,
        resolution=(640, 360),
        fps=30.0,
    )

    assert exported_path == output_mp4.resolve()
    assert output_mp4.exists()
    assert output_mp4.stat().st_size > 1000


def test_coded_visual_render_to_video_and_resolve_export(tmp_path: Path):
    # Template HTML
    template_html = tmp_path / "infographic.html"
    template_html.write_text(
        """<!DOCTYPE html>
<html>
<body style="background:#0f172a;color:#38bdf8;display:flex;align-items:center;
             justify-content:center;height:100vh;">
    <h1 style="font-size:3rem;">{{ metric }}</h1>
</body>

</html>
""",
        encoding="utf-8",
    )

    clip = CodedVisualClip(
        id="cv_stat",
        source=str(template_html),
        duration=Time.from_seconds(2),
        variables={"metric": "99.9%"},
    )

    timeline = Timeline()
    timeline.add_clip(clip)

    # Export to DaVinci Resolve with render_video=True
    output_xml = tmp_path / "resolve_rendered.xml"
    timeline.export_to_resolve(output_xml, render_video=True)

    assert output_xml.exists()
    xml_text = output_xml.read_text(encoding="utf-8")

    # Verify DaVinci Resolve points to an actual .mp4 video rather than .html!
    assert "render.mp4" in xml_text


def test_video_export_with_asset_resolver(tmp_path: Path, generate_test_media):
    from visualkit.engine.asset_resolver import DictAssetResolver

    video_file, audio_file = generate_test_media

    resolver = DictAssetResolver(
        {
            "asset://b_roll": str(video_file),
            "asset://voiceover": str(audio_file),
        }
    )

    timeline = Timeline()
    timeline.add_clip(
        MediaClip(
            id="clip1",
            source=Source(source="asset://b_roll"),
            timeline_start=Time.from_seconds(0),
            duration=Time.from_seconds(2),
        )
    )
    timeline.add_clip(
        AudioClip(
            id="audio1",
            source=Source(source="asset://voiceover"),
            timeline_start=Time.from_seconds(0),
            duration=Time.from_seconds(2),
        )
    )

    output_mp4 = tmp_path / "resolved_output.mp4"
    timeline.export_to_video(output_mp4, fps=30.0, asset_resolver=resolver)

    assert output_mp4.exists()
    assert output_mp4.stat().st_size > 0


class TestRenderTextToImageEscaping:
    """Regression tests for the text-clip-to-HTML rendering step used by
    FFmpegVideoExporter. These test the generated HTML content directly
    (by stopping before the Chrome subprocess call) rather than requiring
    Chrome to be installed in the test environment.
    """

    @staticmethod
    def _force_no_chrome(monkeypatch):
        """Deterministically simulate 'no Chrome installed' regardless of
        what's actually available in the environment running these tests."""
        from visualkit.coded_visual.compiler import CodedVisualCompiler

        monkeypatch.setattr(CodedVisualCompiler, "_find_chrome_executable", staticmethod(lambda: None))

    def test_special_characters_are_html_escaped(self, tmp_path: Path, monkeypatch):
        """Text containing <, >, & must not be interpreted as HTML markup;
        previously it was injected raw into the page."""
        self._force_no_chrome(monkeypatch)
        exporter = FFmpegVideoExporter(cache_dir=tmp_path / "cache")
        clip = TextClip(id="t1", text='Revenue <up> & Growth "2024"', duration=Time.from_seconds(2))

        # No Chrome available -> should raise a clear RuntimeError rather
        # than silently returning the .html file. We still inspect the
        # .html file that was written before the raise, since that's where
        # the escaping bug lived.
        with pytest.raises(RuntimeError, match="Chrome"):
            exporter._render_text_to_image(clip, 1920, 1080)

        html_file = (tmp_path / "cache" / "t1.html").resolve()
        assert html_file.exists()
        content = html_file.read_text()
        assert "<up>" not in content
        assert "&lt;up&gt;" in content
        assert "&amp;" in content

    def test_long_text_is_wrapped_rather_than_left_on_one_line(self, tmp_path: Path, monkeypatch):
        self._force_no_chrome(monkeypatch)
        exporter = FFmpegVideoExporter(cache_dir=tmp_path / "cache")
        long_text = " ".join(["word"] * 30)
        clip = TextClip(id="t2", text=long_text, duration=Time.from_seconds(2))

        with pytest.raises(RuntimeError, match="Chrome"):
            exporter._render_text_to_image(clip, 1920, 1080)

        content = (tmp_path / "cache" / "t2.html").resolve().read_text()
        assert "<br>" in content

    def test_missing_chrome_raises_instead_of_returning_html_as_image(self, tmp_path: Path, monkeypatch):
        """Previously, when Chrome was unavailable, this method returned the
        intermediate .html file itself, which export() would then hand to
        ffmpeg as if it were a video/image input -- a broken, non-obvious
        failure. It must now raise a clear, actionable error instead.
        """
        self._force_no_chrome(monkeypatch)
        exporter = FFmpegVideoExporter(cache_dir=tmp_path / "cache")
        clip = TextClip(id="t3", text="Hello", duration=Time.from_seconds(2))

        with pytest.raises(RuntimeError) as exc_info:
            exporter._render_text_to_image(clip, 1920, 1080)

        assert "Chrome" in str(exc_info.value) or "Chromium" in str(exc_info.value)

    def test_cache_dir_is_configurable(self, tmp_path: Path, monkeypatch):
        """The rendered-text cache directory should be configurable per
        exporter instance rather than a hardcoded relative path tied to the
        caller's current working directory."""
        self._force_no_chrome(monkeypatch)
        custom_cache = tmp_path / "my_custom_cache"
        exporter = FFmpegVideoExporter(cache_dir=custom_cache)
        clip = TextClip(id="t4", text="Hi", duration=Time.from_seconds(2))

        with pytest.raises(RuntimeError, match="Chrome"):
            exporter._render_text_to_image(clip, 1920, 1080)

        assert (custom_cache / "t4.html").exists()

