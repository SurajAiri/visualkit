from visualkit.models.clips import MediaClip, TextClip
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.base import Source
from visualkit.models.timeline import Timeline
from visualkit.utils.time import Time

m1 = MediaClip(
    id="media1",
    timeline_start=Time.zero(),
    duration=Time.from_seconds(10),
    source=Source(source="video.mp4", start=Time.zero()),
)

m2 = MediaClip(
    id="media2",
    timeline_start=Time.from_seconds(10),
    duration=Time.from_seconds(10),
    source=Source(source="video.mp4", start=Time.zero()),
)

t1 = TextClip(
    id="text1",
    timeline_start=Time.zero(),
    duration=Time.from_seconds(5),
    text="Hello, World!",
)
a1 = AudioClip(
    id="audio1",
    timeline_start=Time.zero(),
    duration=Time.from_seconds(10),
    source=Source(source="audio.mp3", start=Time.zero()),
)

# NOTE: this file previously used a stale, nonexistent constructor shape
# (Timeline(main_track=Track(visual=[...], audio=[...]))) left over from an
# earlier version of the API. Because no model enforced extra="forbid" at
# the time, that call silently succeeded and produced an empty, useless
# Timeline instead of raising -- see the fix in utils/base_model.py.
# Current API: build a Timeline and route clips onto tracks via add_clip.
timeline = Timeline()
timeline.add_clip(m1, track_index=0)
timeline.add_clip(m2, track_index=0)
timeline.add_clip(t1, track_index=1)
timeline.add_clip(a1, track_index=0)

if __name__ == "__main__":
    print(f"Video tracks: {len(timeline.video_tracks)}")
    print(f"Audio tracks: {len(timeline.audio_tracks)}")
    print(f"Total duration: {timeline.duration}")
