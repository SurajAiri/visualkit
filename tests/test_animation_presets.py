"""`ClipAnimation` presets: model, compilation to keyframes, split/trim edge-clearing, and
real rendered fades/slides/pops/wipes.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from pydantic import ValidationError

from tests.rendering_helpers import H, W, at, curve, make_clip, png, render
from visualkit.models import (
    AnimationPreset,
    ClipAnimation,
    Mask,
    MediaClip,
    Source,
    TextClip,
    TextStyle,
    Timeline,
    Transform,
)
from visualkit.models.animation import compile_animation
from visualkit.utils.time import Time

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _clip(**kw) -> MediaClip:
    return MediaClip(id="c", source=Source(source="x.mp4"), duration=Time(2), **kw)


# --------------------------------------------------------------------------- model
class TestModel:
    def test_needs_at_least_one_preset(self):
        with pytest.raises(ValidationError, match="in_preset/out_preset"):
            ClipAnimation()

    @pytest.mark.parametrize(
        "kwargs",
        [{"in_duration": 0}, {"out_duration": -1}, {"pop_from": 0}, {"pop_from": 1}, {"slide_distance": 0}],
    )
    def test_invalid_values_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            ClipAnimation(in_preset="fade", **kwargs)

    def test_round_trips_through_json_on_a_clip(self):
        clip = _clip(animation=ClipAnimation(in_preset="slide_left", out_preset="pop", easing="ease_in_out"))
        assert MediaClip.model_validate_json(clip.model_dump_json()) == clip

    def test_is_animated_sees_a_bare_animation_with_no_keyframes(self):
        assert _clip(animation=ClipAnimation(in_preset="fade")).is_animated is True
        assert _clip().is_animated is False

    def test_text_clips_can_carry_an_animation_too(self):
        clip = TextClip(
            text="hi", duration=Time(2), style=TextStyle(), animation=ClipAnimation(in_preset="fade")
        )
        assert clip.effective_keyframes()["opacity"].value_at(0) == 0


# --------------------------------------------------------------------------- compile_animation
class TestCompile:
    def test_fade_in_and_out_hold_in_the_middle(self):
        anim = ClipAnimation(
            in_preset="fade", out_preset="fade", in_duration=0.5, out_duration=0.5, easing="linear"
        )
        curves = compile_animation(anim, Time(3), Transform(), {})
        o = curves["opacity"]
        assert o.value_at(0) == 0
        assert o.value_at(0.25) == pytest.approx(50)
        assert o.value_at(0.5) == 100
        assert o.value_at(1.5) == 100
        assert o.value_at(2.5) == 100  # the out-ramp starts here, at the last out_duration
        assert o.value_at(2.75) == pytest.approx(50)
        assert o.value_at(3) == pytest.approx(0, abs=1e-6)

    def test_default_easing_is_ease_out_not_linear(self):
        anim = ClipAnimation(in_preset="fade", in_duration=1.0)
        o = compile_animation(anim, Time(2), Transform(), {})["opacity"]
        assert o.value_at(0.5) > 50  # ease-out front-loads progress: past the linear midpoint

    def test_fade_respects_the_clip_s_own_static_opacity(self):
        anim = ClipAnimation(in_preset="fade", in_duration=0.5)
        curves = compile_animation(anim, Time(2), Transform(opacity=60), {})
        assert curves["opacity"].value_at(0.5) == 60

    @pytest.mark.parametrize(
        "preset, prop, sign",
        [
            (AnimationPreset.SLIDE_UP, "position.y", 1),
            (AnimationPreset.SLIDE_DOWN, "position.y", -1),
            (AnimationPreset.SLIDE_LEFT, "position.x", 1),
            (AnimationPreset.SLIDE_RIGHT, "position.x", -1),
        ],
    )
    def test_slides_start_offset_and_land_on_the_static_position(self, preset, prop, sign):
        anim = ClipAnimation(in_preset=preset, in_duration=0.5, slide_distance=90)
        curves = compile_animation(anim, Time(2), Transform(), {})
        c = curves[prop]
        assert c.value_at(0) == pytest.approx(sign * 90)
        assert c.value_at(0.5) == pytest.approx(0)

    def test_pop_starts_at_a_fraction_of_the_final_scale(self):
        anim = ClipAnimation(in_preset="pop", in_duration=0.4, pop_from=0.3)
        curves = compile_animation(anim, Time(2), Transform(scale=0.9), {})
        s = curves["scale"]
        assert s.value_at(0) == pytest.approx(0.27)
        assert s.value_at(0.4) == pytest.approx(0.9)

    def test_wipe_reveals_from_zero_to_full(self):
        anim = ClipAnimation(in_preset="wipe", in_duration=0.5)
        curves = compile_animation(anim, Time(2), Transform(), {})
        w = curves["mask.width"]
        assert w.value_at(0) == 0
        assert w.value_at(0.5) == 1

    def test_short_clip_makes_the_ramps_meet_at_the_midpoint(self):
        anim = ClipAnimation(
            in_preset="fade", out_preset="fade", in_duration=1.0, out_duration=1.0, easing="linear"
        )
        curves = compile_animation(anim, Time(0.6), Transform(), {})
        o = curves["opacity"]
        assert o.value_at(0) == 0
        assert o.value_at(0.3) == pytest.approx(100)
        assert o.value_at(0.6) == pytest.approx(0, abs=1e-6)

    def test_a_hand_authored_keyframe_on_the_same_property_wins(self):
        anim = ClipAnimation(in_preset="fade", in_duration=0.5)
        existing = {"opacity": curve((0, 40), (2, 40))}
        curves = compile_animation(anim, Time(2), Transform(), existing)
        assert "opacity" not in curves

    def test_in_and_out_on_different_properties_both_appear(self):
        anim = ClipAnimation(in_preset="fade", out_preset="slide_up")
        curves = compile_animation(anim, Time(2), Transform(), {})
        assert set(curves) == {"opacity", "position.y"}


# --------------------------------------------------------------------------- effective_keyframes/mask
class TestEffective:
    def test_effective_keyframes_merges_animation_under_explicit_keyframes(self):
        clip = _clip(
            animation=ClipAnimation(in_preset="fade", out_preset="slide_up"),
            keyframes={"opacity": curve((0, 10), (2, 10))},
        )
        eff = clip.effective_keyframes()
        assert eff["opacity"].value_at(0) == 10  # explicit wins
        assert "position.y" in eff  # preset still contributes its own property

    def test_wipe_synthesises_a_full_frame_mask_when_none_is_set(self):
        clip = _clip(animation=ClipAnimation(in_preset="wipe", in_duration=0.5))
        mask = clip.effective_mask()
        assert mask is not None and (mask.width, mask.height) == (1.0, 1.0)
        assert clip.mask_at(0.0).width == 0
        assert clip.mask_at(0.5).width == 1

    def test_wipe_is_skipped_if_the_clip_already_has_its_own_mask(self):
        clip = _clip(animation=ClipAnimation(in_preset="wipe"), mask=Mask(shape="ellipse"))
        assert clip.effective_mask().shape == "ellipse"
        assert "mask.width" not in clip.effective_keyframes()

    def test_transform_at_reflects_the_animation(self):
        clip = _clip(animation=ClipAnimation(in_preset="fade", in_duration=1.0))
        assert clip.transform_at(0).opacity == 0
        assert clip.transform_at(1.0).opacity == 100


# --------------------------------------------------------------------------- split/trim
class TestSplitAndTrim:
    def _timeline(self, **kw):
        t = Timeline()
        t.add_clip(_clip(**kw))
        return t

    def test_split_drops_in_preset_from_the_second_half_and_out_from_the_first(self):
        t = self._timeline(animation=ClipAnimation(in_preset="fade", out_preset="slide_up"))
        first, second = t.split_clip("c", Time(1.0))
        assert (first.animation.in_preset, first.animation.out_preset) == (AnimationPreset.FADE, None)
        assert (second.animation.in_preset, second.animation.out_preset) == (None, AnimationPreset.SLIDE_UP)

    def test_split_clears_the_whole_field_when_nothing_survives(self):
        t = self._timeline(animation=ClipAnimation(in_preset="fade"))
        first, second = t.split_clip("c", Time(1.0))
        assert first.animation is not None
        assert second.animation is None

    def test_trim_in_keeps_the_in_preset_it_just_follows_the_new_start(self):
        # Unlike split, trim_in relocates the *same* real start -- "fade in over the first
        # 0.5s" still means the same thing there, so the preset is not cleared.
        t = self._timeline(animation=ClipAnimation(in_preset="fade", out_preset="pop"))
        clip = t.trim_in("c", Time(0.5))
        assert clip.animation.in_preset == AnimationPreset.FADE
        assert clip.animation.out_preset == AnimationPreset.POP
        assert clip.effective_keyframes()["opacity"].value_at(0) == 0  # fades in from the new start

    def test_trim_out_keeps_the_out_preset_it_just_follows_the_new_end(self):
        t = self._timeline(animation=ClipAnimation(in_preset="fade", out_preset="pop"))
        clip = t.trim_out("c", Time(1.5))
        assert clip.animation.in_preset == AnimationPreset.FADE
        assert clip.animation.out_preset == AnimationPreset.POP

    def test_extending_trim_out_keeps_the_out_preset(self):
        t = self._timeline(animation=ClipAnimation(out_preset="fade"))
        clip = t.trim_out("c", Time(3.0))
        assert clip.animation.out_preset == AnimationPreset.FADE

    def test_duplicate_keeps_the_whole_animation(self):
        t = self._timeline(animation=ClipAnimation(in_preset="fade", out_preset="pop"))
        dup = t.duplicate_clip("c")
        assert dup.animation == ClipAnimation(in_preset="fade", out_preset="pop")


# --------------------------------------------------------------------------- real renders
def _bg(tmp_path):
    return make_clip(png(tmp_path / "bg.png", color=(0, 0, 0, 255)), start=0, duration=2, clip_id="bg")


@needs_ffmpeg
class TestRendered:
    def test_fade_in_render(self, tmp_path):
        clip = make_clip(
            png(tmp_path / "w.png"),
            start=0,
            duration=2,
            animation=ClipAnimation(in_preset="fade", in_duration=1.0, easing="linear"),
        )
        frames = render(tmp_path, _bg(tmp_path), clip)
        for t, expect in [(0.0, 0), (0.5, 128), (1.0, 255)]:
            level = int(at(frames, t)[H // 2, W // 2, 1])
            assert level == pytest.approx(expect, abs=10), t

    def test_slide_up_render(self, tmp_path):
        clip = make_clip(
            png(tmp_path / "w.png", size=(40, 40)),
            start=0,
            duration=2,
            transform=Transform(size={"width": 40, "height": 40}),  # keep it small, not fit-to-canvas
            animation=ClipAnimation(
                in_preset="slide_up", in_duration=1.0, slide_distance=60, easing="linear"
            ),
        )
        frames = render(tmp_path, _bg(tmp_path), clip)
        for t, dy in [(0.0, 60), (1.0, 0)]:
            ys, xs = np.where(at(frames, t)[:, :, 1] > 128)
            assert len(xs), t
            cy = (ys.min() + ys.max()) / 2
            assert cy == pytest.approx(H / 2 + dy, abs=4), t

    def test_pop_render(self, tmp_path):
        clip = make_clip(
            png(tmp_path / "w.png"),
            start=0,
            duration=2,
            transform=Transform(scale=0.5),
            animation=ClipAnimation(in_preset="pop", in_duration=1.0, pop_from=0.4, easing="linear"),
        )
        frames = render(tmp_path, _bg(tmp_path), clip)
        for t, expect_w in [(0.0, 0.5 * 0.4), (1.0, 0.5)]:
            ys, xs = np.where(at(frames, t)[:, :, 1] > 128)
            assert (xs.max() - xs.min() + 1) == pytest.approx(expect_w * W, abs=6), t

    def test_wipe_render(self, tmp_path):
        clip = make_clip(
            png(tmp_path / "w.png"),
            start=0,
            duration=2,
            animation=ClipAnimation(in_preset="wipe", in_duration=1.0, easing="linear"),
        )
        frames = render(tmp_path, _bg(tmp_path), clip)
        for t, expect_w in [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]:
            row = at(frames, t)[H // 2, :, 1]
            revealed = int((row > 128).sum())
            assert revealed == pytest.approx(expect_w * W, abs=8), t

    def test_fade_out_at_the_true_clip_end_after_a_split(self, tmp_path):
        """A regression check for the split-drops-mismatched-edge fix: the fade-out that used to
        target the original clip's end must still land there, not at the new split boundary."""
        timeline = Timeline()
        timeline.add_clip(_bg(tmp_path), track_index=0)
        timeline.add_clip(
            make_clip(
                png(tmp_path / "w.png"),
                start=0,
                duration=2,
                animation=ClipAnimation(out_preset="fade", out_duration=0.5),
            ),
            track_index=1,
        )
        first, second = timeline.split_clip("c", Time(0.8))
        assert first.animation is None  # the split point is not the true end; no fade there
        assert second.animation.out_preset == AnimationPreset.FADE
        out = timeline.export_to_video(tmp_path / "o.mp4", fps=10, resolution=(W, H))
        import subprocess

        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
            check=True,
        ).stdout
        frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(int)
        at_split = frames[8]  # t=0.8s: still mid-clip, must be fully opaque, not fading
        at_true_end = frames[19]  # t=1.9s: 0.1s from the true 2s end, mid fade-out
        assert int(at_split[H // 2, W // 2, 1]) > 240
        assert int(at_true_end[H // 2, W // 2, 1]) < 240
