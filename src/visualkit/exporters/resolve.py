import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.dom import minidom

from visualkit.exporters.base import BaseExporter
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.media import MediaClip
from visualkit.models.clips.text import TextClip
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
    ):
        self.fps = fps
        self.resolution = resolution
        self.project_name = project_name
        self.sequence_name = sequence_name

    def export(self, timeline: Timeline, output_path: str | Path, **kwargs) -> Path:
        """Export timeline to DaVinci Resolve format.

        Automatically flattens compound clips and compiles coded visuals if needed.
        """
        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure timeline is flattened and resolved
        flattened = timeline.flatten()

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
                start_frame = clip.timeline_start.to_frames(timebase)
                dur_frames = clip.duration.to_frames(timebase)
                end_frame = start_frame + dur_frames

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
                ET.SubElement(clipitem, "in").text = "0"
                ET.SubElement(clipitem, "out").text = str(dur_frames)

                # File reference
                file_elem = ET.SubElement(clipitem, "file", id=f"file-{file_counter}")
                file_counter += 1

                source_path = ""
                if isinstance(clip, MediaClip):
                    source_path = clip.source.source
                elif isinstance(clip, TextClip):
                    source_path = f"generator://text/{clip.text}"
                else:
                    source_path = getattr(clip, "source", None)
                    if hasattr(source_path, "source"):
                        source_path = source_path.source
                    else:
                        source_path = str(source_path or "unknown")

                ET.SubElement(file_elem, "name").text = Path(source_path).name if source_path else name

                # Convert to file URI if local path exists
                if source_path and not source_path.startswith(("file://", "generator://")):
                    p = Path(source_path)
                    path_url = p.resolve().as_uri() if p.exists() else f"file://{source_path}"
                else:
                    path_url = source_path or "file:///unknown"

                ET.SubElement(file_elem, "pathurl").text = path_url

                f_rate = ET.SubElement(file_elem, "rate")
                ET.SubElement(f_rate, "timebase").text = str(timebase)
                ET.SubElement(f_rate, "ntsc").text = is_ntsc
                ET.SubElement(file_elem, "duration").text = str(dur_frames)

                f_media = ET.SubElement(file_elem, "media")
                f_video = ET.SubElement(f_media, "video")
                f_sc = ET.SubElement(f_video, "samplecharacteristics")
                res = getattr(clip, "resolution", self.resolution)
                ET.SubElement(f_sc, "width").text = str(res[0])
                ET.SubElement(f_sc, "height").text = str(res[1])

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
                ET.SubElement(clipitem, "in").text = "0"
                ET.SubElement(clipitem, "out").text = str(dur_frames)

                file_elem = ET.SubElement(clipitem, "file", id=f"file-audio-{file_counter}")
                file_counter += 1

                source_path = clip.source.source if hasattr(clip, "source") else "unknown.wav"
                ET.SubElement(file_elem, "name").text = Path(source_path).name
                p = Path(source_path)
                path_url = p.resolve().as_uri() if p.exists() else f"file://{source_path}"
                ET.SubElement(file_elem, "pathurl").text = path_url

                f_rate = ET.SubElement(file_elem, "rate")
                ET.SubElement(f_rate, "timebase").text = str(timebase)
                ET.SubElement(f_rate, "ntsc").text = is_ntsc
                ET.SubElement(file_elem, "duration").text = str(dur_frames)

        xml_bytes = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(xml_bytes)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    def generate_fcpxml(self, timeline: Timeline) -> str:
        """Generate modern Apple FCPXML v1.10 format for DaVinci Resolve."""
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
                source_path = ""
                if isinstance(clip, MediaClip):
                    source_path = clip.source.source
                else:
                    source_path = getattr(clip, "source", None)
                    source_path = source_path.source if hasattr(source_path, "source") else str(source_path)

                p = Path(source_path)
                src_uri = p.resolve().as_uri() if p.exists() else f"file://{source_path}"

                asset_id = f"r{res_counter}"
                res_counter += 1
                ET.SubElement(
                    resources,
                    "asset",
                    id=asset_id,
                    name=getattr(clip, "id", "clip"),
                    src=src_uri,
                    format="r1",
                    duration=f"{clip.duration.seconds:.3f}s",
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
                ET.SubElement(
                    clip_elem,
                    "video",
                    ref=asset_id,
                    offset="0s",
                    duration=f"{clip.duration.seconds:.3f}s",
                )

        xml_bytes = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(xml_bytes)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
