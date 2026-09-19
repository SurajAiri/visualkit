from __future__ import annotations

import uuid
from abc import ABC
from enum import Enum
from fractions import Fraction
from typing import Any, Generic, Literal, TypeVar

from pydantic import Field, model_validator

from visualkit.models.clips import (
    AudioContent,
    Clip,
    CodedVisualClip,
    CompileStatus,
    CompoundAudioClip,
    CompoundClip,
    VisualContent,
)
from visualkit.utils.base_model import VisualKitModel
from visualkit.utils.exceptions import (
    ClipNotFoundError,
    InvalidSplitError,
    InvalidTrackOperationError,
    TimelineValidationError,
)
from visualkit.utils.time import Time

# Same denominator cap Time itself uses when snapping a float to an exact
# Fraction (see utils/time.py::_FLOAT_DENOMINATOR_LIMIT). `speed` is a plain
# float field on BaseClip (not a Time), so trim/split math that multiplies a
# duration by `speed` goes through this helper to stay consistent with how
# the rest of the schema treats float precision, rather than inventing a
# second, differently-rounded convention here.
_SPEED_DENOMINATOR_LIMIT = 1_000_000


def _speed_fraction(speed: float) -> Fraction:
    """Convert a clip's `speed` field to an exact Fraction for trim/split math."""
    if isinstance(speed, Fraction):
        return speed
    if isinstance(speed, int):
        return Fraction(speed, 1)
    return Fraction(speed).limit_denominator(_SPEED_DENOMINATOR_LIMIT)


def _remap_compound_inner_ids(compound: CompoundClip) -> None:
    """Give every clip inside `compound.inner_timeline` a fresh id, and
    update `exposed_parameters[i].target_clip_id` references to match.

    `model_copy(deep=True)` deep-copies field *values*, but a
    default_factory-generated `id` is just another field value at this
    point -- it isn't regenerated on copy, so a duplicated CompoundClip's
    inner_timeline previously kept the exact same inner clip ids as the
    original. Two duplicated template instances therefore had inner
    clips sharing one id, which broke anything keyed by clip id across
    instances -- e.g. the text-rendering cache in
    `FFmpegVideoExporter._render_text_to_image`, which uses
    `clip.id` as the cache filename: both instances would collide on the
    same cached PNG and one instance's text would silently render as the
    other's.

    Applied recursively for nested CompoundClips (a template containing
    another template), since the same collision risk exists at every
    nesting level.
    """
    if not compound.inner_timeline:
        return

    id_map: dict[str, str] = {}
    for track in compound.inner_timeline.all_tracks:
        for clip in track.clips:
            old_id = clip.id
            new_id = f"clip_{uuid.uuid4().hex[:8]}"
            clip.id = new_id
            id_map[old_id] = new_id
            if isinstance(clip, CompoundClip):
                _remap_compound_inner_ids(clip)
            # A clip's own linked_clip_id (e.g. a CompoundAudioClip's
            # link back to its CompoundClip, or a split's link between
            # halves) refers to another clip *within this same
            # inner_timeline*, so it needs remapping too -- but the
            # target might not have been visited yet, so this is
            # resolved in a second pass below once id_map is complete.

    if not id_map:
        return

    for track in compound.inner_timeline.all_tracks:
        for clip in track.clips:
            linked = getattr(clip, "linked_clip_id", None)
            if linked and linked in id_map:
                clip.linked_clip_id = id_map[linked]
            compound_ref = getattr(clip, "compound_clip_id", None)
            if compound_ref and compound_ref in id_map:
                clip.compound_clip_id = id_map[compound_ref]

    # Update this compound's own exposed-parameter mappings so
    # `apply_parameters()` still finds each target clip by its new id --
    # otherwise `set_parameter()`/exposed defaults would silently stop
    # reaching any inner clip after a duplication.
    for param in compound.exposed_parameters:
        if param.target_clip_id in id_map:
            param.target_clip_id = id_map[param.target_clip_id]


class InsertMode(str, Enum):
    OVERLAP = "overlap"  # Place clip at timeline_start; allow overlap
    RIPPLE = "ripple"  # Shift subsequent clips right to make room


