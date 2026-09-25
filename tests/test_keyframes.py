"""Keyframe model: validation, evaluation, ffmpeg-expression parity, split/trim, serialization.

No ffmpeg needed here. Rendering is covered in test_keyframe_rendering.py.
"""

from __future__ import annotations

import random
import re
from fractions import Fraction

import pytest
from pydantic import ValidationError

from tests.ffexpr import evaluate
from visualkit.models import MediaClip, Source, TextClip, Timeline, Transform
from visualkit.models.keyframes import (
    KEYFRAMEABLE_PROPERTIES,
    Easing,
    Keyframe,
    PropertyCurve,
    fmt_num,
)
from visualkit.utils.exceptions import InvalidSplitError
from visualkit.utils.time import Time

ALL_EASINGS = list(Easing)


def curve(*points, easing: Easing = Easing.LINEAR) -> PropertyCurve:
    return PropertyCurve.from_points(points, easing=easing)


def random_curve(rng: random.Random, *, span: int = 8, lo: float = -100, hi: float = 200) -> PropertyCurve:
    """A curve on a 1/8-second grid (exact in binary) with random values and easings."""
    slots = sorted(rng.sample(range(0, span * 8 + 1), rng.randint(1, min(8, span * 8))))
    return PropertyCurve(
        keyframes=[
            Keyframe(
                time=Time(Fraction(slot, 8)),
                value=rng.uniform(lo, hi),
                easing=rng.choice(ALL_EASINGS),
            )
            for slot in slots
        ]
    )


# --------------------------------------------------------------------------- validation
class TestCurveValidation:
    def test_needs_at_least_one_keyframe(self):
        with pytest.raises(ValidationError):
            PropertyCurve(keyframes=[])

    def test_duplicate_times_are_rejected(self):
        with pytest.raises(ValidationError, match="share time"):
            PropertyCurve(keyframes=[Keyframe(time=Time(1), value=0), Keyframe(time=Time(1), value=5)])

    def test_unsorted_times_are_rejected_with_a_hint(self):
        with pytest.raises(ValidationError, match="from_points"):
            PropertyCurve(keyframes=[Keyframe(time=Time(2), value=0), Keyframe(time=Time(1), value=5)])

    def test_from_points_sorts_but_still_rejects_duplicates(self):
        c = PropertyCurve.from_points([(2, 9), (0, 1), (1, 5)])
        assert [k.time.seconds for k in c.keyframes] == [0, 1, 2]
        with pytest.raises(ValidationError):
            PropertyCurve.from_points([(1, 1), (1, 2)])

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_are_rejected(self, bad):
        with pytest.raises(ValidationError):
            Keyframe(time=Time(0), value=bad)

    def test_negative_time_is_impossible(self):
        with pytest.raises(Exception):
            Keyframe(time=Time(-1), value=0)  # Time itself is non-negative

    def test_unknown_easing_is_rejected(self):
        with pytest.raises(ValidationError):
            Keyframe(time=Time(0), value=0, easing="bounce")  # type: ignore[arg-type]

    @pytest.mark.parametrize("window", [(0.5, 0.5), (0.7, 0.2), (-0.1, 1.0), (0.0, 1.5)])
    def test_bad_ease_windows_are_rejected(self, window):
        with pytest.raises(ValidationError):
            Keyframe(time=Time(0), value=0, ease_window=window)


