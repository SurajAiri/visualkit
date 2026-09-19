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

    # Check flattened video tracks. The compound reserves its own block of
    # destination tracks distinct from the outer track it sits on (track
    # 0, alongside intro_title) -- previously the compound's inner track 0
    # collided with whatever else shared that same outer track index, so
    # intro_title and the compound's own inner track 0 content would have
    # incorrectly landed on the same flattened track together.
    assert len(flattened.video_tracks) >= 3

    # Track 0: only intro_title -- the outer track the compound clip itself
    # sits on, untouched by the compound's own inner content.
    v0_clips = flattened.video_tracks[0].clips
    assert len(v0_clips) == 1
    assert v0_clips[0].id == "intro_title"
    assert v0_clips[0].timeline_start.seconds == 0.0

    # Track 1: the compound's inner track 0 (the infographic), in its own
    # reserved slot.
    v1_clips = flattened.video_tracks[1].clips
    assert len(v1_clips) == 1
    media_clip = v1_clips[0]
    assert isinstance(media_clip, MediaClip)
    assert media_clip.timeline_start.seconds == 5.0  # 4s (compound start) + 1s (inner start)
    assert media_clip.duration.seconds == 3.0
    assert media_clip.source.source.endswith("index.html")

    # Track 2: the compound's inner track 1 (expanded overlay text, 4s + 0.5s = 4.5s).
    v2_clips = flattened.video_tracks[2].clips
    assert len(v2_clips) == 1
    assert v2_clips[0].id == "overlay_text"
    assert v2_clips[0].timeline_start.seconds == 4.5

    # Audio Track 0: whoosh sfx (4s + 0.5s = 4.5s) with volume 0.8 * 0.5 = 0.4
    a0_clips = flattened.audio_tracks[0].clips
    assert len(a0_clips) == 1
    assert a0_clips[0].id == "sfx_whoosh"
    assert a0_clips[0].timeline_start.seconds == 4.5
    assert pytest.approx(a0_clips[0].audio_properties.volume) == 0.4

    # Ensure no track timing errors
    errors = flattened.validate_tracks()
    assert not errors


def test_flatten_sibling_compound_clips_do_not_collide_on_audio_track():
    """Regression test: two independent CompoundClips, each with their own
    inner audio, must not have their audio collapsed onto the same
    flattened audio track just because both use inner audio track index 0.
    """

    def make_compound(clip_id: str, start_s: float) -> CompoundClip:
        inner = Timeline()
        inner.add_clip(
            AudioClip(id=f"{clip_id}_sfx", source=Source(source="sfx.wav"), duration=Time.from_seconds(2))
        )
        return CompoundClip(
            id=clip_id,
            timeline_start=Time.from_seconds(start_s),
            duration=Time.from_seconds(4),
            inner_timeline=inner,
        )

    root = Timeline()
    root.add_clip(make_compound("comp_a", 0), track_index=0)
    root.add_clip(make_compound("comp_b", 10), track_index=1)

    flattened = root.flatten()

    # Each compound's audio must land on its own distinct audio track.
    assert len(flattened.audio_tracks) == 2
    track_ids = [{c.id for c in t.clips} for t in flattened.audio_tracks]
    assert {"comp_a_sfx"} in track_ids
    assert {"comp_b_sfx"} in track_ids
    # And, critically, not merged onto a single shared track.
    assert track_ids[0] != track_ids[1]


def test_flatten_nested_compound_audio_tracks_stay_isolated():
    """A doubly-nested compound's audio and a sibling audio clip at the
    middle level must not collide on the same flattened audio track."""
    innermost = Timeline()
    innermost.add_clip(
        AudioClip(id="inner_sfx", source=Source(source="in.wav"), duration=Time.from_seconds(2))
    )
    nested_compound = CompoundClip(id="nested", duration=Time.from_seconds(4), inner_timeline=innermost)

    middle = Timeline()
    middle.add_clip(nested_compound, track_index=0)
    middle.add_clip(
        AudioClip(id="middle_sfx", source=Source(source="mid.wav"), duration=Time.from_seconds(2)),
        track_index=1,
    )

    outer_compound = CompoundClip(id="outer", duration=Time.from_seconds(6), inner_timeline=middle)

    root = Timeline()
    root.add_clip(outer_compound, track_index=0)

    flattened = root.flatten()

    all_audio_ids = [{c.id for c in t.clips} for t in flattened.audio_tracks]
    assert {"inner_sfx"} in all_audio_ids
    assert {"middle_sfx"} in all_audio_ids
    assert all_audio_ids[0] != all_audio_ids[1]


