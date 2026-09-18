"""Core Timeline / Track mechanics: track provisioning, insert modes, and
routing. These primarily cover regressions found during a library review:

1. `Timeline.add_clip(clip, track_index=N)` must create tracks up to and
   including index N, and place the clip at exactly N -- not silently
   fall back to track 0 whenever N is beyond the current track count.
2. `Track.add_clip(clip, mode=RIPPLE)` must correctly shift clips that
   start at or after the insertion point, and must raise a clear error
   (rather than silently leaving an overlap) when the insertion point
   falls inside an existing clip's span.
"""

import pytest

from visualkit.models import AudioClip, MediaClip, Source, TextClip, Timeline
from visualkit.models.timeline import InsertMode, Track
from visualkit.utils.exceptions import InvalidTrackOperationError
from visualkit.utils.time import Time


def _media(clip_id: str, start: float, duration: float) -> MediaClip:
    return MediaClip(
        id=clip_id,
        source=Source(source=f"{clip_id}.mp4"),
        timeline_start=Time.from_seconds(start),
        duration=Time.from_seconds(duration),
    )


class TestAddClipTrackIndex:
    def test_track_index_beyond_current_count_creates_intermediate_tracks(self):
        """Requesting track_index=5 on an empty timeline must create 6 tracks
        (0-5) and place the clip at index 5 -- not silently place it at 0."""
        timeline = Timeline()
        clip = _media("m1", start=0, duration=5)

        timeline.add_clip(clip, track_index=5)

        assert len(timeline.video_tracks) == 6
        for i in range(5):
            assert timeline.video_tracks[i].clips == []
        assert [c.id for c in timeline.video_tracks[5].clips] == ["m1"]

    def test_track_index_zero_on_empty_timeline_provisions_one_track(self):
        timeline = Timeline()
        timeline.add_clip(_media("m1", 0, 5))
        assert len(timeline.video_tracks) == 1
        assert timeline.video_tracks[0].clips[0].id == "m1"

    def test_sequential_track_indices_do_not_create_extra_tracks(self):
        """Adding to track_index=0 then track_index=1 should result in
        exactly 2 tracks (the original working case), not more."""
        timeline = Timeline()
        timeline.add_clip(_media("m1", 0, 5), track_index=0)
        timeline.add_clip(_media("m2", 0, 5), track_index=1)
        assert len(timeline.video_tracks) == 2

    def test_audio_clip_routes_to_audio_tracks_at_requested_index(self):
        timeline = Timeline()
        audio_clip = AudioClip(id="a1", source=Source(source="a.mp3"), duration=Time.from_seconds(4))
        timeline.add_clip(audio_clip, track_index=3)

        assert len(timeline.audio_tracks) == 4
        assert [c.id for c in timeline.audio_tracks[3].clips] == ["a1"]

    def test_negative_track_index_raises(self):
        timeline = Timeline()
        with pytest.raises(ValueError):
            timeline.add_clip(_media("m1", 0, 5), track_index=-1)


class TestRippleInsert:
    def test_ripple_shifts_clips_starting_at_or_after_insertion_point(self):
        track = Track()
        later_clip = _media("later", start=5, duration=5)
        track.add_clip(later_clip)

        new_clip = _media("new", start=2, duration=3)
        track.add_clip(new_clip, mode=InsertMode.RIPPLE)

        # "new" keeps its requested start; "later" is pushed back by new's duration
        by_id = {c.id: c for c in track.clips}
        assert by_id["new"].timeline_start.seconds == 2.0
        assert by_id["later"].timeline_start.seconds == 8.0
        assert track.validate_clips() == []

    def test_ripple_insertion_point_inside_existing_clip_raises(self):
        """This is the bug case: inserting at a point that lands inside an
        already-existing clip's span cannot be resolved by shifting alone
        (nothing in the existing clip's span is `>= insertion_point`), so it
        must raise instead of silently producing an overlap."""
        track = Track()
        track.add_clip(_media("existing", start=0, duration=5))  # occupies [0, 5)

        overlapping_new_clip = _media("new", start=3, duration=4)  # starts inside [0, 5)

        with pytest.raises(InvalidTrackOperationError):
            track.add_clip(overlapping_new_clip, mode=InsertMode.RIPPLE)

        # The failed insert must not have mutated the track at all.
        assert [c.id for c in track.clips] == ["existing"]
        assert track.clips[0].timeline_start.seconds == 0.0

    def test_ripple_insert_at_exact_start_of_existing_clip(self):
        """Insertion point exactly at an existing clip's start is the
        boundary case: it should shift (not raise), since `>=` includes
        equality."""
        track = Track()
        track.add_clip(_media("existing", start=3, duration=4))

        track.add_clip(_media("new", start=3, duration=2), mode=InsertMode.RIPPLE)

        by_id = {c.id: c for c in track.clips}
        assert by_id["new"].timeline_start.seconds == 3.0
        assert by_id["existing"].timeline_start.seconds == 5.0
        assert track.validate_clips() == []