class TestClipLevelValidation:
    def _clip(self, **kw) -> MediaClip:
        return MediaClip(source=Source(source="x.mp4"), duration=Time(2), **kw)

    def test_unknown_property_name_is_rejected(self):
        with pytest.raises(ValidationError, match="unknown property"):
            self._clip(keyframes={"opacty": curve((0, 0), (1, 100))})

    @pytest.mark.parametrize(
        "prop, value",
        [
            ("opacity", 100.5),
            ("opacity", -1),
            ("scale", 0),
            ("scale", 100.5),
            ("zoom", 0),
            ("rotation", 3601),
            ("rotation", -3601),
        ],
    )
    def test_values_respect_the_static_fields_bounds(self, prop, value):
        with pytest.raises(ValidationError):
            self._clip(keyframes={prop: curve((0, 1 if prop != "opacity" else 50), (1, value))})

    def test_position_is_unbounded(self):
        self._clip(keyframes={"position.x": curve((0, -5000), (1, 5000))})

    def test_keyframe_after_clip_end_is_rejected(self):
        with pytest.raises(ValidationError, match="after the clip ends"):
            self._clip(keyframes={"opacity": curve((0, 0), (2.5, 100))})

    def test_keyframe_exactly_at_clip_end_is_allowed(self):
        self._clip(keyframes={"opacity": curve((0, 0), (2, 100))})

    def test_shrinking_the_clip_below_its_keyframes_is_rejected_and_changes_nothing(self):
        clip = self._clip(keyframes={"opacity": curve((0, 0), (1.5, 100))})
        with pytest.raises(ValidationError):
            clip.duration = Time(1)
        assert clip.duration == Time(2)  # atomic: the rejected assignment did not stick

    def test_rejected_keyframe_assignment_changes_nothing(self):
        clip = self._clip()
        with pytest.raises(ValidationError):
            clip.keyframes = {"opacity": curve((0, 0), (9, 100))}
        assert clip.keyframes == {}

    def test_every_allowed_property_maps_to_something_real(self):
        from visualkit.models.effects import Mask

        t, m = Transform(), Mask()
        for name in KEYFRAMEABLE_PROPERTIES:
            base, _, attr = name.partition(".")
            if base == "mask":
                assert hasattr(m, attr), name  # mask geometry lives on Mask, not Transform
            else:
                assert hasattr(t, base), name

    def test_text_clips_can_be_keyframed_too(self):
        TextClip(text="hi", duration=Time(2), keyframes={"scale": curve((0, 0.5), (1, 1))})

    def test_a_keyed_clip_is_animated_but_its_static_transform_is_still_identity(self):
        clip = self._clip(keyframes={"opacity": curve((0, 0), (1, 100))})
        assert clip.is_animated
        assert clip.transform.is_identity  # Resolve export reads Transform only -- see Transform docstring
        assert not self._clip().is_animated


# --------------------------------------------------------------------------- evaluation
class TestValueAt:
    def test_holds_first_value_before_and_last_value_after(self):
        c = curve((1, 10), (3, 30))
        assert c.value_at(0) == 10
        assert c.value_at(1) == 10
        assert c.value_at(3) == 30
        assert c.value_at(99) == 30

    def test_single_keyframe_is_constant(self):
        c = curve((5, 42))
        assert c.value_at(0) == c.value_at(5) == c.value_at(50) == 42

    def test_linear_midpoint(self):
        assert curve((0, 0), (2, 100)).value_at(1) == pytest.approx(50)

    def test_hold_steps_at_the_next_keyframe(self):
        c = curve((0, 10, Easing.HOLD), (1, 20, Easing.HOLD), (2, 30))
        assert c.value_at(0.999) == 10
        assert c.value_at(1) == 20
        assert c.value_at(1.5) == 20
        assert c.value_at(2) == 30

    def test_ease_in_out_is_symmetric_and_hits_the_midpoint(self):
        c = curve((0, 0), (1, 100), easing=Easing.EASE_IN_OUT)
        assert c.value_at(0.5) == pytest.approx(50)
        assert c.value_at(0.25) == pytest.approx(100 - c.value_at(0.75))

    def test_ease_in_starts_slow_and_ease_out_finishes_slow(self):
        ein = curve((0, 0), (1, 100), easing=Easing.EASE_IN)
        eout = curve((0, 0), (1, 100), easing=Easing.EASE_OUT)
        assert ein.value_at(0.5) == pytest.approx(12.5)
        assert eout.value_at(0.5) == pytest.approx(87.5)

    def test_easing_applies_to_the_segment_starting_at_the_keyframe(self):
        c = curve((0, 0, Easing.EASE_IN), (1, 100, Easing.LINEAR), (2, 200))
        assert c.value_at(0.5) == pytest.approx(12.5)  # eased first segment
        assert c.value_at(1.5) == pytest.approx(150)  # linear second segment

    def test_accepts_time_fraction_and_float(self):
        c = curve((0, 0), (2, 100))
        assert c.value_at(Time(1)) == c.value_at(Fraction(1)) == c.value_at(1.0) == pytest.approx(50)

    @pytest.mark.parametrize("easing", ALL_EASINGS)
    def test_curves_never_overshoot_their_own_keyframe_values(self, easing):
        rng = random.Random(7)
        c = curve((0, -30, easing), (1, 80, easing), (2.5, 10))
        for _ in range(300):
            v = c.value_at(rng.uniform(0, 3))
            assert -30 - 1e-9 <= v <= 80 + 1e-9


