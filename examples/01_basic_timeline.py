"""Example 1: Basic Timeline Creation and Multi-Track Export

Demonstrates:
- Creating a Timeline and routing video, text, and audio clips across tracks.
- Setting clip start offsets, durations, and playback speeds.
- Exporting to DaVinci Resolve (FCPXML / XMEML).
- Serializing and inspecting the timeline schema.
"""

from pathlib import Path

import visualkit as vk


def main():
    print("=== VisualKit Example 1: Basic Timeline Creation ===")

    # 1. Initialize timeline
    timeline = vk.Timeline()

    # 2. Add video clip on track 0
    # Note: Source accepts string paths or Source instances directly
    main_video = vk.MediaClip(
        id="hero_video",
        source="assets/sample_footage.mp4",
        timeline_start=vk.Time.from_seconds(0),
        duration=vk.Time.from_seconds(10),
        fps=30.0,
    )
    timeline.add_clip(main_video, track_index=0)

    # 3. Add text overlay on track 1 starting at 2.0s
    title_text = vk.TextClip(
        id="chapter_title",
        text="Chapter 1: The Beginning",
        timeline_start=vk.Time.from_seconds(2),
        duration=vk.Time.from_seconds(5),
        style=vk.TextStyle(font_size=56, color="#f8fafc"),
    )
    timeline.add_clip(title_text, track_index=1)

    # 4. Add background audio on audio track 0
    bg_music = vk.AudioClip(
        id="soundtrack",
        source="assets/music.mp3",
        timeline_start=vk.Time.from_seconds(0),
        duration=vk.Time.from_seconds(12),
    )
    timeline.add_clip(bg_music, track_index=0)

    # 5. Inspect timeline stats
    print(f"Total Duration: {timeline.duration}")
    print(f"Video Tracks:   {len(timeline.video_tracks)}")
    print(f"Audio Tracks:   {len(timeline.audio_tracks)}")

    # 6. Export to DaVinci Resolve format (FCP 7 XML / XMEML or FCPXML)
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    xml_path = out_dir / "timeline_resolve.xml"
    timeline.export_to_resolve(output_path=xml_path, fps=30.0)
    print(f"Exported DaVinci Resolve project: {xml_path}")

    # 7. JSON Round-trip serialization
    json_path = out_dir / "timeline.json"
    json_path.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    print(f"Exported Timeline schema JSON:    {json_path}")


if __name__ == "__main__":
    main()