class TestCompoundSpeedRetiming:
    """A CompoundClip's `speed` should compress how much outer-timeline span
    its inner content occupies -- not just tell the leaf clips to play back
    faster while keeping their original spacing/duration.
    """

    def test_2x_speed_compresses_child_position_and_duration(self):
        inner = Timeline()
        inner.add_clip(
            TextClip(
                id="t1", text="A", timeline_start=Time.from_seconds(2), duration=Time.from_seconds(4)
            )
        )
        compound = CompoundClip(
            id="c1",
            timeline_start=Time.from_seconds(0),
            duration=Time.from_seconds(4),
            speed=2.0,
            inner_timeline=inner,
        )

        root = Timeline()
        root.add_clip(compound)
        flattened = root.flatten()
        clip = flattened.video_tracks[0].clips[0]

        # Local 2s / 2x speed = 1s; local 4s duration / 2x speed = 2s.
        assert clip.timeline_start.seconds == 1.0
        assert clip.duration.seconds == 2.0
        assert clip.speed == 2.0

    def test_1x_speed_is_unchanged_from_original_behavior(self):
        """Regression guard: speed=1.0 (the default) must reduce to plain
        offset addition with no compression, matching pre-fix behavior."""
        inner = Timeline()
        inner.add_clip(
            TextClip(
                id="t1", text="A", timeline_start=Time.from_seconds(2), duration=Time.from_seconds(4)
            )
        )
        compound = CompoundClip(
            id="c1", timeline_start=Time.from_seconds(3), duration=Time.from_seconds(4), inner_timeline=inner
        )

        root = Timeline()
        root.add_clip(compound)
        flattened = root.flatten()
        clip = flattened.video_tracks[0].clips[0]

        assert clip.timeline_start.seconds == 5.0  # 3 (compound start) + 2 (inner start)
        assert clip.duration.seconds == 4.0
        assert clip.speed == 1.0

    def test_nested_compound_own_position_is_compressed_by_ancestor_speed(self):
        """A nested compound's *position* within its parent's local time must
        also be compressed by the parent's speed -- not just its children's
        positions. Otherwise a compound sitting at local t=4s inside a 2x
        parent would incorrectly appear at t=4s instead of t=2s.
        """
        leaf_timeline = Timeline()
        leaf_timeline.add_clip(
            TextClip(id="leaf", text="X", timeline_start=Time.zero(), duration=Time.from_seconds(2))
        )
        nested_compound = CompoundClip(
            id="nested",
            timeline_start=Time.from_seconds(4),
            duration=Time.from_seconds(2),
            inner_timeline=leaf_timeline,
        )

        middle = Timeline()
        middle.add_clip(nested_compound)

        outer_compound = CompoundClip(
            id="outer",
            timeline_start=Time.zero(),
            duration=Time.from_seconds(4),
            speed=2.0,
            inner_timeline=middle,
        )

        root = Timeline()
        root.add_clip(outer_compound)
        flattened = root.flatten()
        clip = flattened.video_tracks[0].clips[0]

        assert clip.timeline_start.seconds == 2.0  # 4s local position / 2x speed
        assert clip.duration.seconds == 1.0  # 2s local duration / 2x speed
        assert clip.speed == 2.0

    def test_doubly_nested_speeds_compound_multiplicatively(self):
        """Outer compound at 2x containing an inner compound at 3x should
        give leaf clips an effective 6x speed, with positions/durations
        compressed accordingly at each level.
        """
        innermost = Timeline()
        innermost.add_clip(
            TextClip(
                id="deep", text="X", timeline_start=Time.from_seconds(6), duration=Time.from_seconds(12)
            )
        )
        inner_compound = CompoundClip(
            id="inner_c",
            timeline_start=Time.from_seconds(1),
            duration=Time.from_seconds(4),
            speed=3.0,
            inner_timeline=innermost,
        )

        middle = Timeline()
        middle.add_clip(inner_compound)

        outer_compound = CompoundClip(
            id="outer_c",
            timeline_start=Time.zero(),
            duration=Time.from_seconds(4),
            speed=2.0,
            inner_timeline=middle,
        )

        root = Timeline()
        root.add_clip(outer_compound)
        flattened = root.flatten()
        clip = flattened.video_tracks[0].clips[0]

        assert clip.timeline_start.seconds == 1.5
        assert clip.duration.seconds == 2.0
        assert clip.speed == 6.0

    def test_audio_children_are_compressed_the_same_way_as_video(self):
        inner = Timeline()
        inner.add_clip(
            AudioClip(
                id="sfx",
                source=Source(source="a.wav"),
                timeline_start=Time.from_seconds(2),
                duration=Time.from_seconds(4),
            )
        )
        compound = CompoundClip(
            id="c1",
            timeline_start=Time.zero(),
            duration=Time.from_seconds(4),
            speed=2.0,
            inner_timeline=inner,
        )

        root = Timeline()
        root.add_clip(compound)
        flattened = root.flatten()
        clip = flattened.audio_tracks[0].clips[0]

        assert clip.timeline_start.seconds == 1.0
        assert clip.duration.seconds == 2.0
        assert clip.speed == 2.0


