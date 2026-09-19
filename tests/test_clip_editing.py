"""Tests for the clip-editing primitives added on top of the existing
add_clip / remove_clip / move_clip_track / validate_clips surface:

  - Track.get_clip_at / Timeline.get_clips_at
  - Track.split_clip / Timeline.split_clip
  - Track.trim_in / Track.trim_out / Timeline.trim_in / Timeline.trim_out
  - Track.ripple_delete / Timeline.ripple_delete
  - Track.duplicate_clip / Timeline.duplicate_clip
  - The opt-in `validate` flag on add_clip / all of the above
  - move_clip_track now honoring a `mode` argument instead of always
    reusing add_clip's OVERLAP default

Each clip-type-specific quirk mentioned in the review (speed scaling on
trim/split, CompoundClip being unsplittable, CodedVisualClip's stale
compiled media_source, the CompoundClip/CompoundAudioClip pairing) gets
its own dedicated test rather than being folded into a generic case.
"""

import pytest

from visualkit.models import (
    AudioClip,
    CodedVisualClip,
    CompoundClip,
    MediaClip,
    Source,
    TextClip,
    Timeline,
)
from visualkit.models.clips.coded_visual import CompileStatus
from visualkit.models.timeline import InsertMode, Track
from visualkit.utils.exceptions import (
    ClipNotFoundError,
    InvalidSplitError,
    InvalidTrackOperationError,
    TimelineValidationError,
)
from visualkit.utils.time import Time


def _media(
    clip_id: str, start: float, duration: float, speed: float = 1.0, source_start: float = 0.0
) -> MediaClip:
    return MediaClip(
        id=clip_id,
        source=Source(source=f"{clip_id}.mp4", start=Time.from_seconds(source_start)),
        timeline_start=Time.from_seconds(start),
        duration=Time.from_seconds(duration),
        speed=speed,
    )


def _text(clip_id: str, start: float, duration: float) -> TextClip:
    return TextClip(
        id=clip_id, text="hi", timeline_start=Time.from_seconds(start), duration=Time.from_seconds(duration)
    )


# ---------------------------------------------------------------------------
# get_clip_at / get_clips_at
# ---------------------------------------------------------------------------


