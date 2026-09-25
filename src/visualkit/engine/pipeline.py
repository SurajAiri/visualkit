"""Timeline processing: variable resolution, coded-visual compilation, flattening.

The pipeline never mutates the timeline it is given. `process()` deep-copies
the input first, so exporting a timeline (which flattens it) leaves the
user's templates exactly as they authored them -- in particular an exposed
parameter's *default* is applied to the working copy only, not baked into
the original.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from typing import Any

from visualkit.coded_visual.compiler import CodedVisualCompiler
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.coded_visual import CodedVisualClip, CompileStatus
from visualkit.models.clips.compound import CompoundAudioClip, CompoundClip
from visualkit.models.clips.media import MediaClip
from visualkit.models.clips.text import TextClip
from visualkit.models.clips.visual import Transform, VisualClip
from visualkit.models.timeline import Timeline
from visualkit.utils.exceptions import TimelineValidationError
from visualkit.utils.time import Time

_MAX_COMPOUND_DEPTH = 32


def _frac(value: float) -> Fraction:
    return Fraction(value).limit_denominator(1_000_000)


def compose_transforms(outer: Transform, inner: Transform) -> Transform:
    """Compose a compound clip's `outer` transform with a child's `inner` transform.

    Approximates what nesting means for a flattened timeline: scales
    multiply, zooms multiply, opacities multiply (as fractions), rotations
    add, and the child's offset is scaled and rotated by the parent before
    the parent's own offset is added. An explicit child `size` is kept
    (scaled by the parent's scale).
    """
    import math

    theta = math.radians(outer.rotation)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    ix, iy = inner.position.x * outer.scale, inner.position.y * outer.scale
    rx, ry = ix * cos_t - iy * sin_t, ix * sin_t + iy * cos_t

    size = inner.size.model_copy()
    if size.width > 0 and size.height > 0:
        size = size.model_copy(
            update={"width": size.width * outer.scale, "height": size.height * outer.scale}
        )
    return Transform(
        position={"x": outer.position.x + rx, "y": outer.position.y + ry},
        size=size.model_dump(),
        rotation=max(-3600.0, min(3600.0, outer.rotation + inner.rotation)),
        scale=max(1e-6, min(100.0, outer.scale * inner.scale)),
        zoom=max(1e-6, min(100.0, outer.zoom * inner.zoom)),
        opacity=round(outer.opacity * inner.opacity / 100),
    )


class TimelinePipeline:
    """Processing and transformation pipeline for Timelines."""

    def __init__(self, compiler: CodedVisualCompiler | None = None):
        self._compiler = compiler

    @property
    def compiler(self) -> CodedVisualCompiler:
        """Created lazily so merely importing/constructing a pipeline never touches the filesystem."""
        if self._compiler is None:
            self._compiler = CodedVisualCompiler()
        return self._compiler

    # ------------------------------------------------------------------ validation
    def validate(self, timeline: Timeline) -> None:
        """Raise `TimelineValidationError` for structural problems that would corrupt a flatten.

        Currently: a CompoundClip that (directly or indirectly) contains itself.
        """
        self._check_cycles(timeline, active=())

    def _check_cycles(self, timeline: Timeline, active: tuple[int, ...]) -> None:
        for track in timeline.video_tracks:
            for clip in track.clips:
                if isinstance(clip, CompoundClip) and clip.inner_timeline is not None:
                    key = id(clip.inner_timeline)
                    if key in active or len(active) >= _MAX_COMPOUND_DEPTH:
                        raise TimelineValidationError(
                            f"CompoundClip '{clip.id}' contains itself (or is nested deeper than "
                            f"{_MAX_COMPOUND_DEPTH} levels); a compound clip cannot be its own descendant."
                        )
                    self._check_cycles(clip.inner_timeline, (*active, key))

    # ------------------------------------------------------------------ stages
    def resolve_variables(self, timeline: Timeline) -> Timeline:
        """Recursively apply parameters down through all compound clips (mutates `timeline`)."""
        for track in timeline.video_tracks:
            for clip in track.clips:
                if isinstance(clip, CompoundClip):
                    clip.apply_parameters(strict=True)
                    if clip.inner_timeline:
                        self.resolve_variables(clip.inner_timeline)
        return timeline

    def compile_coded_visuals(
        self,
        timeline: Timeline,
        force: bool = False,
        render_video: bool | None = None,
        alpha: bool = True,
    ) -> Timeline:
        """Compile every CodedVisualClip in `timeline`, including inside compounds (mutates `timeline`).

        `render_video`: ``None`` lets each clip's ``render_mode`` decide (a still
        visual becomes a PNG, an animated one a video); ``True``/``False`` force it.
        `alpha`: animated visuals keep transparency (lossless FFV1 ``.mkv``); ``False`` writes
        the flat H.264 ``.mp4`` instead.
        """
        for track in timeline.video_tracks:
            for clip in track.clips:
                if isinstance(clip, CodedVisualClip):
                    if force or clip.compile_status != CompileStatus.READY or not clip.media_source:
                        self.compiler.compile(clip, force=force, render_video=render_video, alpha=alpha)
                elif isinstance(clip, CompoundClip) and clip.inner_timeline:
                    self.compile_coded_visuals(
                        clip.inner_timeline, force=force, render_video=render_video, alpha=alpha
                    )
        return timeline

    def process(
        self,
        timeline: Timeline,
        force_compile: bool = False,
        render_video: bool | None = None,
        alpha: bool = True,
    ) -> Timeline:
        """Resolve variables -> compile coded visuals -> flatten, **without mutating `timeline`**."""
        self.validate(timeline)
        working = timeline.model_copy(deep=True)
        self.resolve_variables(working)
        self.compile_coded_visuals(working, force=force_compile, render_video=render_video, alpha=alpha)
        return self.flatten(working)

    # ------------------------------------------------------------------ flatten
    def flatten(self, timeline: Timeline) -> Timeline:
        """Expand all CompoundClips and resolve CodedVisualClips into a concrete Timeline.

        The result contains only `MediaClip`, `TextClip` and `AudioClip`, with
        absolute timeline coordinates and composited transforms/volume.
        Coded visuals must already be compiled (see `process`).
        """
        self.validate(timeline)
        flattened = Timeline()

        companion_volumes: dict[str, float] = {}
        companion_track_idx: dict[str, int] = {}
        for track_idx, track in enumerate(timeline.audio_tracks):
            for clip in track.clips:
                if isinstance(clip, CompoundAudioClip):
                    companion_volumes[clip.compound_clip_id] = 0.0 if clip.mute else clip.volume
                    companion_track_idx[clip.compound_clip_id] = track_idx

        # Give each CompoundClip a destination block of video tracks that cannot collide
        # with any other outer track's content (see _compound_video_track_span).
        next_free_v_track = len(timeline.video_tracks)
        compound_v_track_base: dict[str, int] = {}
        for track_idx, v_track in enumerate(timeline.video_tracks):
            for clip in v_track.clips:
                if not isinstance(clip, CompoundClip):
                    continue
                span = self._compound_video_track_span(clip)
                span_range = range(track_idx, track_idx + span)
                overlaps_other_content = (
                    any(
                        i != track_idx
                        and i < len(timeline.video_tracks)
                        and len(timeline.video_tracks[i].clips) > 0
                        for i in span_range
                    )
                    or len(v_track.clips) > 1
                )
                if overlaps_other_content:
                    compound_v_track_base[clip.id] = next_free_v_track
                    next_free_v_track += span
                else:
                    compound_v_track_base[clip.id] = track_idx

        for track_idx, v_track in enumerate(timeline.video_tracks):
            while len(flattened.video_tracks) <= track_idx:
                flattened.add_video_track()

            for clip in v_track.clips:
                if isinstance(clip, CompoundClip):
                    self._flatten_compound_clip(
                        compound=clip,
                        target_timeline=flattened,
                        base_v_track_idx=compound_v_track_base[clip.id],
                        base_a_track_idx=companion_track_idx.get(clip.id, track_idx),
                        companion_volumes=companion_volumes,
                    )
                elif isinstance(clip, CodedVisualClip):
                    flattened.video_tracks[track_idx].add_clip(clip.to_media_clip())
                else:
                    flattened.video_tracks[track_idx].add_clip(deepcopy(clip))

        for track_idx, a_track in enumerate(timeline.audio_tracks):
            while len(flattened.audio_tracks) <= track_idx:
                flattened.add_audio_track()
            for clip in a_track.clips:
                if isinstance(clip, AudioClip):  # CompoundAudioClips were absorbed with their compound
                    flattened.audio_tracks[track_idx].add_clip(deepcopy(clip))

        return flattened

    @classmethod
    def _compound_video_track_span(cls, compound: CompoundClip) -> int:
        """How many destination video tracks `compound` (and its nested compounds) needs."""
        if not compound.inner_timeline:
            return 1
        span = len(compound.inner_timeline.video_tracks) or 1
        for v_track in compound.inner_timeline.video_tracks:
            for child in v_track.clips:
                if isinstance(child, CompoundClip):
                    span += cls._compound_video_track_span(child) - 1
        return span

    def _flatten_compound_clip(
        self,
        compound: CompoundClip,
        target_timeline: Timeline,
        base_v_track_idx: int,
        base_a_track_idx: int,
        companion_volumes: dict[str, float],
        accumulated_offset: Time | None = None,
        parent_speed: float = 1.0,
        parent_transform: Transform | None = None,
        parent_end: Time | None = None,
    ) -> None:
        """Recursively expand `compound` onto `target_timeline`.

        * Inner clip times are divided by the accumulated speed (a 2x compound's
          4s of content occupies 2s outside).
        * Inner content is **clipped to the compound's own duration**: a 10s
          inner clip inside a 4s compound contributes only its first 4s.
        * The compound's own `transform` is composed onto every child.
        """
        if not compound.inner_timeline:
            return

        current_offset = accumulated_offset if accumulated_offset is not None else Time.zero()
        compound_offset = current_offset + (compound.timeline_start / parent_speed)
        effective_speed = parent_speed * compound.speed
        audio_volume_mult = companion_volumes.get(compound.id, 1.0)

        # Absolute end (on the root timeline) beyond which this compound's content is cut.
        own_end = compound_offset + (compound.duration / effective_speed)
        clip_end = own_end if parent_end is None else (own_end if own_end < parent_end else parent_end)

        comp_transform = (
            compose_transforms(parent_transform, compound.transform)
            if parent_transform
            else compound.transform
        )

        for inner_v_idx, inner_v_track in enumerate(compound.inner_timeline.video_tracks):
            dest_v_idx = base_v_track_idx + inner_v_idx
            while len(target_timeline.video_tracks) <= dest_v_idx:
                target_timeline.add_video_track()

            for child_clip in inner_v_track.clips:
                if isinstance(child_clip, CompoundClip):
                    self._flatten_compound_clip(
                        compound=child_clip,
                        target_timeline=target_timeline,
                        base_v_track_idx=dest_v_idx,
                        base_a_track_idx=self._companion_audio_track_index(
                            compound.inner_timeline, child_clip.id, default=base_a_track_idx
                        ),
                        companion_volumes=companion_volumes,
                        accumulated_offset=compound_offset,
                        parent_speed=effective_speed,
                        parent_transform=comp_transform,
                        parent_end=clip_end,
                    )
                    continue

                expanded = (
                    child_clip.to_media_clip()
                    if isinstance(child_clip, CodedVisualClip)
                    else deepcopy(child_clip)
                )
                if not self._place_child(expanded, compound_offset, effective_speed, clip_end):
                    continue
                if not comp_transform.is_identity and hasattr(expanded, "transform"):
                    if isinstance(expanded, VisualClip) and (expanded.keyframes or expanded.animation):
                        # Composing an animated child with a parent transform would mean composing
                        # two curves per property; keyed values also ignore the static transform the
                        # parent's offset/scale/rotation would be folded into. Refuse rather than
                        # render the animation silently wrong. `animation` (fade/slide/pop/wipe)
                        # compiles to the same kind of curve, so it shares the same refusal.
                        raise NotImplementedError(
                            f"Clip '{expanded.id}' has keyframes and sits inside CompoundClip "
                            f"'{compound.id}', whose transform is not the identity. Animated clips "
                            "inside a transformed compound are not supported yet: leave the compound's "
                            "transform at its defaults (animate the inner clips instead), or move the "
                            "animated clip out of the compound."
                        )
                    expanded.transform = compose_transforms(comp_transform, expanded.transform)
                target_timeline.video_tracks[dest_v_idx].add_clip(expanded)

        for inner_a_idx, inner_a_track in enumerate(compound.inner_timeline.audio_tracks):
            dest_a_idx = base_a_track_idx + inner_a_idx
            while len(target_timeline.audio_tracks) <= dest_a_idx:
                target_timeline.add_audio_track()

            for child_clip in inner_a_track.clips:
                if not isinstance(child_clip, AudioClip):
                    continue
                expanded_audio = deepcopy(child_clip)
                if not self._place_child(expanded_audio, compound_offset, effective_speed, clip_end):
                    continue
                expanded_audio.audio_properties.volume = min(
                    1.0, expanded_audio.audio_properties.volume * audio_volume_mult
                )
                target_timeline.audio_tracks[dest_a_idx].add_clip(expanded_audio)

    @staticmethod
    def _place_child(clip: Any, compound_offset: Time, effective_speed: float, clip_end: Time) -> bool:
        """Retime `clip` onto the outer timeline and trim it to `clip_end`.

        Returns False if the clip falls entirely outside the compound's span (dropped).
        """
        speed = _frac(effective_speed)
        start = compound_offset + (clip.timeline_start / effective_speed)
        duration = clip.duration / effective_speed
        end = start + duration

        if start >= clip_end:
            return False
        if end > clip_end:
            duration = Time(clip_end.value - start.value)
        clip.timeline_start = start
        if isinstance(clip, VisualClip):
            # Keyframe times live on the inner timeline, which the compound plays at
            # `effective_speed` -- so they scale with the clip's duration (the clip's own `speed`
            # is not involved), and anything now past the trimmed end is cut.
            retimed = (
                {
                    name: curve.time_scaled(1 / speed).head(duration.value)
                    for name, curve in clip.keyframes.items()
                }
                if clip.keyframes
                else None
            )
            clip.set_duration_and_keyframes(duration, retimed)
        else:
            clip.duration = duration
        clip.speed = float(_frac(clip.speed) * speed)
        return True

    @staticmethod
    def _companion_audio_track_index(timeline: Timeline, compound_clip_id: str, default: int) -> int:
        """Audio track holding `compound_clip_id`'s CompoundAudioClip companion within `timeline`."""
        for track_idx, track in enumerate(timeline.audio_tracks):
            for clip in track.clips:
                if isinstance(clip, CompoundAudioClip) and clip.compound_clip_id == compound_clip_id:
                    return track_idx
        return default

    @staticmethod
    def _coded_visual_to_media(clip: CodedVisualClip) -> MediaClip:
        """Backwards-compatible alias for `CodedVisualClip.to_media_clip`."""
        return clip.to_media_clip()
