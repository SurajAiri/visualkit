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

        # 1. Map audio companion volume multipliers if present
        companion_volumes: dict[str, float] = {}
        for track in timeline.audio_tracks:
            for clip in track.clips:
                if isinstance(clip, CompoundAudioClip):
                    companion_volumes[clip.compound_clip_id] = 0.0 if clip.mute else clip.volume

        # 2. Process Video Tracks
        for track_idx, v_track in enumerate(timeline.video_tracks):
            while len(flattened.video_tracks) <= track_idx:
                flattened.add_video_track()

            for clip in v_track.clips:
                if isinstance(clip, CompoundClip):
                    self._flatten_compound_clip(
                        compound=clip,
                        target_timeline=flattened,
                        base_v_track_idx=track_idx,
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
        companion_volumes: dict[str, float],
        accumulated_offset: Any = None,
        parent_speed: float = 1.0,
    ) -> None:
        """Recursively expands a CompoundClip onto target_timeline."""
        if not compound.inner_timeline:
            return

        from visualkit.utils.time import Time

        current_offset = accumulated_offset if accumulated_offset is not None else Time.zero()
        compound_offset = current_offset + compound.timeline_start
        effective_speed = parent_speed * compound.speed
        audio_volume_mult = companion_volumes.get(compound.id, 1.0)

        # Expand inner video tracks
        for inner_v_idx, inner_v_track in enumerate(compound.inner_timeline.video_tracks):
            dest_v_idx = base_v_track_idx + inner_v_idx
            while len(target_timeline.video_tracks) <= dest_v_idx:
                target_timeline.add_video_track()

            for child_clip in inner_v_track.clips:
                if isinstance(child_clip, CompoundClip):
                    # Nested compound clip
                    self._flatten_compound_clip(
                        compound=child_clip,
                        target_timeline=target_timeline,
                        base_v_track_idx=dest_v_idx,
                        companion_volumes=companion_volumes,
                        accumulated_offset=compound_offset,
                        parent_speed=effective_speed,
                    )
                else:
                    expanded_clip = deepcopy(child_clip)
                    # Shift absolute timeline start and adjust speed
                    expanded_clip.timeline_start = expanded_clip.timeline_start + compound_offset
                    expanded_clip.speed = expanded_clip.speed * effective_speed

                    if isinstance(expanded_clip, CodedVisualClip):
                        expanded_clip = self._coded_visual_to_media(expanded_clip)

                    target_timeline.video_tracks[dest_v_idx].add_clip(expanded_clip)

        # Expand inner audio tracks
        for inner_a_idx, inner_a_track in enumerate(compound.inner_timeline.audio_tracks):
            dest_a_idx = inner_a_idx
            while len(target_timeline.audio_tracks) <= dest_a_idx:
                target_timeline.add_audio_track()

            for child_clip in inner_a_track.clips:
                if isinstance(child_clip, AudioClip):
                    expanded_audio = deepcopy(child_clip)
                    expanded_audio.timeline_start = expanded_audio.timeline_start + compound_offset
                    expanded_audio.speed = expanded_audio.speed * effective_speed
                    expanded_audio.audio_properties.volume = (
                        expanded_audio.audio_properties.volume * audio_volume_mult
                    )
                    target_timeline.audio_tracks[dest_a_idx].add_clip(expanded_audio)

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
        )
