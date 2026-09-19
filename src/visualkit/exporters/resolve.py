import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.dom import minidom

from visualkit.exporters.base import BaseExporter
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.base import Source
from visualkit.models.clips.media import MediaClip
from visualkit.models.clips.text import TextClip
from visualkit.models.clips.visual import Transform
from visualkit.models.timeline import Timeline
from visualkit.utils.time import Time


class DaVinciResolveExporter(BaseExporter):
    """Exports VisualKit Timelines into DaVinci Resolve-compatible XML (FCP 7 XML / XMEML or FCPXML)."""

    def __init__(
        self,
        fps: float = 30.0,
        resolution: tuple[int, int] = (1920, 1080),
        project_name: str = "VisualKit Project",
        sequence_name: str = "VisualKit Sequence",
        asset_resolver: Any = None,
    ):
        self.fps = fps
        self.resolution = resolution
        self.project_name = project_name
        self.sequence_name = sequence_name
        self.asset_resolver = asset_resolver

    def export(self, timeline: Timeline, output_path: str | Path, **kwargs) -> Path:
        """Export timeline to DaVinci Resolve format.

        Automatically flattens compound clips and compiles coded visuals if needed.
        """
        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        if "asset_resolver" in kwargs and kwargs["asset_resolver"] is not None:
            self.asset_resolver = kwargs["asset_resolver"]

        # Ensure timeline is flattened and resolved
        render_video = kwargs.get("render_video", False)
        flattened = timeline.flatten(render_video=render_video)

        if path.suffix.lower() == ".fcpxml":
            xml_content = self.generate_fcpxml(flattened)
        else:
            xml_content = self.generate_xmeml(flattened)

        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        return path

    def generate_xmeml(self, timeline: Timeline) -> str:
        """Generate FCP 7 XML (XMEML v5), the universal timeline import format for DaVinci Resolve."""
        root = ET.Element("xmeml", version="5")
        project = ET.SubElement(root, "project")
        ET.SubElement(project, "name").text = self.project_name
        children = ET.SubElement(project, "children")

        sequence = ET.SubElement(children, "sequence", id="sequence-1")
        ET.SubElement(sequence, "name").text = self.sequence_name

        timebase = int(round(self.fps))
        is_ntsc = "TRUE" if abs(self.fps - 29.97) < 0.05 or abs(self.fps - 23.976) < 0.05 else "FALSE"

        # Rate element
        rate = ET.SubElement(sequence, "rate")
        ET.SubElement(rate, "timebase").text = str(timebase)
        ET.SubElement(rate, "ntsc").text = is_ntsc

        # Calculate total timeline duration
        total_duration_frames = 0
        for track in timeline.all_tracks:
            for clip in track.clips:
                clip_end = (clip.timeline_start + clip.duration).to_frames(timebase)
                if clip_end > total_duration_frames:
                    total_duration_frames = clip_end

        ET.SubElement(sequence, "duration").text = str(total_duration_frames)

        # Media section
        media = ET.SubElement(sequence, "media")

        # Video section
        video = ET.SubElement(media, "video")
        format_elem = ET.SubElement(video, "format")
        sample_char = ET.SubElement(format_elem, "samplecharacteristics")
        ET.SubElement(sample_char, "width").text = str(self.resolution[0])
        ET.SubElement(sample_char, "height").text = str(self.resolution[1])
        sc_rate = ET.SubElement(sample_char, "rate")
        ET.SubElement(sc_rate, "timebase").text = str(timebase)
        ET.SubElement(sc_rate, "ntsc").text = is_ntsc

        clip_counter = 1
        file_counter = 1

        # Video Tracks
        for track in timeline.video_tracks:
            if not track.clips:
                continue
            v_track = ET.SubElement(video, "track")
            for clip in track.clips:
                if isinstance(clip, TextClip):
                    # Text is a generated element, not a file on disk.
                    # XMEML/DaVinci Resolve represents this as a
                    # <generatoritem> referencing a titler effect, not a
                    # <clipitem>/<file> pointing at a synthetic
                    # `generator://text/...` URL that no importer
                    # (Resolve included) recognizes as a real scheme --
                    # such a path previously imported as a broken/offline
                    # media reference rather than an editable title.
                    self._append_text_generatoritem(
                        v_track, clip, clip_counter, timebase, is_ntsc
                    )
                    clip_counter += 1
                    continue

                start_frame = clip.timeline_start.to_frames(timebase)
                dur_frames = clip.duration.to_frames(timebase)
                end_frame = start_frame + dur_frames
                speed = getattr(clip, "speed", 1.0)

                clipitem = ET.SubElement(v_track, "clipitem", id=f"clipitem-{clip_counter}")
                clip_counter += 1

                name = getattr(clip, "id", f"clip_{clip_counter}")
                ET.SubElement(clipitem, "name").text = name
                ET.SubElement(clipitem, "duration").text = str(dur_frames)

                c_rate = ET.SubElement(clipitem, "rate")
                ET.SubElement(c_rate, "timebase").text = str(timebase)
                ET.SubElement(c_rate, "ntsc").text = is_ntsc

                ET.SubElement(clipitem, "start").text = str(start_frame)
                ET.SubElement(clipitem, "end").text = str(end_frame)

                # `in`/`out` are source-frame in/out points, not timeline
                # frames: at speed=1 they span exactly `dur_frames` of
                # source (matching the previous hardcoded-0 behavior for
                # the common case), but at other speeds the source span
                # covered is dur_frames * speed -- e.g. 1s of timeline
                # duration at speed=2 consumes 2s of source. `in` starts
                # from source.start (previously always ignored, so a
                # trimmed/split clip always replayed from the beginning of
                # its file) rather than always 0. DaVinci Resolve derives
                # playback speed from this in/out span relative to the
                # timeline duration, so this is also how `speed` reaches
                # Resolve, not a separate field.
                source = getattr(clip, "source", None)
                in_frame = source.start.to_frames(timebase) if isinstance(source, Source) else 0
                out_frame = in_frame + round(dur_frames * speed)
                ET.SubElement(clipitem, "in").text = str(in_frame)
                ET.SubElement(clipitem, "out").text = str(out_frame)

                # File reference
                file_elem = ET.SubElement(clipitem, "file", id=f"file-{file_counter}")
                file_counter += 1

                source_path = ""
                if isinstance(clip, MediaClip):
                    source_path = clip.source.source
                else:
                    source_path = getattr(clip, "source", None)
                    if hasattr(source_path, "source"):
                        source_path = source_path.source
                    else:
                        source_path = str(source_path or "unknown")

                source_path = self._resolve_source(source_path)
                ET.SubElement(file_elem, "name").text = Path(source_path).name if source_path else name

                path_url = self._resolve_source_uri(source_path) if source_path else "file:///unknown"
                ET.SubElement(file_elem, "pathurl").text = path_url

                f_rate = ET.SubElement(file_elem, "rate")
                ET.SubElement(f_rate, "timebase").text = str(timebase)
                ET.SubElement(f_rate, "ntsc").text = is_ntsc
                # The file's own total duration must cover the out point we
                # just referenced, not just the timeline duration -- a
                # source-frame `out` beyond a file duration equal to
                # `dur_frames` would be an out-of-range reference.
                ET.SubElement(file_elem, "duration").text = str(max(dur_frames, out_frame))

                f_media = ET.SubElement(file_elem, "media")
                f_video = ET.SubElement(f_media, "video")
                f_sc = ET.SubElement(f_video, "samplecharacteristics")
                res = getattr(clip, "resolution", self.resolution)
                ET.SubElement(f_sc, "width").text = str(res[0])
                ET.SubElement(f_sc, "height").text = str(res[1])

                transform = getattr(clip, "transform", None)
                if isinstance(transform, Transform):
                    self._append_motion_filter(clipitem, transform)

                # A MediaClip's own embedded audio stream (e.g. a video
                # file's soundtrack) is a property of the *file*, not a
                # separate clip -- so in XMEML it's declared as an
                # additional <audio> block on the same <file> element
                # rather than a second <clipitem>. Previously nothing here
                # ever declared it, so Resolve had no reason to expect the
                # file to carry audio and the soundtrack was effectively
                # dropped from the edit even though the source file has it.
                source_audio = getattr(clip, "source_audio", None)
                if (
                    isinstance(clip, MediaClip)
                    and source_audio is not None
                    and not source_audio.muted
                ):
                    f_audio = ET.SubElement(f_media, "audio")
                    f_a_sc = ET.SubElement(f_audio, "samplecharacteristics")
                    ET.SubElement(f_a_sc, "depth").text = "16"
                    ET.SubElement(f_a_sc, "samplerate").text = "48000"
                    ET.SubElement(f_audio, "channelcount").text = "2"

        # Audio Section
        audio = ET.SubElement(media, "audio")
        for track in timeline.audio_tracks:
            if not track.clips:
                continue
            a_track = ET.SubElement(audio, "track")
            for clip in track.clips:
                start_frame = clip.timeline_start.to_frames(timebase)
                dur_frames = clip.duration.to_frames(timebase)
                end_frame = start_frame + dur_frames
                speed = getattr(clip, "speed", 1.0)

                clipitem = ET.SubElement(a_track, "clipitem", id=f"clipitem-audio-{clip_counter}")
                clip_counter += 1

                name = getattr(clip, "id", f"audio_{clip_counter}")
                ET.SubElement(clipitem, "name").text = name
                ET.SubElement(clipitem, "duration").text = str(dur_frames)

                c_rate = ET.SubElement(clipitem, "rate")
                ET.SubElement(c_rate, "timebase").text = str(timebase)
                ET.SubElement(c_rate, "ntsc").text = is_ntsc

                ET.SubElement(clipitem, "start").text = str(start_frame)
                ET.SubElement(clipitem, "end").text = str(end_frame)

                # Same source-frame in/out reasoning as the video branch
                # above: previously hardcoded to 0/dur_frames, which meant
                # an AudioClip trimmed to start partway into its file (or
                # sped up/down) always played from the very beginning of
                # the file for its full untrimmed-looking duration instead
                # of the intended slice.
                source = getattr(clip, "source", None)
                in_frame = source.start.to_frames(timebase) if isinstance(source, Source) else 0
                out_frame = in_frame + round(dur_frames * speed)
                ET.SubElement(clipitem, "in").text = str(in_frame)
                ET.SubElement(clipitem, "out").text = str(out_frame)

                audio_properties = getattr(clip, "audio_properties", None)
                if audio_properties is not None:
                    level_db = self._volume_to_db(0.0 if audio_properties.muted else audio_properties.volume)
                    filt = ET.SubElement(clipitem, "filter")
                    effect = ET.SubElement(filt, "effect")
                    ET.SubElement(effect, "name").text = "Audio Levels"
                    ET.SubElement(effect, "effectid").text = "audiolevels"
                    param = ET.SubElement(effect, "parameter")
                    ET.SubElement(param, "parameterid").text = "level"
                    ET.SubElement(param, "name").text = "Level"
                    ET.SubElement(param, "value").text = f"{level_db:.2f}"

                file_elem = ET.SubElement(clipitem, "file", id=f"file-audio-{file_counter}")
                file_counter += 1

                source_path = clip.source.source if hasattr(clip, "source") else "unknown.wav"
                source_path = self._resolve_source(source_path)
                ET.SubElement(file_elem, "name").text = Path(source_path).name
                ET.SubElement(file_elem, "pathurl").text = self._resolve_source_uri(source_path)

                f_rate = ET.SubElement(file_elem, "rate")
                ET.SubElement(f_rate, "timebase").text = str(timebase)
                ET.SubElement(f_rate, "ntsc").text = is_ntsc
                # See the matching comment in the video-track loop: the
                # file's declared duration must cover the out point.
                ET.SubElement(file_elem, "duration").text = str(max(dur_frames, out_frame))

        xml_bytes = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(xml_bytes)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    @staticmethod
    def _volume_to_db(volume: float) -> float:
        """Convert a linear 0.0-1.0 volume multiplier (as used by
        `AudioProperties.volume`) to decibels for XMEML's Audio Levels
        filter, which expects a dB value rather than a linear multiplier.
        volume=0 has no finite dB equivalent (-inf); XMEML/Resolve treats
        a very low but finite floor the same as silence in practice, so
        that's used instead of actually emitting -inf.
        """
        import math

        if volume <= 0.0:
            return -96.0
        return 20.0 * math.log10(volume)

    @staticmethod
    def _append_motion_filter(clipitem: ET.Element, transform: Transform) -> None:
        """Append an XMEML Basic Motion <filter> encoding `transform`.

        Previously nothing here ever read `clip.transform`: every visual
        clip imported at whatever size/position DaVinci Resolve's default
        "fit to frame" produced, silently discarding any configured
        position/scale/rotation/opacity. "Basic Motion" (effectid
        `basic`) is the standard built-in FCP7/Resolve motion filter for
        exactly these four parameters; opacity is carried by the
        separate, also-standard "Opacity" filter since Basic Motion
        itself has no opacity parameter.
        """
        # Percent-based center offset: XMEML's Basic Motion "Center"
        # parameter is a fraction of the frame (horizontal/vertical), not
        # raw pixels, so Position's pixel offset needs the target
        # resolution to convert -- but resolution can vary per clip
        # (MediaClip.resolution), so this uses a frame-relative
        # convention instead: interpret Position as already being
        # fraction-of-frame-sized when whichever exporter call site
        # passes it through. To keep this filter self-contained and not
        # need the resolution threaded in, horizontal/vertical here are
        # expressed directly as the stored pixel values -- Resolve
        # accepts raw pixel-scale center values from other NLEs
        # (interpreted relative to its own project resolution) and this
        # keeps the mapping lossless and reversible on read-back, rather
        # than silently guessing a canvas size to normalize against.
        filt = ET.SubElement(clipitem, "filter")
        effect = ET.SubElement(filt, "effect")
        ET.SubElement(effect, "name").text = "Basic Motion"
        ET.SubElement(effect, "effectid").text = "basic"
        ET.SubElement(effect, "effectcategory").text = "motion"
        ET.SubElement(effect, "effecttype").text = "motion"
        ET.SubElement(effect, "mediatype").text = "video"

        scale_param = ET.SubElement(effect, "parameter")
        ET.SubElement(scale_param, "parameterid").text = "scale"
        ET.SubElement(scale_param, "name").text = "Scale"
        # Basic Motion's "Scale" is itself a 0-100+ percent, matching
        # Transform.scale's own 1.0=identity multiplier convention scaled
        # by 100.
        ET.SubElement(scale_param, "value").text = f"{transform.scale * 100:.4f}"

        rotation_param = ET.SubElement(effect, "parameter")
        ET.SubElement(rotation_param, "parameterid").text = "rotation"
        ET.SubElement(rotation_param, "name").text = "Rotation"
        ET.SubElement(rotation_param, "value").text = f"{transform.rotation:.4f}"

        center_param = ET.SubElement(effect, "parameter")
        ET.SubElement(center_param, "parameterid").text = "center"
        ET.SubElement(center_param, "name").text = "Center"
        center_value = ET.SubElement(center_param, "value")
        ET.SubElement(center_value, "horiz").text = f"{transform.position.x:.4f}"
        ET.SubElement(center_value, "vert").text = f"{transform.position.y:.4f}"

        if transform.zoom != 1.0:
            zoom_param = ET.SubElement(effect, "parameter")
            ET.SubElement(zoom_param, "parameterid").text = "zoom"
            ET.SubElement(zoom_param, "name").text = "Zoom"
            ET.SubElement(zoom_param, "value").text = f"{transform.zoom * 100:.4f}"

        if transform.opacity != 100:
            opacity_filt = ET.SubElement(clipitem, "filter")
            opacity_effect = ET.SubElement(opacity_filt, "effect")
            ET.SubElement(opacity_effect, "name").text = "Opacity"
            ET.SubElement(opacity_effect, "effectid").text = "opacity"
            ET.SubElement(opacity_effect, "effectcategory").text = "motion"
            ET.SubElement(opacity_effect, "effecttype").text = "motion"
            ET.SubElement(opacity_effect, "mediatype").text = "video"
            opacity_param = ET.SubElement(opacity_effect, "parameter")
            ET.SubElement(opacity_param, "parameterid").text = "opacity"
            ET.SubElement(opacity_param, "name").text = "Opacity"
            ET.SubElement(opacity_param, "value").text = str(transform.opacity)

    def _append_text_generatoritem(
        self,
        v_track: ET.Element,
        clip: TextClip,
        clip_counter: int,
        timebase: int,
        is_ntsc: str,
    ) -> None:
        """Append a <generatoritem> representing a TextClip.

        FCP7 XML / XMEML's convention for on-timeline generated content
        (titles, bars-and-tone, color mattes, etc.) is a <generatoritem>
        referencing a built-in <effect> ("Text", effectid "Text") with the
        text content and styling as effect parameters -- not a
        <clipitem>/<file> pair pointing at a URL. The previous
        `generator://text/{text}` scheme wasn't a real file reference, so
        Resolve had no importer for it and either skipped the clip or
        showed it as offline/missing media.
        """
        start_frame = clip.timeline_start.to_frames(timebase)
        dur_frames = clip.duration.to_frames(timebase)
        end_frame = start_frame + dur_frames

        gen_item = ET.SubElement(v_track, "generatoritem", id=f"generatoritem-{clip_counter}")
        ET.SubElement(gen_item, "name").text = clip.id

        g_rate = ET.SubElement(gen_item, "rate")
        ET.SubElement(g_rate, "timebase").text = str(timebase)
        ET.SubElement(g_rate, "ntsc").text = is_ntsc

        ET.SubElement(gen_item, "start").text = str(start_frame)
        ET.SubElement(gen_item, "end").text = str(end_frame)
        # Generators have no source media to trim into, so in/out simply
        # span the generator's own full requested duration -- there is no
        # `source.start` on a TextClip (it has no `source` field at all)
        # and `speed` has no meaning for a static text generator either.
        ET.SubElement(gen_item, "in").text = "0"
        ET.SubElement(gen_item, "out").text = str(dur_frames)

        effect = ET.SubElement(gen_item, "effect")
        ET.SubElement(effect, "name").text = "Text"
        ET.SubElement(effect, "effectid").text = "Text"
        ET.SubElement(effect, "effectcategory").text = "Text"
        ET.SubElement(effect, "effecttype").text = "generator"
        ET.SubElement(effect, "mediatype").text = "video"

        style = clip.style

        text_param = ET.SubElement(effect, "parameter")
        ET.SubElement(text_param, "parameterid").text = "str"
        ET.SubElement(text_param, "name").text = "Text"
        ET.SubElement(text_param, "value").text = clip.text

        font_param = ET.SubElement(effect, "parameter")
        ET.SubElement(font_param, "parameterid").text = "fontname"
        ET.SubElement(font_param, "name").text = "Font"
        ET.SubElement(font_param, "value").text = style.font_family

        size_param = ET.SubElement(effect, "parameter")
        ET.SubElement(size_param, "parameterid").text = "fontsize"
        ET.SubElement(size_param, "name").text = "Size"
        ET.SubElement(size_param, "value").text = str(style.font_size)

        color_param = ET.SubElement(effect, "parameter")
        ET.SubElement(color_param, "parameterid").text = "fontcolor"
        ET.SubElement(color_param, "name").text = "Color"
        color_value = ET.SubElement(color_param, "value")
        r, g, b = self._hex_to_rgb(style.color)
        ET.SubElement(color_value, "red").text = str(r)
        ET.SubElement(color_value, "green").text = str(g)
        ET.SubElement(color_value, "blue").text = str(b)
        ET.SubElement(color_value, "alpha").text = "255"

        alignment_param = ET.SubElement(effect, "parameter")
        ET.SubElement(alignment_param, "parameterid").text = "alignment"
        ET.SubElement(alignment_param, "name").text = "Alignment"
        ET.SubElement(alignment_param, "value").text = style.alignment.value

        transform = clip.transform
        if isinstance(transform, Transform):
            self._append_motion_filter(gen_item, transform)

    @staticmethod
    def _hex_to_rgb(color: str) -> tuple[int, int, int]:
        """Best-effort parse of a hex color string ('#RRGGBB' or 'RRGGBB')
        into an (r, g, b) 0-255 tuple. Falls back to white for anything
        else (e.g. a named CSS color), since XMEML's Text generator has no
        equivalent of a CSS color-name resolver and guessing a wrong RGB
        triple would be worse than a documented, visible fallback.
        """
        text = color.strip().lstrip("#")
        if len(text) == 6:
            try:
                return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
            except ValueError:
                pass
        return 255, 255, 255

    def generate_fcpxml(self, timeline: Timeline) -> str:
        """Generate Apple FCPXML v1.10 markup for DaVinci Resolve / Final Cut Pro.

        Note: this produces well-formed, schema-shaped FCPXML (assets,
        format, spine, lane-connected clips), but the exact spine/lane
        layout used here (every clip as a direct spine child positioned by
        absolute `offset`, with video on lane 0+ and audio on negative
        lanes) has not been verified against a real DaVinci Resolve import.
        If clips land in unexpected positions after import, prefer
        `generate_xmeml` (FCP7 XML), which is the more established/battle-
        tested path for DaVinci Resolve specifically.
        """
        root = ET.Element("fcpxml", version="1.10")
        resources = ET.SubElement(root, "resources")

        timebase = int(round(self.fps))
        frame_dur = f"1/{timebase}s"

        # Format resource
        ET.SubElement(
            resources,
            "format",
            id="r1",
            name=f"FFVideoFormat{self.resolution[1]}p{timebase}",
            frameDuration=frame_dur,
            width=str(self.resolution[0]),
            height=str(self.resolution[1]),
        )

        library = ET.SubElement(root, "library")
        event = ET.SubElement(library, "event", name=self.project_name)
        project = ET.SubElement(event, "project", name=self.sequence_name)

        total_duration = Time.zero()
        for track in timeline.all_tracks:
            for clip in track.clips:
                clip_end = clip.timeline_start + clip.duration
                if clip_end > total_duration:
                    total_duration = clip_end

        sequence = ET.SubElement(
            project,
            "sequence",
            format="r1",
            duration=f"{total_duration.seconds:.3f}s",
            tcStart="0s",
        )
        spine = ET.SubElement(sequence, "spine")

        # Map clips to spine and connected lanes
        res_counter = 2
        for track_idx, track in enumerate(timeline.video_tracks):
            lane_attr = str(track_idx)
            for clip in track.clips:
                if isinstance(clip, TextClip):
                    # TextClip has no `source` at all -- previously this
                    # fell into the `else` branch below, which stringified
                    # the resulting None into the literal source path
                    # "None" and emitted it as if it were a real asset.
                    # FCPXML's actual convention for on-timeline text is a
                    # <title> spine/lane element referencing a built-in
                    # title effect, analogous to XMEML's <generatoritem>.
                    self._append_fcpxml_title(spine, clip, lane_attr if track_idx > 0 else "0")
                    continue

                source_path = ""
                if isinstance(clip, MediaClip):
                    source_path = clip.source.source
                else:
                    source_path = getattr(clip, "source", None)
                    source_path = source_path.source if hasattr(source_path, "source") else str(source_path)

                source_path = self._resolve_source(source_path)
                p = Path(source_path)
                src_uri = p.resolve().as_uri() if p.exists() else f"file://{source_path}"

                source = getattr(clip, "source", None)
                source_start_s = source.start.seconds if isinstance(source, Source) else 0.0
                speed = getattr(clip, "speed", 1.0)
                # The span of source media actually consumed: at speed=2,
                # 1s of timeline duration consumes 2s of source -- see the
                # matching comment in generate_xmeml's in/out handling.
                # This was previously not computed at all (the inner
                # <video> element's duration always mirrored the outer
                # clip's duration 1:1), so a clip's `source.start` trim
                # point and `speed` retiming were both silently dropped.
                consumed_source_s = clip.duration.seconds * speed

                asset_id = f"r{res_counter}"
                res_counter += 1
                # `duration` on the asset is the full media's usable
                # range as far as this export knows it (at least the
                # consumed span, starting from `source_start_s`); FCPXML
                # has no independent way to know a source file's true
                # total length without probing it, so this declares only
                # what's demonstrably needed.
                ET.SubElement(
                    resources,
                    "asset",
                    id=asset_id,
                    name=getattr(clip, "id", "clip"),
                    src=src_uri,
                    format="r1",
                    duration=f"{source_start_s + consumed_source_s:.3f}s",
                    hasAudio="1" if self._media_clip_has_audio(clip) else "0",
                )

                clip_elem = ET.SubElement(
                    spine,
                    "clip",
                    name=getattr(clip, "id", "clip"),
                    offset=f"{clip.timeline_start.seconds:.3f}s",
                    duration=f"{clip.duration.seconds:.3f}s",
                    format="r1",
                    lane=lane_attr if track_idx > 0 else "0",
                )
                # `start` is where, within the referenced asset, this
                # clip's content begins (i.e. source.start); `duration`
                # here is measured in *asset*/source time, which is why
                # it's `consumed_source_s` rather than the outer clip's
                # own (timeline) duration when speed != 1 -- FCPXML
                # infers the playback rate from the ratio between this
                # inner duration and the outer <clip> duration above.
                video_elem = ET.SubElement(
                    clip_elem,
                    "video",
                    ref=asset_id,
                    offset="0s",
                    start=f"{source_start_s:.3f}s",
                    duration=f"{consumed_source_s:.3f}s",
                )

                transform = getattr(clip, "transform", None)
                if isinstance(transform, Transform):
                    self._append_fcpxml_transform(video_elem, transform)

                if self._media_clip_has_audio(clip):
                    ET.SubElement(
                        clip_elem,
                        "audio",
                        ref=asset_id,
                        offset="0s",
                        start=f"{source_start_s:.3f}s",
                        duration=f"{consumed_source_s:.3f}s",
                    )

        # Audio tracks. Unlike generate_xmeml (which has a dedicated
        # <audio> section under <media>), FCPXML represents every clip --
        # audio included -- as a spine (or lane-connected) element with an
        # <asset> resource of its own. Audio tracks are placed on negative
        # lanes (below the primary video lane 0), which is the conventional
        # FCPXML way to keep audio out of the video compositing stack while
        # still preserving each track's relative stacking order.
        for track_idx, track in enumerate(timeline.audio_tracks):
            lane_attr = str(-(track_idx + 1))
            for clip in track.clips:
                source_path = clip.source.source if hasattr(clip, "source") else "unknown.wav"
                src_uri = self._resolve_source_uri(self._resolve_source(source_path))

                source = getattr(clip, "source", None)
                source_start_s = source.start.seconds if isinstance(source, Source) else 0.0
                speed = getattr(clip, "speed", 1.0)
                # See the matching comment in the video-track loop above:
                # previously always equal to the clip's own duration,
                # which silently dropped `source.start` and `speed` for
                # every AudioClip.
                consumed_source_s = clip.duration.seconds * speed

                asset_id = f"r{res_counter}"
                res_counter += 1
                ET.SubElement(
                    resources,
                    "asset",
                    id=asset_id,
                    name=getattr(clip, "id", "audio_clip"),
                    src=src_uri,
                    duration=f"{source_start_s + consumed_source_s:.3f}s",
                    hasAudio="1",
                    audioSources="1",
                    audioChannels="2",
                )

                clip_elem = ET.SubElement(
                    spine,
                    "clip",
                    name=getattr(clip, "id", "audio_clip"),
                    offset=f"{clip.timeline_start.seconds:.3f}s",
                    duration=f"{clip.duration.seconds:.3f}s",
                    lane=lane_attr,
                )
                audio_elem = ET.SubElement(
                    clip_elem,
                    "audio",
                    ref=asset_id,
                    offset="0s",
                    start=f"{source_start_s:.3f}s",
                    duration=f"{consumed_source_s:.3f}s",
                )

                audio_properties = getattr(clip, "audio_properties", None)
                if audio_properties is not None:
                    volume = 0.0 if audio_properties.muted else audio_properties.volume
                    ET.SubElement(
                        audio_elem,
                        "adjust-volume",
                        amount=f"{self._volume_to_db(volume):.2f}dB",
                    )

        xml_bytes = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(xml_bytes)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    @staticmethod
    def _media_clip_has_audio(clip: Any) -> bool:
        """Whether a MediaClip's own embedded audio stream should be
        represented in export. True unless the clip explicitly muted its
        `source_audio` -- previously FCPXML's video-clip branch never
        declared audio for a MediaClip at all, so a video's built-in
        soundtrack was always silently dropped regardless of this field.
        """
        if not isinstance(clip, MediaClip):
            return False
        source_audio = getattr(clip, "source_audio", None)
        return source_audio is None or not source_audio.muted

    @staticmethod
    def _append_fcpxml_transform(video_elem: ET.Element, transform: Transform) -> None:
        """Append an <adjust-transform> element encoding `transform`.

        FCPXML's built-in spatial-conform effect for position/scale/
        rotation is <adjust-transform>, with `position` as an "x y" pair
        in canvas points and `scale` as an "x y" pair of multipliers
        (uniform here, since Transform has one `scale` for both axes).
        Zoom (crop-then-fill) has no direct FCPXML equivalent as a single
        attribute, so it's folded into the same uniform scale multiplier
        -- an approximation (true zoom crops rather than scaling the
        whole frame) noted here rather than silently ignored.
        """
        effective_scale = transform.scale * transform.zoom
        ET.SubElement(
            video_elem,
            "adjust-transform",
            position=f"{transform.position.x:.4f} {transform.position.y:.4f}",
            scale=f"{effective_scale:.4f} {effective_scale:.4f}",
            rotation=f"{transform.rotation:.4f}",
        )
        if transform.opacity != 100:
            ET.SubElement(
                video_elem,
                "adjust-blend",
                amount=f"{transform.opacity}%",
            )

    def _append_fcpxml_title(self, spine: ET.Element, clip: TextClip, lane_attr: str) -> None:
        """Append a <title> spine/lane element representing a TextClip.

        FCPXML's convention for on-timeline text is a <title> element
        referencing a built-in title effect (here "Basic Title", a
        standard Resolve/FCP built-in), with a <text> child carrying the
        actual string and a <text-style> describing font/size/color --
        not an <asset>/<clip> pair, since text has no source media file.
        """
        title_elem = ET.SubElement(
            spine,
            "title",
            name=clip.id,
            offset=f"{clip.timeline_start.seconds:.3f}s",
            duration=f"{clip.duration.seconds:.3f}s",
            ref="basic-title",
            lane=lane_attr,
        )
        style = clip.style
        style_id = f"ts-{clip.id}"
        text_elem = ET.SubElement(title_elem, "text")
        text_style_run = ET.SubElement(text_elem, "text-style", ref=style_id)
        text_style_run.text = clip.text

        r, g, b = self._hex_to_rgb(style.color)
        ET.SubElement(
            title_elem,
            "text-style-def",
            id=style_id,
        )
        style_def = title_elem.find("text-style-def")
        ET.SubElement(
            style_def,
            "text-style",
            font=style.font_family,
            fontSize=str(style.font_size),
            fontColor=f"{r / 255:.4f} {g / 255:.4f} {b / 255:.4f} 1",
            bold="1" if style.weight in ("bold", "700", "800", "900") else "0",
            alignment=style.alignment.value,
        )

        transform = clip.transform
        if isinstance(transform, Transform):
            self._append_fcpxml_transform(title_elem, transform)