# --------------------------------------------------------------------------- expression parity
class TestExpressionMatchesEvaluator:
    """The ffmpeg expression and `value_at` are two implementations of one curve; they must agree."""

    @pytest.mark.parametrize("clip_start", [0.0, 1.0, 3.5, 12.25])
    def test_random_curves_agree_at_200_random_times(self, clip_start):
        rng = random.Random(1234 + int(clip_start * 4))
        for _ in range(25):
            c = random_curve(rng)
            expr = c.to_expr(clip_start)
            for _ in range(8):
                local = rng.uniform(-0.5, 9.0)
                got = evaluate(expr, t=clip_start + local)
                assert got == pytest.approx(c.value_at(local), abs=1e-5), (expr, local)

    def test_expression_uses_absolute_time_so_a_late_clip_starts_late(self):
        c = curve((0, 0), (2, 100))
        expr = c.to_expr(clip_start_s=1.0)
        assert evaluate(expr, t=0.0) == 0  # before the clip starts: held at the first value
        assert evaluate(expr, t=1.0) == pytest.approx(0)
        assert evaluate(expr, t=2.0) == pytest.approx(50)  # 1s into the clip, not 2s
        assert evaluate(expr, t=3.0) == pytest.approx(100)

    def test_hold_step_is_exact_at_the_keyframe_instant(self):
        c = curve((0, 10, Easing.HOLD), (1, 20))
        expr = c.to_expr(2.0)
        assert evaluate(expr, t=2.999) == 10
        assert evaluate(expr, t=3.0) == 20

    def test_constant_curve_is_just_a_number(self):
        assert curve((0, 7.5)).to_expr(3.0) == "7.5"

    def test_flat_segments_contribute_nothing(self):
        expr = curve((0, 5), (1, 5), (2, 5)).to_expr(0)
        assert expr == "5"

    def test_custom_variable_name(self):
        assert evaluate(curve((0, 0), (2, 100)).to_expr(0, var="T"), T=1) == pytest.approx(50)

    def test_negative_numbers_are_parenthesised(self):
        expr = curve((0, -10), (1, -30)).to_expr(0)
        assert "+(-20)*" in expr
        assert expr.startswith("-10")

    def test_no_scientific_notation_even_for_tiny_and_huge_numbers(self):
        c = PropertyCurve(
            keyframes=[
                Keyframe(time=Time(Fraction(1, 1_000_000)), value=1e-9),
                Keyframe(time=Time(Fraction(2, 1_000_000)), value=1e9),
            ]
        )
        expr = c.to_expr(Fraction(1, 3))
        assert not re.search(r"\d[eE][+-]?\d", expr), expr
        assert "e" not in re.sub(r"(clip|gte|pow|lt|if)", "", expr)  # no exponent marker at all

    def test_fmt_num_never_emits_an_exponent(self):
        for x in (1e-12, 1e-5, 123456789.123456789, 2**60, -1e-7, 0.1 + 0.2):
            assert not re.search(r"[eE]", fmt_num(x)), x
        assert fmt_num(-0.0) == "0"
        assert fmt_num(3.0) == "3"

    def test_expression_depth_is_constant_in_the_number_of_keyframes(self):
        """A nested if() chain breaks ffmpeg at ~99 keyframes; the flat form must not nest."""

        def depth(s: str) -> int:
            d = best = 0
            for ch in s:
                d += ch == "("
                best = max(best, d)
                d -= ch == ")"
            return best

        small = PropertyCurve.from_points([(i, i % 7) for i in range(5)], Easing.EASE_IN_OUT)
        big = PropertyCurve.from_points([(i, i % 7) for i in range(1000)], Easing.EASE_IN_OUT)
        assert depth(big.to_expr(0)) == depth(small.to_expr(0))
        assert "if(if(" not in big.to_expr(0)

    def test_thousand_keyframes_still_evaluate_correctly(self):
        pts = [(i * 0.01, (i * 37) % 101) for i in range(1000)]
        c = PropertyCurve.from_points(pts)
        expr = c.to_expr(0)
        for local in (0.0, 0.005, 3.333, 9.9, 9.99, 20):
            assert evaluate(expr, t=local) == pytest.approx(c.value_at(local), abs=1e-4)


