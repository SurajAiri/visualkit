"""Example 3: Compound Clips & Reusable Video Templates

Demonstrates:
- Packaging complex multi-track scenes into reusable CompoundClip containers.
- Exposing template parameters (with labels, descriptions, and defaults) for callers and AI agents.
- Automatic creation and routing of companion audio clips on the audio lane.
- Flattening nested compound timelines with cascading speed and audio volume multipliers.
"""

from pathlib import Path

import visualkit as vk


def create_lower_third_template() -> vk.CompoundClip:
    """Build a reusable Lower Third title card template."""
    inner = vk.Timeline()

    # Visual track 0: Title text
    inner.add_clip(
        vk.TextClip(
            id="speaker_name",
            text="Default Speaker",
            timeline_start=vk.Time.from_seconds(0),
            duration=vk.Time.from_seconds(6),
            style=vk.TextStyle(font_size=48, color="#ffffff"),
        ),
        track_index=0,
    )

    # Visual track 1: Role subtitle
    inner.add_clip(
        vk.TextClip(
            id="speaker_role",
            text="Default Title",
            timeline_start=vk.Time.from_seconds(0.5),
            duration=vk.Time.from_seconds(5.5),
            style=vk.TextStyle(font_size=28, color="#94a3b8"),
        ),
        track_index=1,
    )

    # Audio track 0: Whoosh transition sound effect
    inner.add_clip(
        vk.AudioClip(
            id="sfx_whoosh",
            source="assets/whoosh.wav",
            timeline_start=vk.Time.from_seconds(0),
            duration=vk.Time.from_seconds(1.5),
        ),
        track_index=0,
    )

    # Wrap inside CompoundClip
    compound = vk.CompoundClip(
        id="tpl_lower_third",
        timeline_start=vk.Time.from_seconds(0),
        duration=vk.Time.from_seconds(6),
        inner_timeline=inner,
    )

    # Expose configurable parameters for template consumers
    compound.expose_parameter(
        name="speaker_name",
        target_clip_id="speaker_name",
        target_variable="text",
        label="Speaker Name",
        description="Name of the person being interviewed",
        required=True,
    )
    compound.expose_parameter(
        name="speaker_role",
        target_clip_id="speaker_role",
        target_variable="text",
        label="Speaker Role",
        description="Professional title or company affiliation",
        default="Software Engineer",
    )

    return compound


def main():
    print("=== VisualKit Example 3: Compound Clips & Templates ===")

    # 1. Instantiate the template
    lower_third = create_lower_third_template()

    # 2. Inspect exposed parameters (AI agent / UI form discovery)
    print("Exposed Parameters:")
    for p in lower_third.exposed_parameters:
        req = " (required)" if p.required else ""
        print(f"  - {p.name}: {p.label}{req} -> '{p.description}'")

    # 3. Configure parameter values
    lower_third.set_parameter("speaker_name", "Dr. Jane Doe")
    lower_third.set_parameter("speaker_role", "Principal AI Researcher")
    print("\nConfigured parameters:", lower_third.get_set_parameters())

    # 4. Place compound clip on the main root timeline at 3.0s with 1.5x speed
    root_timeline = vk.Timeline()
    lower_third.timeline_start = vk.Time.from_seconds(3)
    lower_third.speed = 1.0

    # Adding compound clip automatically creates its audio companion on audio track 0!
    root_timeline.add_clip(lower_third)

    print(f"\nRoot Video Tracks: {len(root_timeline.video_tracks)}")
    print(f"Root Audio Tracks: {len(root_timeline.audio_tracks)}")
    print(
        f"Root Audio Clips:  {len(root_timeline.audio_tracks[0].clips)} (includes compound audio companion)"
    )

    # 5. Flatten the hierarchy
    # The pipeline expands nested tracks into absolute timeline time, propagates parameters,
    # and mixes audio gains cleanly.
    flattened = root_timeline.flatten()
    print("\n--- After Flattening ---")
    print(f"Flattened Video Tracks: {len(flattened.video_tracks)}")
    for i, track in enumerate(flattened.video_tracks):
        for clip in track.clips:
            t = getattr(clip, "text", "")
            print(f"  V{i}: [{clip.id}] start={clip.timeline_start} dur={clip.duration} text='{t}'")

    for i, track in enumerate(flattened.audio_tracks):
        for clip in track.clips:
            v = clip.audio_properties.volume
            print(f"  A{i}: [{clip.id}] start={clip.timeline_start} dur={clip.duration} vol={v}")


if __name__ == "__main__":
    main()
