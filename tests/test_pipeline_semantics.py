"""Pipeline semantics: flattening never mutates the source, compounds compose
transforms and clip their content, template parameters fail loudly."""

import pytest

import visualkit as vk
from visualkit import (
    CompoundClip,
    ExposedParameter,
    MediaClip,
    Position,
    TemplateParameterError,
    TextClip,
    Time,
    Timeline,
    TimelineValidationError,
    Transform,
)
from visualkit.engine.pipeline import compose_transforms


def text(clip_id="t", start=0, dur=4, body="orig") -> TextClip:
    return TextClip(id=clip_id, text=body, timeline_start=Time(start), duration=Time(dur))


def media(clip_id="m", start=0, dur=4, **kw) -> MediaClip:
    return MediaClip(
        id=clip_id, source=f"{clip_id}.mp4", timeline_start=Time(start), duration=Time(dur), **kw
    )


def wrap(inner_clips, *, start=0, dur=4, speed=1.0, transform=None, cid="c") -> tuple[Timeline, CompoundClip]:
    inner = Timeline()
    for c in inner_clips:
        inner.add_clip(c)
    comp = CompoundClip(
        id=cid,
        timeline_start=Time(start),
        duration=Time(dur),
        speed=speed,
        inner_timeline=inner,
        **({"transform": transform} if transform else {}),
    )
    root = Timeline()
    root.add_clip(comp)
    return root, comp


class TestFlattenDoesNotMutate:
    def test_exposed_parameter_default_is_not_baked_into_the_template(self):
        root, comp = wrap([text()])
        comp.expose_parameter("headline", "t", "text", default="DEFAULT")
        before = root.model_dump_json()
        flat = root.flatten()
        assert flat.video_tracks[0].clips[0].text == "DEFAULT"  # applied to the output...
        assert root.model_dump_json() == before  # ...but never to the user's template
        assert comp.inner_timeline.video_tracks[0].clips[0].text == "orig"

    def test_flatten_output_shares_no_clip_objects_with_the_source(self):
        root = Timeline()
        root.add_clip(text())
        flat = root.flatten()
        assert flat.video_tracks[0].clips[0] is not root.video_tracks[0].clips[0]

    def test_repeated_flatten_is_stable(self):
        """Track ids are random per Timeline, so compare the clips (what exporters consume)."""
        root, comp = wrap([media()], start=3)

        def clips(flat):
            return [
                [c.model_dump(mode="json") for c in track.clips]
                for track in (*flat.video_tracks, *flat.audio_tracks)
            ]

        assert clips(root.flatten()) == clips(root.flatten())


class TestCompoundTransformComposition:
    def test_compound_transform_reaches_its_children(self):
        root, _ = wrap([text()], transform=Transform(scale=0.5, opacity=50))
        out = root.flatten().video_tracks[0].clips[0].transform
        assert out.scale == pytest.approx(0.5)
        assert out.opacity == 50

    def test_child_and_parent_scale_and_opacity_multiply(self):
        child = text()
        child.transform = Transform(scale=0.5, opacity=50)
        root, _ = wrap([child], transform=Transform(scale=0.5, opacity=50))
        out = root.flatten().video_tracks[0].clips[0].transform
        assert out.scale == pytest.approx(0.25)
        assert out.opacity == 25  # 50% of 50%

    def test_rotations_add_and_offsets_rotate_with_the_parent(self):
        outer = Transform(rotation=90, position=Position(x=100, y=0))
        inner = Transform(rotation=10, position=Position(x=10, y=0))
        out = compose_transforms(outer, inner)
        assert out.rotation == pytest.approx(100)
        assert out.position.x == pytest.approx(
            100, abs=1e-6
        )  # child's +x offset turned to +y by the 90 deg parent
        assert out.position.y == pytest.approx(10, abs=1e-6)

    def test_identity_parent_leaves_child_untouched(self):
        child = Transform(scale=2, opacity=70, rotation=5)
        out = compose_transforms(Transform(), child)
        assert (out.scale, out.opacity, out.rotation) == (2, 70, 5)

    def test_extreme_composition_is_clamped_to_valid_ranges(self):
        out = compose_transforms(Transform(scale=100), Transform(scale=100))
        assert out.scale <= 100


