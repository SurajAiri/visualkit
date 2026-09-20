"""Regression tests for Timeline/Track integrity: atomic edits, companion audio,
duplicate ids, track provisioning, cycle rejection, exact ordering.

Each test pins a bug found in the audit; see CHANGES.md.
"""

from fractions import Fraction

import pytest

from visualkit.models import (
    AudioClip,
    CompoundAudioClip,
    CompoundClip,
    MediaClip,
    Timeline,
)
from visualkit.models.timeline import InsertMode
from visualkit.utils.exceptions import InvalidTrackOperationError, TimelineValidationError
from visualkit.utils.time import Time


def media_clip(clip_id: str, start: float, dur: float) -> MediaClip:
    return MediaClip(id=clip_id, source=f"{clip_id}.mp4", timeline_start=Time(start), duration=Time(dur))


def compound(clip_id: str = "c", dur: float = 5) -> CompoundClip:
    return CompoundClip(id=clip_id, duration=Time(dur), inner_timeline=Timeline())


def snapshot(track):
    return [(c.id, c.timeline_start.value, c.duration.value) for c in track.clips]


class TestAtomicity:
    def test_rejected_split_leaves_track_untouched(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 5))
        t.add_clip(media_clip("b", 1, 3))  # deliberately overlapping (default OVERLAP mode allows it)
        before = snapshot(t.video_tracks[0])
        with pytest.raises(TimelineValidationError):
            t.split_clip("a", Time(2))
        assert snapshot(t.video_tracks[0]) == before

    def test_rejected_split_does_not_relink_or_reset_clip(self):
        t = Timeline()
        a = media_clip("a", 0, 5)
        t.add_clip(a)
        t.add_clip(media_clip("b", 1, 3))
        with pytest.raises(TimelineValidationError):
            t.split_clip("a", Time(2))
        assert a.linked_clip_id is None
        assert a.duration == Time(5)

    def test_rejected_move_keeps_clip_on_source_track(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 5), track_index=0)
        t.add_clip(media_clip("blocker", 0, 5), track_index=1)
        with pytest.raises(TimelineValidationError):
            t.move_clip_track("a", t.video_tracks[1].id, validate=True)
        assert [c.id for c in t.video_tracks[0].clips] == ["a"]
        assert [c.id for c in t.video_tracks[1].clips] == ["blocker"]

    def test_move_to_same_track_is_a_noop(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 5))
        assert t.move_clip_track("a", t.video_tracks[0].id, validate=True) is True
        assert [c.id for c in t.video_tracks[0].clips] == ["a"]


class TestTrackProvisioning:
    def test_video_add_does_not_create_audio_tracks(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 5), track_index=2)
        assert len(t.video_tracks) == 3
        assert len(t.audio_tracks) == 0

    def test_audio_add_does_not_create_video_tracks(self):
        t = Timeline()
        t.add_clip(AudioClip(id="a", source="a.mp3", duration=Time(5)), track_index=2)
        assert len(t.audio_tracks) == 3
        assert len(t.video_tracks) == 0

    def test_compound_add_provisions_its_audio_seat(self):
        t = Timeline()
        t.add_clip(compound(), track_index=1)
        assert len(t.video_tracks) == 2
        assert len(t.audio_tracks) == 2
        assert isinstance(t.audio_tracks[1].clips[0], CompoundAudioClip)


class TestIdsAndCycles:
    def test_duplicate_clip_id_is_rejected(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 5))
        with pytest.raises(TimelineValidationError, match="already exists"):
            t.add_clip(media_clip("a", 5, 5))
        assert len(t.video_tracks[0].clips) == 1

    def test_duplicate_id_across_tracks_is_rejected(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 5), track_index=0)
        with pytest.raises(TimelineValidationError):
            t.add_clip(media_clip("a", 0, 5), track_index=1)

    def test_compound_cannot_contain_the_timeline_it_is_added_to(self):
        root = Timeline()
        c = CompoundClip(id="c", duration=Time(5), inner_timeline=root)
        with pytest.raises(TimelineValidationError, match="cannot contain"):
            root.add_clip(c)

    def test_indirect_cycle_is_rejected(self):
        root = Timeline()
        mid = Timeline()
        mid.add_clip(CompoundClip(id="inner", duration=Time(5), inner_timeline=root))
        with pytest.raises(TimelineValidationError):
            root.add_clip(CompoundClip(id="outer", duration=Time(5), inner_timeline=mid))


