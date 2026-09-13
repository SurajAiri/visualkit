import uuid

from pydantic import BaseModel, Field

from visualkit.models.clips import AudioContent, Clip, VisualContent


class Track(BaseModel):
    """A single track holding an ordered, non-overlapping-by-default list
    of clips. Track owns clip storage; clips remain track-agnostic (no
    track_id field) so moving a clip between tracks is a pure list
    operation with no risk of a clip's own state disagreeing with reality.
    """

    id: str = Field(default_factory=lambda: f"track_{uuid.uuid4().hex[:8]}")
    visual: list[VisualContent] = Field(default_factory=list)
    audio: list[AudioContent] = Field(default_factory=list)

    # append clip (this will automatically append/insert into the right list based on clip_type)


class Timeline(BaseModel):
    """Owns all tracks. Track levels are contiguous: 0..N-1 with no gaps,
    renumbered automatically whenever a track is added, removed, or moved.
    """

    main_track: Track = Field(default_factory=Track)
    tracks: list[Track] = Field(default_factory=list)

    def validate_tracks(self):
        """Validation on tracks before compiling"""
        pass