class TestCompoundContentIsClipped:
    def test_inner_clip_longer_than_compound_is_cut_to_compound_end(self):
        root, _ = wrap([media(dur=10)], dur=4)
        clip = root.flatten().video_tracks[0].clips[0]
        assert clip.duration == Time(4)

    def test_inner_clip_starting_after_compound_end_is_dropped(self):
        root, _ = wrap([media("early", 0, 2), media("late", 6, 2)], dur=4)
        ids = [c.id for c in root.flatten().video_tracks[0].clips]
        assert ids == ["early"]

    def test_offset_compound_places_and_clips_correctly(self):
        root, _ = wrap([media(dur=10)], start=5, dur=3)
        clip = root.flatten().video_tracks[0].clips[0]
        assert clip.timeline_start == Time(5) and clip.duration == Time(3)

    def test_nested_compound_is_clipped_by_its_ancestor(self):
        inner_root, _ = wrap([media(dur=10)], dur=8, cid="inner")
        outer_inner = Timeline()
        outer_inner.add_clip(inner_root.video_tracks[0].clips[0])
        outer = CompoundClip(id="outer", duration=Time(3), inner_timeline=outer_inner)
        root = Timeline()
        root.add_clip(outer)
        clip = root.flatten().video_tracks[0].clips[0]
        assert clip.duration == Time(3)  # limited by the *outer* 3s, not inner's 8s


class TestTemplateParameters:
    def _comp(self):
        return wrap([text()])

    def test_unknown_parameter_name_raises(self):
        _, comp = self._comp()
        with pytest.raises(TemplateParameterError, match="no exposed parameter"):
            comp.set_parameter("typo", 1)

    def test_target_clip_that_does_not_exist_fails_at_export(self):
        root, comp = self._comp()
        comp.expose_parameter("x", "ghost", "text", default="v")
        with pytest.raises(TemplateParameterError, match="does not exist"):
            root.flatten()

    def test_target_property_that_does_not_exist_fails_at_export(self):
        root, comp = self._comp()
        comp.expose_parameter("x", "t", "no_such_property", default="v")
        with pytest.raises(TemplateParameterError, match="no variable or property"):
            root.flatten()

    @pytest.mark.parametrize("protected", ["id", "clip_type", "linked_clip_id", "inner_timeline"])
    def test_parameters_cannot_rewrite_identity_fields(self, protected):
        root, comp = self._comp()
        comp.expose_parameter("x", "t", protected, default="hijack")
        with pytest.raises(TemplateParameterError, match="protected"):
            root.flatten()
        assert comp.inner_timeline.video_tracks[0].clips[0].id == "t"

    def test_lenient_mode_never_corrupts_the_id_either(self):
        _, comp = self._comp()
        comp.expose_parameter("x", "t", "id")
        comp.set_parameter("x", "hijack")
        assert comp.inner_timeline.video_tracks[0].clips[0].id == "t"

    def test_namespaced_clip_dot_property_still_works(self):
        _, comp = self._comp()
        comp.set_parameter("t.text", "via path")
        assert comp.inner_timeline.video_tracks[0].clips[0].text == "via path"

    def test_wrong_value_type_is_surfaced_by_validation(self):
        _, comp = self._comp()
        comp.expose_parameter("x", "t", "duration")
        with pytest.raises(vk.InvalidTimeError):
            comp.set_parameter("x", "not a time")


class TestCycles:
    def test_self_containing_compound_is_a_clear_error_not_recursion(self):
        comp = CompoundClip(id="c", duration=Time(5), inner_timeline=Timeline())
        comp.inner_timeline.video_tracks.append(vk.VideoTrack()) if False else None
        # bypass add_clip's own guard to prove the pipeline defends itself independently
        inner = comp.inner_timeline
        inner.add_video_track()
        inner.video_tracks[0].clips.append(comp)
        root = Timeline()
        root.add_video_track()
        root.video_tracks[0].clips.append(comp)
        with pytest.raises(TimelineValidationError, match="contains itself"):
            root.flatten()
