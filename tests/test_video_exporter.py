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