# --------------------------------------------------------------------------- split / trim maths
class TestHeadAndTailAreExact:
    """Cutting a curve must never change the motion, even inside an eased segment."""

    @pytest.mark.parametrize("seed", range(40))
    def test_head_and_tail_reproduce_the_original(self, seed):
        rng = random.Random(seed)
        c = random_curve(rng)
        cut = Fraction(rng.randint(1, 63), 8)  # never 0; may or may not sit on a keyframe
        first, second = c.head(cut), c.tail(cut)
        for _ in range(40):
            tau = rng.uniform(0, float(cut))
            assert first.value_at(tau) == pytest.approx(c.value_at(tau), abs=1e-9)
        for _ in range(40):
            tau = rng.uniform(0, 9)
            assert second.value_at(tau) == pytest.approx(c.value_at(tau + float(cut)), abs=1e-9)

    def test_cutting_inside_an_eased_segment_keeps_the_shape(self):
        c = curve((0, 0), (4, 100), easing=Easing.EASE_IN_OUT)
        second = c.tail(1)  # cut a quarter of the way in
        # A naive "restart the cubic from the cut" would be visibly different here:
        naive = curve((0, c.value_at(1)), (3, 100), easing=Easing.EASE_IN_OUT)
        assert second.value_at(1) == pytest.approx(c.value_at(2), abs=1e-9)
        assert abs(second.value_at(1) - naive.value_at(1)) > 1.0
        assert second.value_at(0) == pytest.approx(c.value_at(1))

    def test_tail_of_tail_and_head_of_tail_compose(self):
        rng = random.Random(99)
        for _ in range(30):
            c = random_curve(rng)
            a, b = Fraction(rng.randint(1, 20), 8), Fraction(rng.randint(1, 20), 8)
            both = c.tail(a).tail(b)
            once = c.tail(a + b)
            windowed = c.tail(a).head(b)
            for _ in range(20):
                tau = rng.uniform(0, 6)
                assert both.value_at(tau) == pytest.approx(once.value_at(tau), abs=1e-9)
                if tau <= float(b):
                    assert windowed.value_at(tau) == pytest.approx(c.value_at(tau + float(a)), abs=1e-9)

    def test_negative_offset_reveals_preroll_holding_the_first_value(self):
        c = curve((1, 10), (2, 20))
        shifted = c.tail(Fraction(-1, 2))  # 0.5s of pre-roll
        assert shifted.value_at(0) == 10
        assert shifted.value_at(1.5) == pytest.approx(10)
        assert shifted.value_at(2.0) == pytest.approx(c.value_at(1.5))

    def test_tail_past_the_last_keyframe_is_the_final_value(self):
        c = curve((0, 1), (1, 9))
        t = c.tail(5)
        assert len(t.keyframes) == 1 and t.value_at(0) == 9 and t.keyframes[0].time == Time.zero()

    def test_head_before_the_first_keyframe_is_the_first_value(self):
        h = curve((2, 7), (3, 9)).head(1)
        assert h.value_at(0) == h.value_at(1) == 7

    def test_head_and_tail_leave_the_original_untouched(self):
        c = curve((0, 0), (4, 100), easing=Easing.EASE_OUT)
        before = c.model_dump_json()
        c.head(1)
        c.tail(1)
        assert c.model_dump_json() == before

    @pytest.mark.parametrize("seed", range(15))
    def test_cut_curves_still_match_their_ffmpeg_expression(self, seed):
        """Easing windows must round-trip through the expression too, not just `value_at`."""
        rng = random.Random(500 + seed)
        c = random_curve(rng)
        cut = Fraction(rng.randint(1, 40), 8)
        for piece in (c.head(cut), c.tail(cut)):
            expr = piece.to_expr(2.0)
            for _ in range(20):
                local = rng.uniform(0, 6)
                assert evaluate(expr, t=2.0 + local) == pytest.approx(piece.value_at(local), abs=1e-5)

    def test_time_scaled_speeds_up_the_curve(self):
        c = curve((0, 0), (4, 100), easing=Easing.EASE_IN)
        fast = c.time_scaled(Fraction(1, 2))
        for x in (0.3, 1.0, 1.9):
            assert fast.value_at(x) == pytest.approx(c.value_at(x * 2), abs=1e-9)
        with pytest.raises(ValueError):
            c.time_scaled(0)


