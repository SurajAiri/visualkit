from copy import deepcopy
from typing import Any

from visualkit.coded_visual.compiler import CodedVisualCompiler
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.base import Source
from visualkit.models.clips.coded_visual import CodedVisualClip, CompileStatus
from visualkit.models.clips.compound import CompoundAudioClip, CompoundClip
from visualkit.models.clips.media import MediaClip
from visualkit.models.clips.text import TextClip
from visualkit.models.timeline import AudioTrack, Timeline, VideoTrack


class TimelinePipeline:
    """Processing and transformation pipeline for Timelines.

    Handles variable resolution, compilation of coded visuals, and timeline flattening.
    """

    def __init__(self, compiler: CodedVisualCompiler | None = None):
        self.compiler = compiler or CodedVisualCompiler()

    def resolve_variables(self, timeline: Timeline) -> Timeline:
        """Recursively apply parameters down through all compound clips in the timeline."""
        for track in timeline.video_tracks:
            for clip in track.clips:
                if isinstance(clip, CompoundClip):
                    clip.apply_parameters()
                    if clip.inner_timeline:
                        self.resolve_variables(clip.inner_timeline)
        return timeline

    def compile_coded_visuals(
        self,
        timeline: Timeline,
        force: bool = False,
        render_video: bool = False,
    ) -> Timeline:
        """Find and compile all CodedVisualClip instances across all tracks and inner timelines."""
        for track in timeline.video_tracks:
            for clip in track.clips:
                if isinstance(clip, CodedVisualClip):
                    if force or clip.compile_status != CompileStatus.READY or not clip.media_source:
                        self.compiler.compile(clip, force=force, render_video=render_video)
                elif isinstance(clip, CompoundClip) and clip.inner_timeline:
                    self.compile_coded_visuals(
                        clip.inner_timeline,
                        force=force,
                        render_video=render_video,
                    )
        return timeline

    def flatten(self, timeline: Timeline) -> Timeline:
        """Expand all CompoundClips and resolve CodedVisualClips into a concrete Timeline.

        The resulting timeline consists strictly of primitive MediaClip, TextClip, and AudioClip instances
        with absolute timeline coordinates and composited transforms/audio levels.
        """
        flattened = Timeline()

        # 1. Map audio companion volume multipliers, and which audio track
        # each compound's companion clip sits on, if present. The latter is
        # what lets sibling compound clips' inner audio land on distinct
        # audio tracks in the flattened output instead of colliding on
        # whichever track happens to be their *inner* track 0.
        companion_volumes: dict[str, float] = {}
        companion_track_idx: dict[str, int] = {}
        for track_idx, track in enumerate(timeline.audio_tracks):
            for clip in track.clips:
                if isinstance(clip, CompoundAudioClip):
                    companion_volumes[clip.compound_clip_id] = 0.0 if clip.mute else clip.volume
                    companion_track_idx[clip.compound_clip_id] = track_idx

        # Reserve every outer video track index first (0..N-1), then hand
        # out non-overlapping blocks of *additional* destination tracks to
        # each top-level CompoundClip whose reserved span would otherwise
        # overlap another outer track's own content.
        # Previously a compound's inner track 0 was assigned
        # `base_v_track_idx=track_idx` unconditionally -- the same index
        # as the outer video track the compound clip itself sits on -- so
        # any other, unrelated clip sharing that same outer track (e.g. a
        # second overlay, or a second CompoundClip), or sharing any outer
        # track the compound's *wider* inner span would reach, collided
        # with the compound's inner content in the flattened output. A
        # compound whose entire reserved span sits on otherwise-empty
        # outer track slots has nothing to collide with there, so it
        # keeps reusing that track index (matching prior behavior exactly
        # for the common single-clip-per-track case); only genuine
        # overlap with another track's content triggers reserving a
        # dedicated block elsewhere.
        next_free_v_track = len(timeline.video_tracks)
        compound_v_track_base: dict[str, int] = {}
        for track_idx, v_track in enumerate(timeline.video_tracks):
            for clip in v_track.clips:
                if not isinstance(clip, CompoundClip):
                    continue
                span = self._compound_video_track_span(clip)
                span_range = range(track_idx, track_idx + span)
                overlaps_other_content = any(
                    i != track_idx and i < len(timeline.video_tracks) and len(timeline.video_tracks[i].clips) > 0
                    for i in span_range
                ) or len(v_track.clips) > 1
                if overlaps_other_content:
                    compound_v_track_base[clip.id] = next_free_v_track
                    next_free_v_track += span
                else:
                    compound_v_track_base[clip.id] = track_idx

        # 2. Process Video Tracks
        for track_idx, v_track in enumerate(timeline.video_tracks):
            while len(flattened.video_tracks) <= track_idx:
                flattened.add_video_track()

            for clip in v_track.clips:
                if isinstance(clip, CompoundClip):
                    # Prefer the audio track the compound's own companion
                    # clip lives on (its reserved "seat" on the audio lane);
                    # fall back to the video track index if no companion was
                    # ever created (e.g. the compound was constructed and
                    # added to a track directly, bypassing
                    # Timeline.add_clip's auto-companion routing).
                    base_a_track_idx = companion_track_idx.get(clip.id, track_idx)
                    self._flatten_compound_clip(
                        compound=clip,
                        target_timeline=flattened,
                        base_v_track_idx=compound_v_track_base[clip.id],
                        base_a_track_idx=base_a_track_idx,
                        companion_volumes=companion_volumes,
                    )
                elif isinstance(clip, CodedVisualClip):
                    # Resolve to MediaClip
                    media_clip = self._coded_visual_to_media(clip)
                    flattened.video_tracks[track_idx].add_clip(media_clip)
                else:
                    # Primitive clip (MediaClip, TextClip)
                    flattened.video_tracks[track_idx].add_clip(deepcopy(clip))

        # 3. Process Audio Tracks (standalone audio clips)
        for track_idx, a_track in enumerate(timeline.audio_tracks):
            while len(flattened.audio_tracks) <= track_idx:
                flattened.add_audio_track()

            for clip in a_track.clips:
                # CompoundAudioClips were already absorbed during compound expansion
                if isinstance(clip, AudioClip):
                    flattened.audio_tracks[track_idx].add_clip(deepcopy(clip))

        return flattened

    @classmethod
    def _compound_video_track_span(cls, compound: CompoundClip) -> int:
        """How many destination video tracks `compound` needs for itself
        and all its nested compounds, so sibling clips get non-overlapping
        destination ranges. At minimum 1 (even an empty/no-inner-timeline
        compound reserves its own slot, so index arithmetic for whatever
        comes after it stays simple and it can't accidentally overlap a
        sibling that does have content).
        """
        if not compound.inner_timeline:
            return 1

        span = len(compound.inner_timeline.video_tracks) or 1
        # A nested CompoundClip expands into *additional* tracks beyond
        # its own inner-track slot (see flatten()'s reservation pass),
        # so the parent's total span must include however much extra
        # room each nested compound will consume beyond the single slot
        # already counted for the inner track it sits on.
        for v_track in compound.inner_timeline.video_tracks:
            for child in v_track.clips:
                if isinstance(child, CompoundClip):
                    span += cls._compound_video_track_span(child) - 1
        return span

    def process(
        self,
        timeline: Timeline,
        force_compile: bool = False,
        render_video: bool = False,
    ) -> Timeline:
        """Run the full end-to-end pipeline: resolve variables -> compile coded visuals -> flatten."""
        self.resolve_variables(timeline)
        self.compile_coded_visuals(timeline, force=force_compile, render_video=render_video)
        return self.flatten(timeline)

    def _flatten_compound_clip(
        self,
        compound: CompoundClip,
        target_timeline: Timeline,
        base_v_track_idx: int,
        base_a_track_idx: int,
        companion_volumes: dict[str, float],
        accumulated_offset: Any = None,
        parent_speed: float = 1.0,
    ) -> None:
        """Recursively expands a CompoundClip onto target_timeline.

        `base_v_track_idx` / `base_a_track_idx` are the destination video /
        audio track offsets reserved for this compound: its inner track N
        expands onto destination track `base_idx + N`. Without a
        per-compound audio base, sibling compound clips' inner audio tracks
        would all collide on destination audio track N regardless of which
        compound (or which outer video track) they came from.
        """
        if not compound.inner_timeline:
            return

        from visualkit.utils.time import Time

        current_offset = accumulated_offset if accumulated_offset is not None else Time.zero()
        # compound.timeline_start is this compound's position measured in its
        # *parent's* local time. If an ancestor compound plays faster than
        # 1x (parent_speed > 1), that local position is compressed on the
        # root timeline by the same factor -- e.g. a nested compound sitting
        # at local t=4s inside a 2x-speed parent actually appears at t=2s of
        # occupied root-timeline span. Leaf clips get the equivalent
        # treatment below via effective_speed.
        compound_offset = current_offset + (compound.timeline_start / parent_speed)
        effective_speed = parent_speed * compound.speed
        audio_volume_mult = companion_volumes.get(compound.id, 1.0)

        # Expand inner video tracks
        for inner_v_idx, inner_v_track in enumerate(compound.inner_timeline.video_tracks):
            dest_v_idx = base_v_track_idx + inner_v_idx
            while len(target_timeline.video_tracks) <= dest_v_idx:
                target_timeline.add_video_track()

            for child_clip in inner_v_track.clips:
                if isinstance(child_clip, CompoundClip):
                    # Nested compound clip. Its own companion (if any) lives
                    # on one of *this* compound's inner audio tracks, so
                    # resolve its base the same way the top-level call does:
                    # prefer the audio track its companion sits on within
                    # compound.inner_timeline, falling back to the nested
                    # compound's position among its siblings.
                    nested_base_a_idx = self._companion_audio_track_index(
                        compound.inner_timeline,
                        child_clip.id,
                        default=base_a_track_idx,
                    )
                    self._flatten_compound_clip(
                        compound=child_clip,
                        target_timeline=target_timeline,
                        base_v_track_idx=dest_v_idx,
                        base_a_track_idx=nested_base_a_idx,
                        companion_volumes=companion_volumes,
                        accumulated_offset=compound_offset,
                        parent_speed=effective_speed,
                    )
                else:
                    expanded_clip = deepcopy(child_clip)
                    # Compress the child's local position and duration by
                    # effective_speed before placing it on the outer
                    # timeline: a compound played at 2x speed should have
                    # its 4s of inner content occupy 2s of outer timeline,
                    # not keep its original spacing with only the leaf
                    # clip's own `speed` field bumped (which affects
                    # playback rate but not how much outer timeline the
                    # clip occupies).
                    expanded_clip.timeline_start = (
                        expanded_clip.timeline_start / effective_speed
                    ) + compound_offset
                    expanded_clip.duration = expanded_clip.duration / effective_speed
                    expanded_clip.speed = expanded_clip.speed * effective_speed

                    if isinstance(expanded_clip, CodedVisualClip):
                        expanded_clip = self._coded_visual_to_media(expanded_clip)

                    target_timeline.video_tracks[dest_v_idx].add_clip(expanded_clip)

        # Expand inner audio tracks
        for inner_a_idx, inner_a_track in enumerate(compound.inner_timeline.audio_tracks):
            dest_a_idx = base_a_track_idx + inner_a_idx
            while len(target_timeline.audio_tracks) <= dest_a_idx:
                target_timeline.add_audio_track()

            for child_clip in inner_a_track.clips:
                if isinstance(child_clip, AudioClip):
                    expanded_audio = deepcopy(child_clip)
                    # Same speed-compression as video children: see comment
                    # above in the video-track expansion loop.
                    expanded_audio.timeline_start = (
                        expanded_audio.timeline_start / effective_speed
                    ) + compound_offset
                    expanded_audio.duration = expanded_audio.duration / effective_speed
                    expanded_audio.speed = expanded_audio.speed * effective_speed
                    expanded_audio.audio_properties.volume = (
                        expanded_audio.audio_properties.volume * audio_volume_mult
                    )
                    target_timeline.audio_tracks[dest_a_idx].add_clip(expanded_audio)

    @staticmethod
    def _companion_audio_track_index(timeline: Timeline, compound_clip_id: str, default: int) -> int:
        """Find which audio track a compound clip's CompoundAudioClip companion lives on
        within `timeline`, falling back to `default` if it has no companion there
        (e.g. it was added to an inner timeline directly rather than through
        Timeline.add_clip's auto-companion routing).
        """
        for track_idx, track in enumerate(timeline.audio_tracks):
            for clip in track.clips:
                if isinstance(clip, CompoundAudioClip) and clip.compound_clip_id == compound_clip_id:
                    return track_idx
        return default

    @staticmethod
    def _coded_visual_to_media(clip: CodedVisualClip) -> MediaClip:
        """Converts a compiled CodedVisualClip into a concrete MediaClip."""
        if not clip.media_source:
            raise ValueError(
                f"CodedVisualClip '{clip.id}' has no media_source. Must be compiled before flattening."
            )
        return MediaClip(
            id=f"media_{clip.id}",
            timeline_start=clip.timeline_start,
            duration=clip.duration,
            speed=clip.speed,
            source=Source(source=clip.media_source, start=clip.source.start),
            fps=clip.fps,
            resolution=(int(clip.canvas_size.width), int(clip.canvas_size.height)),
            transform=clip.transform,
            source_audio=clip.source_audio,
        )