class TrackKind(str, Enum):
    VISUAL = "visual"
    AUDIO = "audio"


TClip = TypeVar("TClip", bound=Clip)


class Track(VisualKitModel, Generic[TClip]):
    """A single track holding an ordered, non-overlapping-by-default list of clips."""

    id: str = Field(default_factory=lambda: f"track_{uuid.uuid4().hex[:8]}")
    clips: list[TClip] = Field(default_factory=list)

    def add_clip(self, clip: TClip, mode: InsertMode = InsertMode.OVERLAP, *, validate: bool = False) -> None:
        """Add a clip to this track.

        In RIPPLE mode, every existing clip whose span starts at or after the
        new clip's insertion point is pushed right by the new clip's
        duration, opening a gap for it. If the insertion point instead falls
        *inside* an already-existing clip's span, there is no unambiguous way
        to "make room" without splitting that clip -- which this method does
        not do -- so an `InvalidTrackOperationError` is raised rather than
        silently leaving clips overlapping.

        `validate` (default False, for backwards compatibility -- OVERLAP
        mode's whole point is that it permits overlap) opts into checking
        the result against `validate_clips()`. In OVERLAP mode this is
        checked *before* mutating anything, so a rejected insert never
        touches the track. In RIPPLE mode the check runs after (ripple's own
        math already prevents overlap by construction; this is a cheap
        defense-in-depth net, not the primary guard).
        """
        if mode == InsertMode.RIPPLE:
            insertion_point = clip.timeline_start

            # Validate first, mutate second: iteration order over self.clips
            # is incidental, so a clip that would need to raise must be
            # found before any other clip is shifted -- otherwise a failed
            # insert could leave the track partially rippled.
            for existing in self.clips:
                existing_end = existing.timeline_start + existing.duration
                if existing.timeline_start < insertion_point < existing_end:
                    raise InvalidTrackOperationError(
                        f"Cannot ripple-insert clip '{clip.id}' at {insertion_point}: it falls "
                        f"inside existing clip '{existing.id}' (spans {existing.timeline_start} "
                        f"to {existing_end}). Split or move the existing clip first."
                    )

            for existing in self.clips:
                if existing.timeline_start >= insertion_point:
                    existing.timeline_start = existing.timeline_start + clip.duration
        elif validate:
            conflicts = self._overlap_conflicts(clip.timeline_start, clip.timeline_start + clip.duration)
            if conflicts:
                raise TimelineValidationError(
                    f"Cannot add clip '{clip.id}' at {clip.timeline_start}: " + "; ".join(conflicts)
                )

        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.timeline_start.seconds)

        if validate and mode == InsertMode.RIPPLE:
            errors = self.validate_clips()
            if errors:
                raise TimelineValidationError("; ".join(errors))

    def remove_clip(self, clip_id: str) -> bool:
        """Remove a clip from this track by ID."""
        for i, c in enumerate(self.clips):
            if c.id == clip_id:
                del self.clips[i]
                return True
        return False

    def get_clip(self, clip_id: str) -> TClip | None:
        """Get a clip on this track by ID."""
        for c in self.clips:
            if c.id == clip_id:
                return c
        return None

    def get_clip_at(self, time: Time) -> TClip | None:
        """Return the clip on this track under the playhead at `time`.

        A clip's span is start-inclusive, end-exclusive: `[timeline_start,
        timeline_start + duration)`. Returns the first match in start-time
        order if the track is in an invalid, overlapping state; on a valid
        (non-overlapping) track there can be at most one match anyway.
        """
        time = Time(time)
        for c in self.clips:
            if c.timeline_start <= time < (c.timeline_start + c.duration):
                return c
        return None

    def _overlap_conflicts(self, start: Time, end: Time, exclude_id: str | None = None) -> list[str]:
        """Return a description for every existing clip (other than `exclude_id`)
        whose span intersects the half-open interval [start, end)."""
        conflicts: list[str] = []
        for c in self.clips:
            if c.id == exclude_id:
                continue
            c_start = c.timeline_start
            c_end = c.timeline_start + c.duration
            if start < c_end and c_start < end:
                conflicts.append(f"would overlap clip '{c.id}' (spans {c_start} to {c_end})")
        return conflicts

    def validate_clips(self) -> list[str]:
        """Ensures clips on this track do not overlap in time."""
        errors: list[str] = []
        ordered = sorted(self.clips, key=lambda c: c.timeline_start.seconds)
        for prev, cur in zip(ordered, ordered[1:]):
            prev_end = prev.timeline_start.seconds + prev.duration.seconds
            if cur.timeline_start.seconds < prev_end:
                errors.append(
                    f"clip {cur.id} starts at {cur.timeline_start.seconds}s, "
                    f"before clip {prev.id} ends at {prev_end}s"
                )
        return errors

    def split_clip(self, clip_id: str, at_time: Time, *, validate: bool = True) -> tuple[TClip, TClip]:
        """Split a clip in two at `at_time`, an absolute timeline position.

        `at_time` must fall strictly inside the clip's span -- splitting
        exactly at its start or end wouldn't produce two non-empty halves.
        The original clip object is mutated in place to become the first
        half (keeping its id); a new clip is appended as the second half.

        For any clip carrying a `source` (MediaClip, AudioClip, and
        CodedVisualClip, which extends MediaClip), the second half's
        `source.start` is advanced by the split offset scaled by `speed` --
        at speed=2.0, one second of timeline time consumes two seconds of
        source time, so the offset into source must be scaled accordingly,
        not copied 1:1. For clip types that support `linked_clip_id`
        (MediaClip, AudioClip), the two halves are cross-linked so the split
        provenance is discoverable later.

        CompoundClip (and its CompoundAudioClip companion) cannot be split
        here: a compound's inner_timeline would need to be deep-copied and
        have every inner clip's own in/out points re-derived for whichever
        half it now belongs to (including any inner clips that themselves
        straddle the split point), which this method does not attempt.
        Flatten the compound first if you need to split its content.

        If the original clip is a CodedVisualClip that had already
        compiled, both halves have their compiled `media_source` cleared and
        `compile_status` reset to PENDING: the existing render was produced
        for the pre-split duration (the compiler bakes `duration` into both
        its cache key and its ffmpeg `-t` argument), and reusing it for the
        now-shorter/differently-timed halves would silently ship a stale
        render. Recompiling from PENDING regenerates the correct output
        lazily, the same way an unsplit clip would compile on first use.
        """
        at_time = Time(at_time)
        clip = self.get_clip(clip_id)
        if clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found on track '{self.id}'.")

        if isinstance(clip, (CompoundClip, CompoundAudioClip)):
            raise InvalidSplitError(
                f"Cannot split clip '{clip_id}': CompoundClip splitting isn't supported -- it "
                "would require deep-copying inner_timeline and re-deriving in/out points for "
                "every clip it contains. Flatten the compound clip first, or restructure its "
                "inner_timeline directly."
            )

        start = clip.timeline_start
        end = start + clip.duration
        if not (start < at_time < end):
            raise InvalidSplitError(
                f"Split point {at_time} is not strictly inside clip '{clip_id}' (spans {start} to {end})."
            )

        delta = Time(at_time.value - start.value)  # positive by the bounds check above

        first = clip
        second = clip.model_copy(deep=True)
        second.id = f"clip_{uuid.uuid4().hex[:8]}"
        second.timeline_start = at_time
        second.duration = Time(end.value - at_time.value)

        first.duration = delta

        if hasattr(second, "source"):
            second.source.start = Time(second.source.start.value + delta.value * _speed_fraction(clip.speed))

        for half in (first, second):
            if isinstance(half, CodedVisualClip) and half.compile_status == CompileStatus.READY:
                half.media_source = None
                half.compile_status = CompileStatus.PENDING

        if hasattr(first, "linked_clip_id"):
            first.linked_clip_id = second.id
            second.linked_clip_id = first.id

        self.clips.append(second)
        self.clips.sort(key=lambda c: c.timeline_start.seconds)

        if validate:
            errors = self.validate_clips()
            if errors:
                raise TimelineValidationError("; ".join(errors))

        return first, second

    def trim_in(self, clip_id: str, new_in: Time, *, validate: bool = True) -> TClip:
        """Move a clip's head to `new_in`, an absolute timeline position.

        `new_in` may be later than the clip's current start (the common
        case: shrinking the clip by trimming off its head) or earlier (the
        less common case: revealing more pre-roll, if the underlying source
        has it). The clip's end stays fixed; only its start and duration
        move.

        For clips carrying a `source`, `source.start` is advanced (or
        pulled back) by the same delta, scaled by `speed`, so the clip
        keeps showing the same in-source content at the new timeline
        position -- see `split_clip` for why the scaling matters. Advancing
        past the point where `source.start` would go negative raises,
        since that would mean revealing source content that doesn't exist.

        CompoundClip is not supported: it has no field recording "this many
        seconds of inner_timeline already consumed", so moving its
        timeline_start forward would just delay when its (unchanged) inner
        content starts playing rather than skip into it -- the wrong result
        for a head trim. `trim_out` (which only shortens the tail) works
        fine for CompoundClip, since it doesn't have this problem.
        """
        new_in = Time(new_in)
        clip = self.get_clip(clip_id)
        if clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found on track '{self.id}'.")

        if isinstance(clip, CompoundClip):
            raise InvalidTrackOperationError(
                f"Cannot trim_in CompoundClip '{clip_id}': its inner_timeline has no independent "
                "notion of playback offset, so advancing timeline_start would delay its content "
                "rather than skip into it. Use trim_out, or edit inner_timeline directly."
            )

        old_start, old_end = clip.timeline_start, clip.timeline_start + clip.duration
        delta = new_in.value - old_start.value  # signed; Time subtraction would raise if negative
        new_duration_value = old_end.value - new_in.value
        if new_duration_value <= 0:
            raise InvalidTrackOperationError(
                f"trim_in({new_in}) would leave clip '{clip_id}' with zero or negative duration "
                f"(clip currently spans {old_start} to {old_end})."
            )

        new_source_start: Time | None = None
        if hasattr(clip, "source"):
            candidate = clip.source.start.value + delta * _speed_fraction(clip.speed)
            if candidate < 0:
                raise InvalidTrackOperationError(
                    f"trim_in({new_in}) on clip '{clip_id}' would require source.start before 0 "
                    f"(speed={clip.speed}); there's no source content that far back."
                )
            new_source_start = Time(candidate)

        if validate:
            conflicts = self._overlap_conflicts(new_in, old_end, exclude_id=clip_id)
            if conflicts:
                raise TimelineValidationError(
                    f"Cannot trim_in clip '{clip_id}' to {new_in}: " + "; ".join(conflicts)
                )

        clip.timeline_start = new_in
        clip.duration = Time(new_duration_value)
        if new_source_start is not None:
            clip.source.start = new_source_start

        if isinstance(clip, CodedVisualClip) and clip.compile_status == CompileStatus.READY:
            clip.media_source = None
            clip.compile_status = CompileStatus.PENDING

        return clip

    def trim_out(self, clip_id: str, new_out: Time, *, validate: bool = True) -> TClip:
        """Move a clip's tail to `new_out`, an absolute timeline position.

        `new_out` may be earlier than the clip's current end (shrinking it)
        or later (extending it, if the underlying source has more content
        past the current out point -- this schema doesn't track total
        source length, so that's on the caller to know). `timeline_start`
        and `source.start` are untouched: the clip keeps starting at the
        same point in its source, it just plays more or less of it.

        Unlike `trim_in`, this works uniformly for every clip type
        including CompoundClip -- shortening or lengthening the tail
        doesn't require knowing anything about inner playback offset.
        """
        new_out = Time(new_out)
        clip = self.get_clip(clip_id)
        if clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found on track '{self.id}'.")

        new_duration_value = new_out.value - clip.timeline_start.value
        if new_duration_value <= 0:
            raise InvalidTrackOperationError(
                f"trim_out({new_out}) would leave clip '{clip_id}' with zero or negative duration "
                f"(clip starts at {clip.timeline_start})."
            )

        if validate:
            conflicts = self._overlap_conflicts(clip.timeline_start, new_out, exclude_id=clip_id)
            if conflicts:
                raise TimelineValidationError(
                    f"Cannot trim_out clip '{clip_id}' to {new_out}: " + "; ".join(conflicts)
                )

        clip.duration = Time(new_duration_value)

        if isinstance(clip, CodedVisualClip) and clip.compile_status == CompileStatus.READY:
            clip.media_source = None
            clip.compile_status = CompileStatus.PENDING

        return clip

    def ripple_delete(self, clip_id: str, *, validate: bool = True) -> bool:
        """Remove a clip and shift every later clip left to close the gap.

        The exact inverse of `add_clip(mode=RIPPLE)`: every clip whose start
        is at or after the removed clip's *end* is shifted left by the
        removed clip's duration. A clip that starts before the removed
        clip's end (which shouldn't happen on an already-valid track, but
        can if the track was left overlapping some other way) is left in
        place rather than guessed at -- mirroring add_clip(RIPPLE)'s own
        refusal to resolve that ambiguity by insertion.

        Returns False (no-op) if the clip isn't found, matching
        `remove_clip`'s contract.
        """
        clip = self.get_clip(clip_id)
        if clip is None:
            return False

        removed_end = clip.timeline_start + clip.duration
        removed_duration_value = clip.duration.value

        self.clips = [c for c in self.clips if c.id != clip_id]
        for existing in self.clips:
            if existing.timeline_start >= removed_end:
                existing.timeline_start = Time(existing.timeline_start.value - removed_duration_value)

        self.clips.sort(key=lambda c: c.timeline_start.seconds)

        if validate:
            errors = self.validate_clips()
            if errors:
                raise TimelineValidationError("; ".join(errors))

        return True

    def duplicate_clip(
        self,
        clip_id: str,
        *,
        new_timeline_start: Time | None = None,
        mode: InsertMode = InsertMode.OVERLAP,
        validate: bool = True,
    ) -> TClip:
        """Duplicate a clip on this track, returning the new copy.

        Defaults to placing the copy immediately after the original (at
        `timeline_start + duration`) so the common "duplicate it" case
        doesn't land the copy directly on top of the original even under
        OVERLAP mode. Pass `new_timeline_start` to place it elsewhere, or
        `mode=RIPPLE` to insert it and shift what follows.

        The copy gets a fresh id and, for clip types that carry
        `linked_clip_id`, that field is cleared on the copy -- a duplicate
        is a new, independent clip, not the other half of whatever the
        original was linked to (e.g. a prior split).
        """
        original = self.get_clip(clip_id)
        if original is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found on track '{self.id}'.")

        if new_timeline_start is not None:
            target_start = Time(new_timeline_start)
        else:
            target_start = original.timeline_start + original.duration
        target_end = target_start + original.duration

        if validate and mode == InsertMode.OVERLAP:
            conflicts = self._overlap_conflicts(target_start, target_end)
            if conflicts:
                raise TimelineValidationError(
                    f"Cannot duplicate clip '{clip_id}' to {target_start}: " + "; ".join(conflicts)
                )

        duplicate = original.model_copy(deep=True)
        duplicate.id = f"clip_{uuid.uuid4().hex[:8]}"
        if hasattr(duplicate, "linked_clip_id"):
            duplicate.linked_clip_id = None
        duplicate.timeline_start = target_start

        if isinstance(duplicate, CompoundClip) and duplicate.inner_timeline:
            _remap_compound_inner_ids(duplicate)

        # RIPPLE mode does its own overlap-avoidance (or raises) internally;
        # OVERLAP mode was already checked above when validate=True.
        self.add_clip(duplicate, mode=mode)

        return duplicate