# --------------------------------------------------------------------------- serialization
class TestSerialization:
    def test_json_round_trip_of_a_curve_preserves_everything(self):
        c = curve((0, 0, Easing.EASE_IN_OUT), (Fraction(1, 3), 50, Easing.HOLD), (2, 100)).tail(
            Fraction(1, 7)
        )
        again = PropertyCurve.model_validate_json(c.model_dump_json())
        assert again == c
        assert [k.time.value for k in again.keyframes] == [
            k.time.value for k in c.keyframes
        ]  # exact Fractions

    def test_json_round_trip_of_a_clip_with_keyframes(self):
        clip = MediaClip(
            source=Source(source="x.mp4"),
            duration=Time(3),
            keyframes={
                "opacity": curve((0, 0), (1, 100), easing=Easing.EASE_OUT),
                "position.x": curve((0, -200), (3, 200)),
            },
        )
        again = MediaClip.model_validate_json(clip.model_dump_json())
        assert again == clip
        assert again.keyframes["opacity"].keyframes[0].easing == Easing.EASE_OUT

    def test_clip_from_plain_dicts(self):
        clip = MediaClip.model_validate(
            {
                "source": "x.mp4",
                "duration": {"numerator": 2, "denominator": 1},
                "keyframes": {
                    "scale": {
                        "keyframes": [
                            {"time": {"numerator": 0, "denominator": 1}, "value": 0.5},
                            {"time": {"numerator": 1, "denominator": 1}, "value": 1.0},
                        ]
                    }
                },
            }
        )
        assert clip.keyframes["scale"].value_at(0.5) == pytest.approx(0.75)

    def test_a_timeline_with_keyed_clips_round_trips(self):
        tl = Timeline()
        tl.add_clip(
            MediaClip(
                id="a",
                source=Source(source="x.mp4"),
                duration=Time(2),
                keyframes={"opacity": curve((0, 0), (2, 100))},
            )
        )
        again = Timeline.model_validate_json(tl.model_dump_json())
        _, clip = again.get_clip("a")
        assert clip.keyframes["opacity"].value_at(1) == pytest.approx(50)

    def test_transform_at_resolves_keyed_properties_and_keeps_static_ones(self):
        clip = MediaClip(
            source=Source(source="x.mp4"),
            duration=Time(2),
            transform=Transform(scale=0.8, rotation=15),
            keyframes={"opacity": curve((0, 0), (2, 100)), "position.x": curve((0, 0), (2, 200))},
        )
        t = clip.transform_at(1)
        assert t.opacity == 50 and t.position.x == pytest.approx(100)
        assert t.scale == 0.8 and t.rotation == 15  # unkeyed: static values pass through


# --------------------------------------------------------------------------- timeline split / trim
def keyed_clip(**kw) -> MediaClip:
    return MediaClip(
        id="k",
        source=kw.pop("source", Source(source="x.mp4")),
        timeline_start=Time(1),
        duration=Time(4),
        keyframes=kw.pop(
            "keyframes",
            {
                "opacity": curve((0, 0), (4, 100)),
                "position.x": curve((0, -100, Easing.EASE_IN_OUT), (2, 100, Easing.EASE_OUT), (4, 0)),
            },
        ),
        **kw,
    )


def add(clip) -> tuple[Timeline, MediaClip]:
    tl = Timeline()
    tl.add_clip(clip)
    return tl, clip


