import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from visualkit.exporters import DaVinciResolveExporter
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
def mock_video_file(tmp_path: Path) -> Path:
    video_file = tmp_path / "sample_video.mp4"
    video_file.write_bytes(b"dummy video content")
    return video_file


@pytest.fixture
def mock_audio_file(tmp_path: Path) -> Path:
    audio_file = tmp_path / "sample_audio.wav"
    audio_file.write_bytes(b"dummy audio content")
    return audio_file


def test_export_xmeml_multitrack(tmp_path: Path, mock_video_file: Path, mock_audio_file: Path):
    timeline = Timeline()

    # Video track 0
    v0_clip = MediaClip(
        id="video_main",
        source=Source(source=str(mock_video_file)),
        timeline_start=Time.from_seconds(0),
        duration=Time.from_seconds(5),
    )
    timeline.add_clip(v0_clip, track_index=0)

    # Video track 1 (overlay text)
    v1_clip = TextClip(
        id="title_overlay",
        text="Chapter 1",
        timeline_start=Time.from_seconds(2),
        duration=Time.from_seconds(3),
    )
    timeline.add_clip(v1_clip, track_index=1)

    # Audio track 0
    a0_clip = AudioClip(
        id="bg_music",
        source=Source(source=str(mock_audio_file)),
        timeline_start=Time.from_seconds(0),
        duration=Time.from_seconds(8),
    )
    timeline.add_clip(a0_clip, track_index=0)

    output_xml = tmp_path / "resolve_project.xml"
    exported_path = timeline.export_to_resolve(output_xml, fps=30.0)

    assert exported_path == output_xml.resolve()
    assert output_xml.exists()

    # Parse and validate XML structure
    tree = ET.parse(output_xml)
    root = tree.getroot()

    assert root.tag == "xmeml"
    assert root.attrib["version"] == "5"

    sequence = root.find(".//sequence")
    assert sequence is not None
    assert sequence.find("name").text == "VisualKit Sequence"

    # Verify video tracks
    v_tracks = sequence.findall(".//media/video/track")
    assert len(v_tracks) == 2

    # Verify track 0 clipitem
    track0_item = v_tracks[0].find("clipitem")
    assert track0_item.find("name").text == "video_main"
    assert track0_item.find("start").text == "0"
    assert track0_item.find("end").text == "150"  # 5s * 30fps
    assert track0_item.find("file/pathurl").text.startswith("file://")

    # Verify track 1 clipitem (start 2s = 60 frames)
    track1_item = v_tracks[1].find("clipitem")
    assert track1_item.find("name").text == "title_overlay"
    assert track1_item.find("start").text == "60"
    assert track1_item.find("end").text == "150"  # (2 + 3) * 30

    # Verify audio track
    a_tracks = sequence.findall(".//media/audio/track")
    assert len(a_tracks) == 1
    audio_item = a_tracks[0].find("clipitem")
    assert audio_item.find("name").text == "bg_music"
    assert audio_item.find("end").text == "240"  # 8s * 30fps


def test_export_fcpxml_format(tmp_path: Path, mock_video_file: Path):
    timeline = Timeline()
    v_clip = MediaClip(
        id="hero_clip",
        source=Source(source=str(mock_video_file)),
        timeline_start=Time.from_seconds(1),
        duration=Time.from_seconds(4),
    )
    timeline.add_clip(v_clip)

    output_fcpxml = tmp_path / "project.fcpxml"
    exporter = DaVinciResolveExporter(fps=30.0)
    exported_path = exporter.export(timeline, output_fcpxml)

    assert exported_path == output_fcpxml.resolve()
    assert output_fcpxml.exists()

    tree = ET.parse(output_fcpxml)
    root = tree.getroot()
    assert root.tag == "fcpxml"
    assert root.attrib["version"] == "1.10"

    # Check resources
    resources = root.find("resources")
    assert resources is not None
    format_elem = resources.find("format")
    assert format_elem.attrib["id"] == "r1"
    asset_elem = resources.find("asset")
    assert asset_elem is not None
    assert asset_elem.attrib["src"].startswith("file://")

    # Check spine
    clip_elem = root.find(".//spine/clip")
    assert clip_elem is not None
    assert clip_elem.attrib["name"] == "hero_clip"


def test_export_with_compound_and_coded_visual_auto_flattening(tmp_path: Path):
    # Template HTML
    template_html = tmp_path / "infographic.html"
    template_html.write_text("<html><body><h1>Graph</h1></body></html>", encoding="utf-8")

    inner = Timeline()
    inner.add_clip(
        CodedVisualClip(
            id="coded_stat",
            source=str(template_html),
            duration=Time.from_seconds(3),
        )
    )

    compound = CompoundClip(
        id="compound_block",
        timeline_start=Time.from_seconds(2),
        duration=Time.from_seconds(3),
        inner_timeline=inner,
    )

    timeline = Timeline()
    timeline.add_clip(compound)

    # Export directly to DaVinci Resolve format
    output_xml = tmp_path / "flattened_export.xml"
    timeline.export_to_resolve(output_xml, fps=30.0)

    # Verify compound was auto-flattened and coded visual was compiled into media
    tree = ET.parse(output_xml)
    root = tree.getroot()

    clip_names = [elem.text for elem in root.findall(".//clipitem/name")]
    assert "compound_block" not in clip_names
    assert any("coded_stat" in name for name in clip_names)

    # Start frame is 2s * 30fps = 60 frames
    coded_item = next(
        elem for elem in root.findall(".//clipitem") if "coded_stat" in elem.find("name").text
    )
    assert coded_item.find("start").text == "60"
    assert coded_item.find("end").text == "150"