class VideoTrack(Track[VisualContent]):
    """A track that holds visual clips."""

    kind: Literal[TrackKind.VISUAL] = Field(default=TrackKind.VISUAL, frozen=True)
    clips: list[VisualContent] = Field(default_factory=list)


class AudioTrack(Track[AudioContent]):
    """A track that holds audio clips."""

    kind: Literal[TrackKind.AUDIO] = Field(default=TrackKind.AUDIO, frozen=True)
    clips: list[AudioContent] = Field(default_factory=list)


class Timeline(VisualKitModel):
    """Owns all video and audio tracks."""

    video_tracks: list[VideoTrack] = Field(default_factory=list)
    audio_tracks: list[AudioTrack] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _parse_tracks_input(cls, data: Any) -> Any:
        """Allow passing `tracks=[...]` directly to Timeline."""
        if isinstance(data, dict) and "tracks" in data:
            tracks = data.pop("tracks")
            v_tracks = data.setdefault("video_tracks", [])
            a_tracks = data.setdefault("audio_tracks", [])
            for t in tracks:
                if isinstance(t, VideoTrack) or getattr(t, "kind", None) == TrackKind.VISUAL:
                    v_tracks.append(t)
                elif isinstance(t, AudioTrack) or getattr(t, "kind", None) == TrackKind.AUDIO:
                    a_tracks.append(t)
        return data

    @property
    def all_tracks(self) -> list[Track]:
        """Video tracks first in composite order, then audio tracks."""
        return [*self.video_tracks, *self.audio_tracks]

    def add_video_track(self, index: int | None = None) -> VideoTrack:
        """Add and return a new VideoTrack."""
        track = VideoTrack()
        if index is None:
            self.video_tracks.append(track)
        else:
            self.video_tracks.insert(index, track)
        return track

    def add_audio_track(self, index: int | None = None) -> AudioTrack:
        """Add and return a new AudioTrack."""
        track = AudioTrack()
        if index is None:
            self.audio_tracks.append(track)
        else:
            self.audio_tracks.insert(index, track)
        return track

    def add_track(self, track: Track, index: int | None = None) -> None:
        """Add an existing track to the timeline."""
        if isinstance(track, VideoTrack):
            if index is None:
                self.video_tracks.append(track)
            else:
                self.video_tracks.insert(index, track)
        elif isinstance(track, AudioTrack):
            if index is None:
                self.audio_tracks.append(track)
            else:
                self.audio_tracks.insert(index, track)
        else:
            raise ValueError(f"Unknown track type: {type(track)}")

    def add_clip(
        self,
        *clips: Clip,
        track_index: int = 0,
        mode: InsertMode = InsertMode.OVERLAP,
        validate: bool = False,
    ) -> None:
        """Add clips directly to the timeline, automatically routing by clip type.

        If `track_index` is beyond the current number of tracks, tracks are
        created up to and including that index (rather than only ever
        appending a single new track), so `track_index` always refers to the
        track the caller asked for.

        `validate` (default False, for backwards compatibility) is passed
        through to each underlying `Track.add_clip` call -- see its
        docstring for what it checks in OVERLAP vs RIPPLE mode.
        """
        # handling track index
        if track_index < 0:
            raise ValueError("track_index must be non-negative")

        while len(self.video_tracks) <= track_index:
            self.add_video_track()
        while len(self.audio_tracks) <= track_index:
            self.add_audio_track()

        video_track_index = track_index
        audio_track_index = track_index

        for clip in clips:
            if clip.clip_type in ("media", "text", "coded_visual", "compound"):
                self.video_tracks[video_track_index].add_clip(clip, mode=mode, validate=validate)

                # If compound clip, auto-create and route companion to audio lane
                if isinstance(clip, CompoundClip):
                    companion = clip.create_audio_companion()
                    self.audio_tracks[audio_track_index].add_clip(companion, mode=mode, validate=validate)

            elif clip.clip_type in ("audio", "compound_audio"):
                self.audio_tracks[audio_track_index].add_clip(clip, mode=mode, validate=validate)

    def get_clip(self, clip_id: str) -> tuple[Track, Any] | tuple[None, None]:
        """Find a clip and its containing track by clip ID."""
        for track in self.all_tracks:
            clip = track.get_clip(clip_id)
            if clip is not None:
                return track, clip
        return None, None

    def get_clips_at(self, time: Time) -> list[tuple[Track, Any]]:
        """Return every (track, clip) pair across all tracks active at `time`.

        Unlike `Track.get_clip_at`, this can legitimately return more than
        one result: several tracks composite together, so more than one
        clip is normally "under the playhead" at once (e.g. a video track
        and an audio track, or two overlaid video tracks).
        """
        time = Time(time)
        results: list[tuple[Track, Any]] = []
        for track in self.all_tracks:
            clip = track.get_clip_at(time)
            if clip is not None:
                results.append((track, clip))
        return results

    def remove_clip(self, clip_id: str) -> bool:
        """Remove a clip from whichever track owns it."""
        for track in self.all_tracks:
            if track.remove_clip(clip_id):
                return True
        return False

    def move_clip_track(
        self,
        clip_id: str,
        new_track_id: str,
        *,
        mode: InsertMode = InsertMode.OVERLAP,
        validate: bool = False,
    ) -> bool:
        """Move a clip to another compatible track.

        `mode` controls how the clip is placed on `dest_track` (previously
        this always used OVERLAP regardless of what was asked for, silently
        ignoring a caller's RIPPLE intent); `validate` is passed through to
        the destination track's `add_clip`.
        """
        src_track, clip = self.get_clip(clip_id)
        if not src_track or not clip:
            raise ValueError(f"Clip '{clip_id}' not found.")

        dest_track = next((t for t in self.all_tracks if t.id == new_track_id), None)
        if not dest_track:
            raise ValueError(f"Target track '{new_track_id}' not found.")

        # Type safety checks
        if isinstance(dest_track, VideoTrack) and not isinstance(src_track, VideoTrack):
            raise TypeError("Cannot move audio clip into a VideoTrack.")
        if isinstance(dest_track, AudioTrack) and not isinstance(src_track, AudioTrack):
            raise TypeError("Cannot move visual clip into an AudioTrack.")

        src_track.remove_clip(clip_id)
        dest_track.add_clip(clip, mode=mode, validate=validate)
        return True

    def split_clip(self, clip_id: str, at_time: Time, *, validate: bool = True) -> tuple[Clip, Clip]:
        """Split whichever clip has `clip_id`, wherever it lives. See `Track.split_clip`."""
        track, clip = self.get_clip(clip_id)
        if track is None or clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found.")
        return track.split_clip(clip_id, at_time, validate=validate)

    def trim_in(self, clip_id: str, new_in: Time, *, validate: bool = True) -> Clip:
        """Trim the head of whichever clip has `clip_id`, wherever it lives. See `Track.trim_in`."""
        track, clip = self.get_clip(clip_id)
        if track is None or clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found.")
        return track.trim_in(clip_id, new_in, validate=validate)

    def trim_out(self, clip_id: str, new_out: Time, *, validate: bool = True) -> Clip:
        """Trim the tail of whichever clip has `clip_id`, wherever it lives.

        If the clip is a CompoundClip with a linked CompoundAudioClip
        companion, the companion is trimmed to the same absolute `new_out`
        too, so the two lanes stay in sync -- see `Track.trim_out`.
        """
        track, clip = self.get_clip(clip_id)
        if track is None or clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found.")

        new_out = Time(new_out)
        trimmed = track.trim_out(clip_id, new_out, validate=validate)

        if isinstance(clip, CompoundClip) and clip.linked_clip_id:
            companion_track, companion = self.get_clip(clip.linked_clip_id)
            if companion_track is not None and companion is not None:
                companion_track.trim_out(companion.id, new_out, validate=validate)

        return trimmed

    def ripple_delete(self, clip_id: str, *, validate: bool = True) -> bool:
        """Ripple-delete whichever clip has `clip_id`, wherever it lives.

        If the clip is a CompoundClip with a linked CompoundAudioClip
        companion, the companion is ripple-deleted from its own (audio)
        track too, so both lanes stay aligned -- otherwise the audio track
        would end up with a dangling orphan clip and the two lanes would
        drift out of sync relative to each other. See `Track.ripple_delete`.
        """
        track, clip = self.get_clip(clip_id)
        if track is None or clip is None:
            return False

        companion_id = clip.linked_clip_id if isinstance(clip, CompoundClip) else None

        removed = track.ripple_delete(clip_id, validate=validate)

        if removed and companion_id:
            companion_track, companion = self.get_clip(companion_id)
            if companion_track is not None and companion is not None:
                companion_track.ripple_delete(companion.id, validate=validate)

        return removed

    def duplicate_clip(
        self,
        clip_id: str,
        *,
        new_timeline_start: Time | None = None,
        mode: InsertMode = InsertMode.OVERLAP,
        validate: bool = True,
    ) -> Clip:
        """Duplicate whichever clip has `clip_id`, wherever it lives.

        If the clip is a CompoundClip with a linked CompoundAudioClip
        companion, the companion is duplicated too (placed at the same new
        `timeline_start`) and the two duplicates are cross-linked to each
        other -- mirroring how `add_clip` auto-creates and routes a
        companion for a freshly-added CompoundClip. See `Track.duplicate_clip`.
        """
        track, clip = self.get_clip(clip_id)
        if track is None or clip is None:
            raise ClipNotFoundError(f"Clip '{clip_id}' not found.")

        duplicate = track.duplicate_clip(
            clip_id, new_timeline_start=new_timeline_start, mode=mode, validate=validate
        )

        if isinstance(clip, CompoundClip) and clip.linked_clip_id:
            companion_track, companion = self.get_clip(clip.linked_clip_id)
            if companion_track is not None and companion is not None:
                companion_duplicate = companion_track.duplicate_clip(
                    companion.id,
                    new_timeline_start=duplicate.timeline_start,
                    mode=mode,
                    validate=validate,
                )
                duplicate.linked_clip_id = companion_duplicate.id
                if isinstance(companion_duplicate, CompoundAudioClip):
                    companion_duplicate.compound_clip_id = duplicate.id

        return duplicate

    def validate_tracks(self) -> list[str]:
        """Validation on tracks before compiling. Returns list of error messages."""
        errors: list[str] = []
        seen_track_ids: set[str] = set()
        seen_clip_ids: set[str] = set()

        for track in self.all_tracks:
            if track.id in seen_track_ids:
                errors.append(f"duplicate track id: {track.id}")
            seen_track_ids.add(track.id)

            errors.extend(f"track {track.id}: {e}" for e in track.validate_clips())

            for clip in track.clips:
                if clip.id in seen_clip_ids:
                    errors.append(f"duplicate clip id across timeline: {clip.id}")
                seen_clip_ids.add(clip.id)

        return errors

    @property
    def duration(self) -> Time:
        """Returns the total duration of the timeline, computed from the latest clip endpoint."""
        latest = Time.zero()
        for track in self.all_tracks:
            for clip in track.clips:
                clip_end = clip.timeline_start + clip.duration
                if clip_end > latest:
                    latest = clip_end
        return latest

    def flatten(self, force_compile: bool = False, render_video: bool = False) -> Timeline:
        """Resolve variables, compile coded visuals, and flatten all compound clips

        into a concrete Timeline.
        """
        from visualkit.engine.pipeline import TimelinePipeline

        return TimelinePipeline().process(
            self,
            force_compile=force_compile,
            render_video=render_video,
        )

    def export_to_resolve(
        self,
        output_path: Any,
        fps: float = 30.0,
        resolution: tuple[int, int] = (1920, 1080),
        project_name: str = "VisualKit Project",
        sequence_name: str = "VisualKit Sequence",
        render_video: bool = False,
        asset_resolver: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Export timeline to DaVinci Resolve-compatible XML (FCP 7 XML / XMEML or FCPXML)."""
        from visualkit.exporters.resolve import DaVinciResolveExporter

        exporter = DaVinciResolveExporter(
            fps=fps,
            resolution=resolution,
            project_name=project_name,
            sequence_name=sequence_name,
            asset_resolver=asset_resolver,
        )
        return exporter.export(
            self,
            output_path=output_path,
            render_video=render_video,
            asset_resolver=asset_resolver,
            **kwargs,
        )

    def export_to_video(
        self,
        output_path: Any,
        fps: float = 30.0,
        resolution: tuple[int, int] = (1920, 1080),
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        asset_resolver: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Render and export the timeline into a standalone video file (MP4/WebM) using FFmpeg."""
        from visualkit.exporters.video import FFmpegVideoExporter

        exporter = FFmpegVideoExporter(
            fps=fps,
            resolution=resolution,
            video_codec=video_codec,
            audio_codec=audio_codec,
            asset_resolver=asset_resolver,
        )
        return exporter.export(
            self,
            output_path=output_path,
            asset_resolver=asset_resolver,
            **kwargs,
        )
