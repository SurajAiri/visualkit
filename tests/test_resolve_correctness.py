"""Regression tests for the DaVinci Resolve exporter (XMEML + FCPXML).

Each test pins a bug found in the audit: NTSC frame drift, un-normalized
positions, duplicated <file> declarations, decimal-second FCPXML times,
an undeclared title effect, and spurious identity motion filters.
"""

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

import visualkit as vk
from visualkit.exporters.resolve import DaVinciResolveExporter


@pytest.fixture
def media(tmp_path: Path) -> str:
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"x")
    return str(p)


def xmeml(timeline: vk.Timeline, fps: float = 30, res=(1920, 1080)) -> ET.Element:
    return ET.fromstring(DaVinciResolveExporter(fps=fps, resolution=res).generate_xmeml(timeline))


def fcpxml(timeline: vk.Timeline, fps: float = 30, res=(1920, 1080)) -> ET.Element:
    return ET.fromstring(DaVinciResolveExporter(fps=fps, resolution=res).generate_fcpxml(timeline))


def one_clip(media: str, **kw) -> vk.Timeline:
    t = vk.Timeline()
    t.add_clip(
        vk.MediaClip(id="a", source=media, duration=vk.Time(kw.pop("dur", 2)), resolution=(640, 360), **kw)
    )
    return t


class TestNtscFrameMath:
    def test_one_hour_at_2997_is_107892_frames_not_108000(self, media):
        root = xmeml(one_clip(media, dur=3600), fps=29.97)
        assert root.find(".//clipitem/end").text == "107892"

    def test_timebase_label_and_ntsc_flag(self, media):
        root = xmeml(one_clip(media), fps=29.97)
        assert root.find("./project/children/sequence/rate/timebase").text == "30"
        assert root.find("./project/children/sequence/rate/ntsc").text == "TRUE"

    def test_true_30_is_not_flagged_ntsc(self, media):
        root = xmeml(one_clip(media), fps=30)
        assert root.find("./project/children/sequence/rate/ntsc").text == "FALSE"

    def test_fcpxml_frame_duration_is_exact_rational(self, media):
        root = fcpxml(one_clip(media), fps=29.97)
        assert root.find(".//format").attrib["frameDuration"] == "1001/30000s"

    def test_fcpxml_times_are_whole_frames(self, media):
        t = vk.Timeline()
        t.add_clip(
            vk.MediaClip(
                id="a", source=media, timeline_start=vk.Time(0), duration=vk.Time(2), resolution=(640, 360)
            )
        )
        t.add_clip(
            vk.MediaClip(
                id="b", source=media, timeline_start=vk.Time(2), duration=vk.Time(1), resolution=(640, 360)
            )
        )
        root = fcpxml(t, fps=29.97)
        n, d = root.find(".//format").attrib["frameDuration"].rstrip("s").split("/")
        frame = Fraction(int(n), int(d))
        for el in root.iter():
            for key in ("offset", "duration", "start"):
                v = el.attrib.get(key)
                if v and v != "0s":
                    a, _, b = v.rstrip("s").partition("/")
                    assert (Fraction(int(a), int(b or 1)) / frame).denominator == 1, (el.tag, key, v)


class TestMotionAndPosition:
    def test_xmeml_center_is_normalized_by_sequence_resolution(self, media):
        t = one_clip(media, transform=vk.Transform(position=vk.Position(x=480, y=-270)))
        root = xmeml(t, res=(1920, 1080))
        assert root.find(".//value/horiz").text == "0.250000"
        assert root.find(".//value/vert").text == "-0.250000"

    def test_identity_transform_emits_no_filters(self, media):
        root = xmeml(one_clip(media))
        assert root.find(".//clipitem/filter") is None

    def test_opacity_only_transform_still_emits_a_filter(self, media):
        root = xmeml(one_clip(media, transform=vk.Transform(opacity=50)))
        names = [f.find("effect/name").text for f in root.findall(".//clipitem/filter")]
        assert "Opacity" in names

    def test_fcpxml_position_is_percent_of_height_with_y_up(self, media):
        t = one_clip(media, transform=vk.Transform(position=vk.Position(x=108, y=108)))
        root = fcpxml(t, res=(1920, 1080))
        assert root.find(".//adjust-transform").attrib["position"] == "10.0000 -10.0000"


class TestFileDeclarations:
    def _two_uses(self, media, **second) -> vk.Timeline:
        t = vk.Timeline()
        t.add_clip(
            vk.MediaClip(
                id="first",
                source=media,
                timeline_start=vk.Time(0),
                duration=vk.Time(1),
                resolution=(640, 360),
                source_audio=vk.AudioProperties(muted=True),
            )
        )
        t.add_clip(
            vk.MediaClip(
                id="second",
                source=vk.Source(source=media, start=vk.Time(1)),
                timeline_start=vk.Time(1),
                duration=vk.Time(2),
                resolution=(640, 360),
                **second,
            )
        )
        return t

    def test_same_file_is_declared_once_and_referenced_after(self, media):
        files = xmeml(self._two_uses(media)).findall(".//file")
        assert len(files) == 2
        assert sum(1 for f in files if f.find("pathurl") is not None) == 1
        assert len({f.attrib["id"] for f in files}) == 1

    def test_declared_duration_covers_furthest_use(self, media):
        declared = next(
            f for f in xmeml(self._two_uses(media)).findall(".//file") if f.find("pathurl") is not None
        )
        assert declared.find("duration").text == "90"  # 1s in + 2s used = 3s @ 30fps

    def test_audio_stream_advertised_even_if_first_use_is_muted(self, media):
        declared = next(
            f for f in xmeml(self._two_uses(media)).findall(".//file") if f.find("pathurl") is not None
        )
        assert declared.find("media/audio") is not None

    def test_reused_file_keeps_per_clip_motion(self, media):
        """A later use of an already-declared file is a bare <file> reference; its own
        transform must still be emitted (regression guard for an early `continue`)."""
        t = self._two_uses(media, transform=vk.Transform(scale=0.5, opacity=60))
        second = next(
            c for c in xmeml(t).findall(".//video/track/clipitem") if c.find("name").text == "second"
        )
        assert [f.find("effect/name").text for f in second.findall("filter")] == ["Basic Motion", "Opacity"]


class TestTitleEffectDeclaration:
    def test_every_ref_resolves_to_a_declared_resource(self, media):
        t = one_clip(media)
        t.add_clip(vk.TextClip(id="t", text="Hi", duration=vk.Time(2)), track_index=1)
        root = fcpxml(t)
        declared = {e.attrib["id"] for e in root.find("resources")}
        refs = {
            e.attrib["ref"] for e in root.iter() if e.tag in ("title", "video", "audio") and "ref" in e.attrib
        }
        assert refs <= declared

    def test_no_title_effect_emitted_when_no_text(self, media):
        root = fcpxml(one_clip(media))
        assert root.find("resources/effect") is None
