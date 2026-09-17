from visualkit.models import (
    AudioClip,
    CompoundClip,
    InsertMode,
    MediaClip,
    Source,
    TextClip,
    Timeline,
    VideoTrack,
)
from visualkit.utils.time import Time

# 1. Create inner timeline with direct add_clip on timeline
inner = Timeline()
inner.add_clip(TextClip(text="Inner Title", duration=Time.from_seconds(5)))

# 2. Wrap inside CompoundClip
compound = CompoundClip(
    timeline_start=Time.from_seconds(2),
    duration=Time.from_seconds(10),
    inner_timeline=inner,
    parameters={"theme": "dark"},
)

# 3. Add compound clip and an audio clip directly to root timeline
root = Timeline()
root.add_clip(compound)
root.add_clip(AudioClip(source=Source(source="bg_music.mp3"), duration=Time.from_seconds(15)))

# Notice: compound clip automatically created its audio companion on audio_tracks[0]!
print("Root video tracks:", len(root.video_tracks))
print("Root audio tracks:", len(root.audio_tracks))
print("Root audio clips count:", len(root.audio_tracks[0].clips))

# 4. Add another visual clip with RIPPLE mode
text_clip2 = TextClip(text="Intro", timeline_start=Time.from_seconds(1), duration=Time.from_seconds(3))
root.add_clip(text_clip2, mode=InsertMode.RIPPLE)

# Verify ripple shifted the compound clip to the right
print("Compound start after ripple:", root.video_tracks[0].clips[1].timeline_start)

# 5. Round-trip JSON validation
json_str = root.model_dump_json(indent=2)
restored = Timeline.model_validate_json(json_str)

assert isinstance(restored.video_tracks[0].clips[1], CompoundClip)
assert isinstance(restored.video_tracks[0].clips[1].inner_timeline, Timeline)
print("All validations and direct timeline.add_clip checks passed!")