class TestTimelineSplitAndTrim:
    def test_split_halves_reproduce_the_original_curve_at_the_same_timeline_moment(self):
        tl, orig = add(keyed_clip())
        original = {n: c.model_copy(deep=True) for n, c in orig.keyframes.items()}
        first, second = tl.split_clip("k", Time(2.5))  # 1.5s into the clip -- inside the first eased segment
        assert first.timeline_start == Time(1) and second.timeline_start == Time(2.5)
        rng = random.Random(3)
        for _ in range(100):
            local = rng.uniform(0, 4)
            for name, curve_ in original.items():
                if local <= 1.5:
                    assert first.keyframes[name].value_at(local) == pytest.approx(
                        curve_.value_at(local), abs=1e-9
                    )
                else:
                    assert second.keyframes[name].value_at(local - 1.5) == pytest.approx(
                        curve_.value_at(local), abs=1e-9
                    )

    def test_both_halves_satisfy_the_clip_invariant_keyframes_within_duration(self):
        tl, _ = add(keyed_clip())
        first, second = tl.split_clip("k", Time(2.5))
        for half in (first, second):
            for c in half.keyframes.values():
                assert c.end_time <= half.duration

    def test_split_is_independent_of_speed(self):
        """D1: keyframe time is timeline time, so speed=2 changes source offset but not the split maths."""
        tl, _ = add(keyed_clip(speed=2.0))
        first, second = tl.split_clip("k", Time(2.5))
        assert second.keyframes["opacity"].value_at(0) == pytest.approx(37.5)  # 1.5s of 4s, linear 0-100
        assert second.source.start == Time(3)  # 1.5s * speed 2

    def test_split_of_a_clip_without_keyframes_is_unchanged(self):
        tl, _ = add(MediaClip(id="p", source=Source(source="x.mp4"), duration=Time(4)))
        first, second = tl.split_clip("p", Time(2))
        assert first.keyframes == {} and second.keyframes == {}

    def test_rejected_split_leaves_keyframes_untouched(self):
        tl, orig = add(keyed_clip())
        before = orig.model_dump_json()
        with pytest.raises(InvalidSplitError):
            tl.split_clip("k", Time(9))
        assert orig.model_dump_json() == before

    def test_trim_in_rebases_keyframes_and_stays_continuous(self):
        tl, orig = add(keyed_clip())
        original = orig.keyframes["position.x"].model_copy(deep=True)
        tl.trim_in("k", Time(2))  # drop the first second
        assert orig.timeline_start == Time(2) and orig.duration == Time(3)
        for local in (0, 0.3, 1, 2.2, 3):
            assert orig.keyframes["position.x"].value_at(local) == pytest.approx(
                original.value_at(local + 1), abs=1e-9
            )

    def test_trim_in_can_reveal_preroll_which_holds_the_first_value(self):
        tl, orig = add(
            keyed_clip(source=Source(source="x.mp4", start=Time(2)))
        )  # footage exists before the in-point
        tl.trim_in("k", Time(0.5))  # pull the head back 0.5s
        assert orig.duration == Time(4.5)
        assert orig.keyframes["opacity"].value_at(0) == 0
        assert orig.keyframes["opacity"].value_at(0.5) == pytest.approx(0)
        assert orig.keyframes["opacity"].value_at(2.5) == pytest.approx(50)

    def test_trim_out_cuts_keyframes_and_stays_continuous(self):
        tl, orig = add(keyed_clip())
        original = orig.keyframes["position.x"].model_copy(deep=True)
        tl.trim_out("k", Time(3))  # clip now 2s long
        assert orig.duration == Time(2)
        for local in (0, 0.7, 1.4, 2):
            assert orig.keyframes["position.x"].value_at(local) == pytest.approx(
                original.value_at(local), abs=1e-9
            )
        assert all(c.end_time <= Time(2) for c in orig.keyframes.values())

    def test_trim_out_can_extend_and_holds_the_last_value(self):
        tl, orig = add(keyed_clip())
        tl.trim_out("k", Time(7))
        assert orig.duration == Time(6)
        assert orig.keyframes["opacity"].value_at(5.9) == pytest.approx(100)

    def test_duplicate_keeps_keyframes(self):
        tl, orig = add(keyed_clip())
        track = tl.video_tracks[0]
        dup = track.duplicate_clip("k")
        assert dup.keyframes == orig.keyframes and dup.keyframes is not orig.keyframes

    def test_timeline_level_split_and_trim_wrappers_also_rebase(self):
        tl, _ = add(keyed_clip())
        _, second = tl.split_clip("k", Time(3))
        assert second.keyframes["opacity"].value_at(0) == pytest.approx(50)


