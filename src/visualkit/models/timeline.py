from enum import Enum
import uuid

from pydantic import BaseModel, Field

from visualkit.models.clips import AudioClip, AudioContent, Clip, VisualContent


class TrackAddMode(str, Enum):
    OVERLAP = "overlap"  # just add the clip to the list, even if it overlaps with existing clips
    RIPPLE = "ripple"  # shift existing clips to the right to make room for the new clip, preventing overlap


class Track(BaseModel):
    """A single track holding an ordered, non-overlapping-by-default list
    of clips. Track owns clip storage; clips remain track-agnostic (no
    track_id field) so moving a clip between tracks is a pure list
    operation with no risk of a clip's own state disagreeing with reality.
    """

    id: str = Field(default_factory=lambda: f"track_{uuid.uuid4().hex[:8]}")
    visual: list[VisualContent] = Field(default_factory=list)
    audio: list[AudioContent] = Field(default_factory=list)

    # todo: all these need to be re-written these are all wrong, incomplete or mis-interpreted
    def add_clip(self, clip: Clip, mode: TrackAddMode = TrackAddMode.OVERLAP) -> None:
        """Route a clip into the correct list based on its concrete type."""
        # get start
        # todo: if overlap, then add compound and visual in visual and audio in audio, if ripple then shift all clips to the right
        # for compound clips, on validation there should be a check that automatically add compound audio clip associated to the compound clip if it is not already present in the audio track and if it is only present in audio track remove that (but this is mostly in validation phase)

    def remove_clip(self, clip_id: str) -> bool:
        for lst in (self.visual, self.audio):
            for i, c in enumerate(lst):
                if c.id == clip_id:
                    del lst[i]
                    return True
        return False

    def get_clip(self, clip_id: str) -> Clip | None:
        for c in (*self.visual, *self.audio):
            if c.id == clip_id:
                return c
        return None

    @staticmethod
    def _overlap_errors(clips: list) -> list[str]:
        errors = []
        ordered = sorted(clips, key=lambda c: c.start.seconds)
        for prev, cur in zip(ordered, ordered[1:]):
            prev_end = prev.start.seconds + prev.duration.seconds
            if cur.start.seconds < prev_end:
                errors.append(
                    f"clip {cur.id} starts at {cur.start.seconds}s, before clip {prev.id} ends at {prev_end}s"
                )
        return errors

    def validate_clips(self) -> list[str]:
        """Enforces the non-overlapping-by-default invariant this class claims."""
        return self._overlap_errors(self.visual) + self._overlap_errors(self.audio)


class Timeline(BaseModel):
    """Owns all tracks. Track order (== z-order for compositing) is the list
    position of `tracks`, with `main_track` always compositing first (level 0).
    There is no stored level field: order is derived from list position, so
    it cannot drift out of sync the way a stored, manually-renumbered level
    field could.

    ASSUMPTION (flagged, confirm or correct): main_track is kept separate from
    `tracks` only to guarantee a timeline is never track-less. If that's the
    only reason, prefer folding it into `tracks` with a `min_length=1`
    constraint instead -- see the note in the chat response.
    """

    main_track: Track = Field(default_factory=Track)
    tracks: list[Track] = Field(default_factory=list)

    @property
    def all_tracks(self) -> list[Track]:
        """main_track first, then overlay tracks in composite order."""
        return [self.main_track, *self.tracks]

    def add_track(self, index: int | None = None) -> Track:
        track = Track()
        if index is None:
            self.tracks.append(track)
        else:
            self.tracks.insert(index, track)
        return track

    def remove_track(self, track_id: str) -> bool:
        if track_id == self.main_track.id:
            raise ValueError("main_track cannot be removed")
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                del self.tracks[i]
                return True
        return False

    def move_track(self, track_id: str, new_index: int) -> bool:
        if track_id == self.main_track.id:
            raise ValueError("main_track has no position to move; it is always level 0")
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                self.tracks.insert(new_index, self.tracks.pop(i))
                return True
        return False

    def validate_tracks(self) -> list[str]:
        """Validation on tracks before compiling. Returns human-readable error
        strings; an empty list means the timeline is valid."""
        errors: list[str] = []

        seen_track_ids: set[str] = set()
        seen_clip_ids: set[str] = set()

        for track in self.all_tracks:
            if track.id in seen_track_ids:
                errors.append(f"duplicate track id: {track.id}")
            seen_track_ids.add(track.id)

            errors.extend(f"track {track.id}: {e}" for e in track.validate_clips())

            for clip in (*track.visual, *track.audio):
                if clip.id in seen_clip_ids:
                    errors.append(f"duplicate clip id across timeline: {clip.id}")
                seen_clip_ids.add(clip.id)

        return errors
