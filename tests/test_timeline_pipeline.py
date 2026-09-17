from pathlib import Path

import pytest

from visualkit.engine import TimelinePipeline
from visualkit.models import (
    AudioClip,
    CodedVisualClip,
    CompoundClip,
    ExposedParameter,
    MediaClip,
    Size,
    Source,
    TextClip,
    Timeline,
    Variable,
)
from visualkit.utils.time import Time


@pytest.fixture
def sample_template_html(tmp_path: Path) -> Path:
    html_file = tmp_path / "graphic.html"
    html_file.write_text(
        """<!DOCTYPE html>
<html>
<head>
    <meta name="aspect-ratio" content="16:9">
    <meta name="canvas-size" content="1920x1080">
</head>
<body>
    <h1>{{ metric }}</h1>
</body>
</html>
""",
        encoding="utf-8",
    )
    return html_file


def test_resolve_variables_nested():
    # Inner-most timeline
    deepest = Timeline()
    deepest.add_clip(
        CodedVisualClip(
            id="deep_cv",
            source="mock.html",
            variables={"title": Variable(name="title", default="Deep Default")},
        )
    )

    inner_compound = CompoundClip(
        id="inner_comp",
        inner_timeline=deepest,
        exposed_parameters=[
            ExposedParameter(
                name="sub_title",
                target_clip_id="deep_cv",
                target_variable="title",
            )
        ],
    )

    middle = Timeline()
    middle.add_clip(inner_compound)

    outer_compound = CompoundClip(
        id="outer_comp",
        inner_timeline=middle,
        exposed_parameters=[
            ExposedParameter(
                name="headline",
                target_clip_id="inner_comp",
                target_variable="sub_title",
            )
        ],
        parameters={"headline": "Updated From Top"},
    )

    root = Timeline()
    root.add_clip(outer_compound)

    pipeline = TimelinePipeline()
    pipeline.resolve_variables(root)

    _, target_clip = deepest.get_clip("deep_cv")
    assert target_clip.get_resolved_variables()["title"] == "Updated From Top"


def test_flatten_compound_timeline(sample_template_html: Path):
    # 1. Build an inner timeline with video and audio tracks
    inner = Timeline()
    cv_clip = CodedVisualClip(
        id="infographic_1",
        source=str(sample_template_html),
        timeline_start=Time.from_seconds(1),
        duration=Time.from_seconds(3),
        variables={"metric": "99%"},
    )
    inner.add_clip(cv_clip, track_index=0)

    overlay_text = TextClip(
        id="overlay_text",
        text="Subtitle",
        timeline_start=Time.from_seconds(0.5),
        duration=Time.from_seconds(2),
    )
    inner.add_clip(overlay_text, track_index=1)

    inner_audio = AudioClip(
        id="sfx_whoosh",
        source=Source(source="whoosh.wav"),
        timeline_start=Time.from_seconds(0.5),
        duration=Time.from_seconds(1),
    )
    inner_audio.audio_properties.volume = 0.8
    inner.add_clip(inner_audio, track_index=0)

    # 2. Wrap inside a CompoundClip starting at 4 seconds on the root timeline
    compound = CompoundClip(
        id="comp_section",
        timeline_start=Time.from_seconds(4),
        duration=Time.from_seconds(5),
        inner_timeline=inner,
    )

    root = Timeline()
    # Initial intro clip on root track 0
    root.add_clip(TextClip(id="intro_title", text="Welcome", duration=Time.from_seconds(4)))
    root.add_clip(compound)

    # Adjust compound companion audio volume
    root.audio_tracks[0].clips[0].volume = 0.5

    # 3. Flatten the timeline
    flattened = root.flatten()

    # Verify no CompoundClip or CodedVisualClip remain
    for track in flattened.all_tracks:
        for clip in track.clips:
            assert clip.clip_type not in ("compound", "compound_audio", "coded_visual")

    # Check flattened video tracks
    assert len(flattened.video_tracks) >= 2

    # Track 0: intro_title (0s) + resolved media from infographic (4s + 1s = 5s)
    v0_clips = flattened.video_tracks[0].clips
    assert len(v0_clips) == 2
    assert v0_clips[0].id == "intro_title"
    assert v0_clips[0].timeline_start.seconds == 0.0

    media_clip = v0_clips[1]
    assert isinstance(media_clip, MediaClip)
    assert media_clip.timeline_start.seconds == 5.0  # 4s (compound start) + 1s (inner start)
    assert media_clip.duration.seconds == 3.0
    assert media_clip.source.source.endswith("index.html")

    # Track 1: expanded overlay text (4s + 0.5s = 4.5s)
    v1_clips = flattened.video_tracks[1].clips
    assert len(v1_clips) == 1
    assert v1_clips[0].id == "overlay_text"
    assert v1_clips[0].timeline_start.seconds == 4.5

    # Audio Track 0: whoosh sfx (4s + 0.5s = 4.5s) with volume 0.8 * 0.5 = 0.4
    a0_clips = flattened.audio_tracks[0].clips
    assert len(a0_clips) == 1
    assert a0_clips[0].id == "sfx_whoosh"
    assert a0_clips[0].timeline_start.seconds == 4.5
    assert pytest.approx(a0_clips[0].audio_properties.volume) == 0.4

    # Ensure no track timing errors
    errors = flattened.validate_tracks()
    assert not errors