# --------------------------------------------------------------------------- compound clips
class TestCompoundClipKeyframes:
    """Handoff D4: an animated child keeps its animation when a compound is flattened."""

    @staticmethod
    def _flatten(*, speed=1.0, transform=None, child_dur=4, comp_dur=4):
        from visualkit.models import CompoundClip

        inner = Timeline()
        inner.add_clip(
            MediaClip(
                id="kid",
                source=Source(source="x.mp4"),
                duration=Time(child_dur),
                keyframes={"position.x": PropertyCurve.from_points([(0, 0), (2, 100)])},
            )
        )
        comp = CompoundClip(
            id="comp",
            duration=Time(comp_dur),
            speed=speed,
            inner_timeline=inner,
            **({"transform": transform} if transform else {}),
        )
        root = Timeline()
        root.add_clip(comp)
        return root.flatten().video_tracks[0].clips[0]

    def test_animation_survives_flattening(self):
        clip = self._flatten()
        assert clip.keyframes["position.x"].value_at(1) == pytest.approx(50)

    def test_faster_compound_retimes_the_animation(self):
        # At 2x the child's 2s move plays in 1 timeline second.
        clip = self._flatten(speed=2.0, comp_dur=2)
        assert clip.keyframes["position.x"].value_at(0.5) == pytest.approx(50)
        assert clip.keyframes["position.x"].value_at(1) == pytest.approx(100)

    def test_animated_child_under_a_transformed_compound_is_refused_not_miscomposed(self):
        with pytest.raises(NotImplementedError, match="animated"):
            self._flatten(transform=Transform(scale=0.5))


class TestCompoundClipOtherEffectsSurviveFlattening(TestCompoundClipKeyframes):
    """`chroma_key`, `mask` and `animation` ride along through `to_media_clip`/flatten just like
    `keyframes` do (see `TestCompoundClipKeyframes` above); `animation` shares the keyframe
    guard against a transformed parent, since it compiles to the exact same kind of curve.
    """

    @staticmethod
    def _flatten_with(child_extra: dict, *, transform=None):
        from visualkit.models import CompoundClip
        from visualkit.models.clips.coded_visual import CodedVisualClip

        inner = Timeline()
        inner.add_clip(MediaClip(id="kid", source=Source(source="x.mp4"), duration=Time(4), **child_extra))
        comp = CompoundClip(
            id="comp",
            duration=Time(4),
            inner_timeline=inner,
            **({"transform": transform} if transform else {}),
        )
        root = Timeline()
        root.add_clip(comp)
        return root.flatten().video_tracks[0].clips[0]

    def test_chroma_key_survives(self):
        from visualkit.models.effects import ChromaKey

        clip = self._flatten_with({"chroma_key": ChromaKey(color="#0000ff")}, transform=Transform(scale=0.5))
        assert clip.chroma_key.color == "#0000FF"

    def test_mask_survives(self):
        from visualkit.models.effects import Mask

        clip = self._flatten_with({"mask": Mask(shape="ellipse", width=0.3)}, transform=Transform(scale=0.5))
        assert clip.mask.shape == "ellipse" and clip.mask.width == 0.3

    def test_unopposed_animation_survives(self):
        from visualkit.models.animation import ClipAnimation

        clip = self._flatten_with({"animation": ClipAnimation(in_preset="fade")})
        assert clip.effective_keyframes()["opacity"].value_at(0) == 0

    def test_animation_under_a_transformed_parent_is_refused_like_keyframes(self):
        from visualkit.models.animation import ClipAnimation

        with pytest.raises(NotImplementedError, match="animated"):
            self._flatten_with({"animation": ClipAnimation(in_preset="fade")}, transform=Transform(scale=0.5))
