from __future__ import annotations

import uuid
from abc import ABC
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from visualkit.models.clips import (
    AudioContent,
    Clip,
    CompoundClip,
    VisualContent,
)


class InsertMode(str, Enum):
    OVERLAP = "overlap"  # Place clip at timeline_start; allow overlap
    RIPPLE = "ripple"  # Shift subsequent clips right to make room


class TrackKind(str, Enum):
    VISUAL = "visual"
    AUDIO = "audio"


TClip = TypeVar("TClip", bound=Clip)


class Track(BaseModel, Generic[TClip]):
    """A single track holding an ordered, non-overlapping-by-default list of clips."""

    id: str = Field(default_factory=lambda: f"track_{uuid.uuid4().hex[:8]}")
    clips: list[TClip] = Field(default_factory=list)

    def add_clip(self, clip: TClip, mode: InsertMode = InsertMode.OVERLAP) -> None:
        """Add a clip to this track."""
        if mode == InsertMode.RIPPLE:
            for existing in self.clips:
                if existing.timeline_start >= clip.timeline_start:
                    existing.timeline_start = existing.timeline_start + clip.duration

        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.timeline_start.seconds)

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


class VideoTrack(Track[VisualContent]):
    """A track that holds visual clips."""

    kind: Literal[TrackKind.VISUAL] = Field(default=TrackKind.VISUAL, frozen=True)
    clips: list[VisualContent] = Field(default_factory=list)


class AudioTrack(Track[AudioContent]):
    """A track that holds audio clips."""

    kind: Literal[TrackKind.AUDIO] = Field(default=TrackKind.AUDIO, frozen=True)
    clips: list[AudioContent] = Field(default_factory=list)


class Timeline(BaseModel):
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
    ) -> None:
        """Add clips directly to the timeline, automatically routing by clip type."""
        # handling track index
        if track_index < 0:
            raise ValueError("track_index must be non-negative")
        if track_index >= len(self.video_tracks):
            self.add_video_track()
            video_track_index = len(self.video_tracks) - 1
        else:
            video_track_index = track_index
        if track_index >= len(self.audio_tracks):
            self.add_audio_track()
            audio_track_index = len(self.audio_tracks) - 1
        else:
            audio_track_index = track_index

        for clip in clips:
            if clip.clip_type in ("media", "text", "coded_visual", "compound"):
                self.video_tracks[video_track_index].add_clip(clip, mode=mode)

                # If compound clip, auto-create and route companion to audio lane
                if isinstance(clip, CompoundClip):
                    companion = clip.create_audio_companion()
                    self.audio_tracks[audio_track_index].add_clip(companion, mode=mode)

            elif clip.clip_type in ("audio", "compound_audio"):
                self.audio_tracks[audio_track_index].add_clip(clip, mode=mode)

    def get_clip(self, clip_id: str) -> tuple[Track, Any] | tuple[None, None]:
        """Find a clip and its containing track by clip ID."""
        for track in self.all_tracks:
            clip = track.get_clip(clip_id)
            if clip is not None:
                return track, clip
        return None, None

    def remove_clip(self, clip_id: str) -> bool:
        """Remove a clip from whichever track owns it."""
        for track in self.all_tracks:
            if track.remove_clip(clip_id):
                return True
        return False

    def move_clip_track(self, clip_id: str, new_track_id: str) -> bool:
        """Move a clip to another compatible track."""
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
        dest_track.add_clip(clip)
        return True

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

    def flatten(self, force_compile: bool = False) -> Timeline:
        """Resolve variables, compile coded visuals, and flatten all compound clips

        into a concrete Timeline.
        """
        from visualkit.engine.pipeline import TimelinePipeline

        return TimelinePipeline().process(self, force_compile=force_compile)

    def export_to_resolve(
        self,
        output_path: Any,
        fps: float = 30.0,
        resolution: tuple[int, int] = (1920, 1080),
        project_name: str = "VisualKit Project",
        sequence_name: str = "VisualKit Sequence",
    ) -> Any:
        """Export timeline to DaVinci Resolve-compatible XML (FCP 7 XML / XMEML or FCPXML)."""
        from visualkit.exporters.resolve import DaVinciResolveExporter

        exporter = DaVinciResolveExporter(
            fps=fps,
            resolution=resolution,
            project_name=project_name,
            sequence_name=sequence_name,
        )
        return exporter.export(self, output_path=output_path)