class TestCompanionAudio:
    def test_remove_compound_removes_companion(self):
        t = Timeline()
        t.add_clip(compound())
        assert t.remove_clip("c") is True
        assert t.video_tracks[0].clips == []
        assert t.audio_tracks[0].clips == []

    def test_ripple_insert_moves_companion_with_compound(self):
        t = Timeline()
        t.add_clip(compound())
        t.add_clip(media_clip("m", 0, 3), mode=InsertMode.RIPPLE)
        comp = next(c for c in t.video_tracks[0].clips if c.id == "c")
        companion = t.audio_tracks[0].clips[0]
        assert comp.timeline_start == Time(3)
        assert companion.timeline_start == comp.timeline_start

    def test_sync_companions_realigns_after_direct_edit(self):
        t = Timeline()
        c = compound()
        t.add_clip(c)
        c.timeline_start = Time(4)
        c.duration = Time(9)
        assert t.sync_companions() == 1
        companion = t.audio_tracks[0].clips[0]
        assert companion.timeline_start == Time(4)
        assert companion.duration == Time(9)
        assert t.sync_companions() == 0  # idempotent

    def test_move_clip_track_resyncs_companions(self):
        t = Timeline()
        c = compound()
        t.add_clip(c)
        t.add_video_track()
        c.timeline_start = Time(2)
        t.move_clip_track("c", t.video_tracks[1].id)
        assert t.audio_tracks[0].clips[0].timeline_start == Time(2)


class TestExactOrdering:
    def test_sub_epsilon_starts_are_ordered_exactly(self):
        """The sort key used to be float seconds, which cannot tell these apart."""
        early = MediaClip(id="x", source="x.mp4", timeline_start=Time(Fraction(1, 3)), duration=Time(1))
        late = MediaClip(
            id="y",
            source="y.mp4",
            timeline_start=Time(Fraction(1, 3) + Fraction(1, 10**30)),
            duration=Time(1),
        )
        t = Timeline()
        t.add_clip(late)
        t.add_clip(early)
        assert [c.id for c in t.video_tracks[0].clips] == ["x", "y"]

    def test_validate_clips_uses_exact_arithmetic(self):
        t = Timeline()
        t.add_clip(MediaClip(id="a", source="a.mp4", timeline_start=Time(0), duration=Time(Fraction(1, 3))))
        # starts *exactly* where 'a' ends: no overlap
        t.add_clip(MediaClip(id="b", source="b.mp4", timeline_start=Time(Fraction(1, 3)), duration=Time(1)))
        assert t.video_tracks[0].validate_clips() == []


class TestAddClipIsAllOrNothing:
    """A rejected batch must leave the timeline exactly as it was (found while verifying the README)."""

    @staticmethod
    def state(t):
        return (
            [[(c.id, c.timeline_start.value, c.duration.value) for c in tr.clips] for tr in t.video_tracks],
            [[(c.id, c.timeline_start.value, c.duration.value) for c in tr.clips] for tr in t.audio_tracks],
        )

    def test_failed_overlap_in_a_batch_keeps_the_earlier_clips_out(self):
        t = Timeline()
        t.add_clip(media_clip("x", 0, 5))
        before = self.state(t)
        with pytest.raises(TimelineValidationError):
            t.add_clip(media_clip("ok", 10, 1), media_clip("clash", 2, 1), validate=True)
        assert self.state(t) == before

    def test_duplicate_ids_within_one_call_are_rejected(self):
        t = Timeline()
        with pytest.raises(TimelineValidationError, match="already exists"):
            t.add_clip(media_clip("a", 0, 1), media_clip("a", 5, 1))
        assert t.video_tracks == []

    def test_rollback_also_removes_tracks_created_by_the_failed_call(self):
        """The first clip forces tracks 1..3 into existence; the second is then rejected."""
        t = Timeline()
        t.add_clip(media_clip("x", 0, 5))
        assert len(t.video_tracks) == 1
        with pytest.raises(TimelineValidationError):
            t.add_clip(media_clip("ok", 10, 2), media_clip("clash", 11, 2), track_index=3, validate=True)
        assert len(t.video_tracks) == 1, "tracks created by the failed call must be removed"
        assert [c.id for c in t.video_tracks[0].clips] == ["x"]

    def test_failed_compound_add_unlinks_and_leaves_no_companion(self):
        t = Timeline()
        t.add_clip(AudioClip(id="a", source="a.mp3", timeline_start=Time(0), duration=Time(5)))
        comp = compound("c", 5)
        # The companion audio would overlap the existing audio clip, so validation rejects the add.
        with pytest.raises(TimelineValidationError):
            t.add_clip(comp, validate=True)
        assert comp.linked_clip_id is None
        assert t.video_tracks == [] or all(tr.clips == [] for tr in t.video_tracks)
        assert [c.id for c in t.audio_tracks[0].clips] == ["a"]

    def test_failed_ripple_batch_restores_shifted_clip_positions(self):
        """'a' ripples the existing clips later; 'b' then lands inside one of them and is rejected.
        Restoring the track *order* is not enough: the shifted start times must come back too."""
        t = Timeline()
        t.add_clip(media_clip("first", 0, 2), media_clip("second", 2, 2))
        before = self.state(t)
        with pytest.raises(InvalidTrackOperationError):
            t.add_clip(media_clip("a", 0, 3), media_clip("b", 4, 1), mode=InsertMode.RIPPLE)
        assert self.state(t) == before
        assert [c.timeline_start for c in t.video_tracks[0].clips] == [Time(0), Time(2)]

    def test_successful_batch_still_adds_everything(self):
        t = Timeline()
        t.add_clip(media_clip("a", 0, 1), media_clip("b", 1, 1), media_clip("c", 2, 1))
        assert [c.id for c in t.video_tracks[0].clips] == ["a", "b", "c"]