class TestGetClipAt:
    def test_track_get_clip_at_finds_containing_clip(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", 5, 5))

        assert track.get_clip_at(Time.from_seconds(2)).id == "a"
        assert track.get_clip_at(Time.from_seconds(5)).id == "b"  # start-inclusive
        assert track.get_clip_at(Time.from_seconds(9.9)).id == "b"

    def test_track_get_clip_at_end_is_exclusive(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        assert track.get_clip_at(Time.from_seconds(5)) is None  # exactly at end -> not "a"

    def test_track_get_clip_at_gap_returns_none(self):
        track = Track()
        track.add_clip(_media("a", 0, 2))
        track.add_clip(_media("b", 5, 2))
        assert track.get_clip_at(Time.from_seconds(3)) is None

    def test_timeline_get_clips_at_returns_all_simultaneous_tracks(self):
        timeline = Timeline()
        timeline.add_clip(_media("v1", 0, 10), track_index=0)
        timeline.add_clip(AudioClip(id="a1", source=Source(source="a.mp3"), duration=Time.from_seconds(10)))

        results = timeline.get_clips_at(Time.from_seconds(3))
        ids = {clip.id for _, clip in results}
        assert ids == {"v1", "a1"}

    def test_timeline_get_clips_at_empty_when_nothing_under_playhead(self):
        timeline = Timeline()
        timeline.add_clip(_media("v1", 0, 2))
        assert timeline.get_clips_at(Time.from_seconds(5)) == []


# ---------------------------------------------------------------------------
# split_clip
# ---------------------------------------------------------------------------


class TestSplitClip:
    def test_split_basic_media_clip(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))

        first, second = track.split_clip("a", Time.from_seconds(4))

        assert first.id == "a"
        assert first.timeline_start.seconds == 0
        assert first.duration.seconds == 4

        assert second.timeline_start.seconds == 4
        assert second.duration.seconds == 6
        assert second.id != "a"

        assert [c.id for c in track.clips] == ["a", second.id]
        assert track.validate_clips() == []

    def test_split_advances_source_start_by_speed(self):
        """speed=2.0: one timeline second consumes two source seconds, so a
        4-second-in split must advance source.start by 8, not 4."""
        track = Track()
        track.add_clip(_media("a", start=0, duration=10, speed=2.0, source_start=100))

        first, second = track.split_clip("a", Time.from_seconds(4))

        assert first.source.start.seconds == 100  # untouched
        assert second.source.start.seconds == 108  # 100 + 4*2

    def test_split_respects_nonzero_source_start_and_speed_one(self):
        track = Track()
        track.add_clip(_media("a", start=0, duration=10, speed=1.0, source_start=50))

        _, second = track.split_clip("a", Time.from_seconds(3))
        assert second.source.start.seconds == 53

    def test_split_cross_links_linked_clip_id(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))
        first, second = track.split_clip("a", Time.from_seconds(4))
        assert first.linked_clip_id == second.id
        assert second.linked_clip_id == first.id

    def test_split_text_clip_has_no_source_to_touch(self):
        track = Track()
        track.add_clip(_text("t", 0, 10))
        first, second = track.split_clip("t", Time.from_seconds(4))
        assert first.text == "hi"
        assert second.text == "hi"
        assert first.duration.seconds == 4
        assert second.duration.seconds == 6

    def test_split_at_exact_start_raises(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))
        with pytest.raises(InvalidSplitError):
            track.split_clip("a", Time.from_seconds(0))

    def test_split_at_exact_end_raises(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))
        with pytest.raises(InvalidSplitError):
            track.split_clip("a", Time.from_seconds(10))

    def test_split_outside_clip_span_raises(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))
        with pytest.raises(InvalidSplitError):
            track.split_clip("a", Time.from_seconds(20))

    def test_split_missing_clip_raises_clip_not_found(self):
        track = Track()
        with pytest.raises(ClipNotFoundError):
            track.split_clip("nope", Time.from_seconds(1))

    def test_split_compound_clip_is_disallowed(self):
        inner = Timeline()
        compound = CompoundClip(id="comp", duration=Time.from_seconds(10), inner_timeline=inner)
        track = Track()
        track.clips.append(compound)

        with pytest.raises(InvalidSplitError):
            track.split_clip("comp", Time.from_seconds(4))

    def test_split_resets_stale_compiled_coded_visual(self):
        """A CodedVisualClip that already compiled must not let either half
        keep pointing at a media_source rendered for the pre-split duration."""
        track = Track()
        clip = CodedVisualClip(id="cv", source="templates/x.html", duration=Time.from_seconds(10))
        clip.media_source = "/cache/rendered_for_10s.mp4"
        clip.compile_status = CompileStatus.READY
        track.clips.append(clip)

        first, second = track.split_clip("cv", Time.from_seconds(4))

        assert first.media_source is None
        assert first.compile_status == CompileStatus.PENDING
        assert second.media_source is None
        assert second.compile_status == CompileStatus.PENDING

    def test_split_leaves_pending_coded_visual_alone(self):
        """Nothing to invalidate if it was never compiled -- shouldn't raise
        or otherwise misbehave on the PENDING/no-media_source case."""
        track = Track()
        clip = CodedVisualClip(id="cv", source="templates/x.html", duration=Time.from_seconds(10))
        track.clips.append(clip)

        first, second = track.split_clip("cv", Time.from_seconds(4))
        assert first.compile_status == CompileStatus.PENDING
        assert second.compile_status == CompileStatus.PENDING

    def test_timeline_split_clip_finds_clip_on_any_track(self):
        timeline = Timeline()
        timeline.add_clip(_media("a", 0, 10), track_index=2)

        first, second = timeline.split_clip("a", Time.from_seconds(4))
        assert first.id == "a"
        assert second.timeline_start.seconds == 4

    def test_timeline_split_clip_not_found_raises(self):
        timeline = Timeline()
        with pytest.raises(ClipNotFoundError):
            timeline.split_clip("nope", Time.from_seconds(1))


# ---------------------------------------------------------------------------
# trim_in / trim_out
# ---------------------------------------------------------------------------


