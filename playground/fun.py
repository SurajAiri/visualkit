from visualkit.models.clips import Clip, MediaClip, TextClip
from visualkit.models.clips.audio import AudioClip
from visualkit.models.clips.base import Source
from visualkit.models.timeline import Timeline, Track
from visualkit.utils.time import Time

m1 = MediaClip(
    id="media1",
    timeline_start=Time.zero(),
    duration=Time.from_seconds(10),
    source=Source(source="video.mp4", start=Time.zero()),
)

m2 = MediaClip(
    id="media2",
    timeline_start=Time.zero(),
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

timeline = Timeline(
    main_track=Track(id="main", visual=[m1, m2, t1], audio=[a1]),
)