class TestTrimIn:
    def test_trim_in_shrinks_and_advances_source_start(self):
        track = Track()
        track.add_clip(_media("a", start=0, duration=10, speed=1.0, source_start=20))

        clip = track.trim_in("a", Time.from_seconds(3))

        assert clip.timeline_start.seconds == 3
        assert clip.duration.seconds == 7
        assert clip.source.start.seconds == 23

    def test_trim_in_scales_source_advance_by_speed(self):
        track = Track()
        track.add_clip(_media("a", start=0, duration=10, speed=2.0, source_start=20))

        clip = track.trim_in("a", Time.from_seconds(3))
        assert clip.source.start.seconds == 26  # 20 + 3*2

    def test_trim_in_can_extend_head_backward(self):
        """new_in before the current start reveals more pre-roll: source.start
        must move backward too, by the same speed-scaled amount."""
        track = Track()
        track.add_clip(_media("a", start=5, duration=5, speed=1.0, source_start=10))

        clip = track.trim_in("a", Time.from_seconds(2))
        assert clip.timeline_start.seconds == 2
        assert clip.duration.seconds == 8
        assert clip.source.start.seconds == 7  # pulled back by 3

    def test_trim_in_past_available_source_raises(self):
        track = Track()
        track.add_clip(_media("a", start=5, duration=5, speed=1.0, source_start=2))
        # Extending 4s earlier would need source.start = -2, which doesn't exist.
        with pytest.raises(InvalidTrackOperationError):
            track.trim_in("a", Time.from_seconds(1))

    def test_trim_in_past_clip_end_raises(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))
        with pytest.raises(InvalidTrackOperationError):
            track.trim_in("a", Time.from_seconds(10))

    def test_trim_in_text_clip_no_source_needed(self):
        track = Track()
        track.add_clip(_text("t", 0, 10))
        clip = track.trim_in("t", Time.from_seconds(4))
        assert clip.timeline_start.seconds == 4
        assert clip.duration.seconds == 6

    def test_trim_in_compound_clip_disallowed(self):
        compound = CompoundClip(id="comp", duration=Time.from_seconds(10), inner_timeline=Timeline())
        track = Track()
        track.clips.append(compound)
        with pytest.raises(InvalidTrackOperationError):
            track.trim_in("comp", Time.from_seconds(3))

    def test_trim_in_rejects_overlap_with_previous_clip(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", start=5, duration=5, source_start=10))
        # Pulling b's head back to 3 would collide with a's [0,5).
        with pytest.raises(TimelineValidationError):
            track.trim_in("b", Time.from_seconds(3))
        # And the track must be untouched by the rejected attempt.
        assert track.get_clip("b").timeline_start.seconds == 5

    def test_trim_in_can_be_forced_without_validation(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", start=5, duration=5, source_start=10))
        clip = track.trim_in("b", Time.from_seconds(3), validate=False)
        assert clip.timeline_start.seconds == 3

    def test_trim_in_resets_stale_compiled_coded_visual(self):
        track = Track()
        clip = CodedVisualClip(id="cv", source="x.html", duration=Time.from_seconds(10))
        clip.media_source = "/cache/x.mp4"
        clip.compile_status = CompileStatus.READY
        track.clips.append(clip)

        track.trim_in("cv", Time.from_seconds(4))
        assert clip.media_source is None
        assert clip.compile_status == CompileStatus.PENDING


class TestTrimOut:
    def test_trim_out_shrinks_without_touching_source(self):
        track = Track()
        track.add_clip(_media("a", start=0, duration=10, source_start=5))
        clip = track.trim_out("a", Time.from_seconds(6))
        assert clip.timeline_start.seconds == 0
        assert clip.duration.seconds == 6
        assert clip.source.start.seconds == 5  # untouched

    def test_trim_out_can_extend_tail(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        clip = track.trim_out("a", Time.from_seconds(8))
        assert clip.duration.seconds == 8

    def test_trim_out_to_zero_or_negative_duration_raises(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        with pytest.raises(InvalidTrackOperationError):
            track.trim_out("a", Time.from_seconds(0))

    def test_trim_out_rejects_overlap_with_next_clip(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", 5, 5))
        with pytest.raises(TimelineValidationError):
            track.trim_out("a", Time.from_seconds(7))
        assert track.get_clip("a").duration.seconds == 5

    def test_trim_out_works_on_compound_clip(self):
        """Unlike trim_in, trim_out doesn't need an inner-playback-offset
        concept -- shortening the tail is well-defined for CompoundClip."""
        compound = CompoundClip(
            id="comp", timeline_start=Time.zero(), duration=Time.from_seconds(10), inner_timeline=Timeline()
        )
        track = Track()
        track.clips.append(compound)

        clip = track.trim_out("comp", Time.from_seconds(6))
        assert clip.duration.seconds == 6

    def test_trim_out_resets_stale_compiled_coded_visual(self):
        track = Track()
        clip = CodedVisualClip(id="cv", source="x.html", duration=Time.from_seconds(10))
        clip.media_source = "/cache/x.mp4"
        clip.compile_status = CompileStatus.READY
        track.clips.append(clip)

        track.trim_out("cv", Time.from_seconds(6))
        assert clip.media_source is None
        assert clip.compile_status == CompileStatus.PENDING

    def test_timeline_trim_out_propagates_to_compound_audio_companion(self):
        timeline = Timeline()
        compound = CompoundClip(id="comp", duration=Time.from_seconds(10), inner_timeline=Timeline())
        timeline.add_clip(compound)

        companion_id = compound.linked_clip_id
        assert companion_id is not None

        timeline.trim_out("comp", Time.from_seconds(6))

        _, companion = timeline.get_clip(companion_id)
        assert companion.duration.seconds == 6

    def test_timeline_trim_in_missing_clip_raises(self):
        timeline = Timeline()
        with pytest.raises(ClipNotFoundError):
            timeline.trim_in("nope", Time.from_seconds(1))


# ---------------------------------------------------------------------------
# ripple_delete
# ---------------------------------------------------------------------------


class TestRippleDelete:
    def test_ripple_delete_shifts_later_clips_left(self):
        track = Track()
        track.add_clip(_media("a", 0, 3))
        track.add_clip(_media("b", 3, 4))
        track.add_clip(_media("c", 7, 2))

        assert track.ripple_delete("b") is True

        by_id = {c.id: c for c in track.clips}
        assert set(by_id) == {"a", "c"}
        assert by_id["a"].timeline_start.seconds == 0
        assert by_id["c"].timeline_start.seconds == 3  # was 7, shifted left by b's 4s
        assert track.validate_clips() == []

    def test_ripple_delete_is_inverse_of_ripple_insert(self):
        track = Track()
        track.add_clip(_media("a", 0, 3))
        track.add_clip(_media("c", 3, 2))

        new_clip = _media("b", start=3, duration=4)
        track.add_clip(new_clip, mode=InsertMode.RIPPLE)
        assert track.get_clip("c").timeline_start.seconds == 7

        track.ripple_delete("b")
        assert track.get_clip("c").timeline_start.seconds == 3
        assert track.validate_clips() == []

    def test_ripple_delete_missing_clip_returns_false(self):
        track = Track()
        assert track.ripple_delete("nope") is False

    def test_ripple_delete_leaves_earlier_clips_untouched(self):
        track = Track()
        track.add_clip(_media("a", 0, 3))
        track.add_clip(_media("b", 3, 4))
        track.ripple_delete("b")
        assert track.get_clip("a").timeline_start.seconds == 0

    def test_timeline_ripple_delete_cascades_to_compound_audio_companion(self):
        timeline = Timeline()
        timeline.add_clip(
            CompoundClip(
                id="comp1",
                timeline_start=Time.zero(),
                duration=Time.from_seconds(3),
                inner_timeline=Timeline(),
            )
        )
        _, comp1 = timeline.get_clip("comp1")
        companion_id = comp1.linked_clip_id

        # A later clip on both lanes so we can observe the ripple shift.
        timeline.add_clip(
            CompoundClip(
                id="comp2",
                timeline_start=Time.from_seconds(3),
                duration=Time.from_seconds(2),
                inner_timeline=Timeline(),
            )
        )
        _, comp2 = timeline.get_clip("comp2")
        companion2_id = comp2.linked_clip_id

        assert timeline.ripple_delete("comp1") is True

        # Video lane: comp1 gone, comp2 shifted left to 0.
        assert timeline.get_clip("comp1") == (None, None)
        _, comp2_after = timeline.get_clip("comp2")
        assert comp2_after.timeline_start.seconds == 0

        # Audio lane: comp1's companion gone, comp2's companion shifted left too.
        assert timeline.get_clip(companion_id) == (None, None)
        _, companion2_after = timeline.get_clip(companion2_id)
        assert companion2_after.timeline_start.seconds == 0


# ---------------------------------------------------------------------------
# duplicate_clip
# ---------------------------------------------------------------------------


class TestDuplicateClip:
    def test_duplicate_defaults_to_right_after_original(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))

        dup = track.duplicate_clip("a")

        assert dup.id != "a"
        assert dup.timeline_start.seconds == 5
        assert dup.duration.seconds == 5
        assert track.validate_clips() == []

    def test_duplicate_at_explicit_position(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        dup = track.duplicate_clip("a", new_timeline_start=Time.from_seconds(20))
        assert dup.timeline_start.seconds == 20

    def test_duplicate_clears_linked_clip_id(self):
        track = Track()
        track.add_clip(_media("a", 0, 10))
        _, second = track.split_clip("a", Time.from_seconds(4))
        assert second.linked_clip_id is not None

        dup = track.duplicate_clip(second.id, new_timeline_start=Time.from_seconds(50))
        assert dup.linked_clip_id is None

    def test_duplicate_overlap_by_default_raises(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        with pytest.raises(TimelineValidationError):
            track.duplicate_clip("a", new_timeline_start=Time.from_seconds(2))

    def test_duplicate_with_ripple_mode_shifts_following_clips(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", 5, 5))

        dup = track.duplicate_clip("a", new_timeline_start=Time.from_seconds(5), mode=InsertMode.RIPPLE)

        assert dup.timeline_start.seconds == 5
        assert track.get_clip("b").timeline_start.seconds == 10
        assert track.validate_clips() == []

    def test_duplicate_missing_clip_raises(self):
        track = Track()
        with pytest.raises(ClipNotFoundError):
            track.duplicate_clip("nope")

    def test_timeline_duplicate_compound_clip_duplicates_audio_companion_too(self):
        timeline = Timeline()
        timeline.add_clip(
            CompoundClip(
                id="comp",
                timeline_start=Time.zero(),
                duration=Time.from_seconds(5),
                inner_timeline=Timeline(),
            )
        )
        _, original = timeline.get_clip("comp")
        original_companion_id = original.linked_clip_id

        dup = timeline.duplicate_clip("comp")

        assert dup.id != "comp"
        assert dup.timeline_start.seconds == 5
        assert dup.linked_clip_id is not None
        assert dup.linked_clip_id != original_companion_id

        _, dup_companion = timeline.get_clip(dup.linked_clip_id)
        assert dup_companion is not None
        assert dup_companion.compound_clip_id == dup.id
        assert dup_companion.timeline_start.seconds == 5

        # Original pairing must be untouched.
        _, original_after = timeline.get_clip("comp")
        assert original_after.linked_clip_id == original_companion_id


# ---------------------------------------------------------------------------
# add_clip / move_clip_track: opt-in validate flag + mode fix
# ---------------------------------------------------------------------------


class TestAddClipValidateFlag:
    def test_add_clip_overlap_default_still_permits_overlap(self):
        """validate defaults to False, so existing OVERLAP-mode behavior is unchanged."""
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", 2, 5))  # overlaps "a"; must not raise
        assert len(track.clips) == 2

    def test_add_clip_overlap_with_validate_raises_before_mutating(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        with pytest.raises(TimelineValidationError):
            track.add_clip(_media("b", 2, 5), validate=True)
        assert [c.id for c in track.clips] == ["a"]  # rejected insert didn't touch the track

    def test_add_clip_overlap_with_validate_allows_non_overlapping(self):
        track = Track()
        track.add_clip(_media("a", 0, 5))
        track.add_clip(_media("b", 5, 5), validate=True)
        assert len(track.clips) == 2


class TestMoveClipTrackMode:
    def test_move_clip_track_default_mode_is_overlap(self):
        timeline = Timeline()
        timeline.add_video_track()
        timeline.add_video_track()
        timeline.add_clip(_media("a", 0, 5), track_index=0)
        dest = timeline.video_tracks[1]
        dest.add_clip(_media("existing", 0, 5))

        timeline.move_clip_track("a", dest.id)
        assert dest.get_clip("a").timeline_start.seconds == 0  # OVERLAP: unchanged, now overlaps

    def test_move_clip_track_ripple_mode_shifts_destination_clips(self):
        timeline = Timeline()
        timeline.add_video_track()
        timeline.add_video_track()
        timeline.add_clip(_media("a", 0, 5), track_index=0)
        dest = timeline.video_tracks[1]
        dest.add_clip(_media("existing", 0, 5))

        timeline.move_clip_track("a", dest.id, mode=InsertMode.RIPPLE)

        by_id = {c.id: c for c in dest.clips}
        assert by_id["a"].timeline_start.seconds == 0
        assert by_id["existing"].timeline_start.seconds == 5
        assert dest.validate_clips() == []
