"""Regression tests for Time (NTSC / drop-frame / bad input) and Variable (typing / recursion)."""

import math
from fractions import Fraction

import pytest
from pydantic import ValidationError

from visualkit.models import Variable, VariableType
from visualkit.utils.exceptions import InvalidTimeError
from visualkit.utils.time import Time, is_drop_frame_rate, is_ntsc_rate, nominal_timebase

NTSC = Fraction(30000, 1001)


class TestBadInput:
    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_floats_raise_invalid_time_error(self, bad):
        with pytest.raises(InvalidTimeError):
            Time(bad)

    def test_bool_is_rejected(self):
        with pytest.raises(InvalidTimeError):
            Time(True)

    @pytest.mark.parametrize("bad", ["1/0", "abc", "1e400", "", "  "])
    def test_bad_strings_raise_invalid_time_error_not_raw_python_errors(self, bad):
        with pytest.raises(InvalidTimeError):
            Time(bad)
        with pytest.raises(InvalidTimeError):
            Time.from_seconds(bad)

    @pytest.mark.parametrize("fps", [0, -1, True])
    def test_bad_fps_rejected(self, fps):
        with pytest.raises(InvalidTimeError):
            Time.from_frames(5, fps)

    def test_from_frames_requires_int(self):
        with pytest.raises(InvalidTimeError):
            Time.from_frames(1.5, 30)


class TestNtscRates:
    @pytest.mark.parametrize("spelling", [29.97, 29.970, NTSC])
    def test_29_97_spellings_are_the_same_exact_rate(self, spelling):
        assert Time.from_frames(30000, spelling) == Time(Fraction(1001))

    def test_helpers(self):
        assert is_ntsc_rate(29.97) and is_ntsc_rate(23.976) and is_ntsc_rate(59.94)
        assert not is_ntsc_rate(30) and not is_ntsc_rate(25)
        assert nominal_timebase(29.97) == 30 and nominal_timebase(23.976) == 24 and nominal_timebase(25) == 25
        assert is_drop_frame_rate(29.97) and not is_drop_frame_rate(23.976) and not is_drop_frame_rate(30)

    def test_float_timecode_parse_no_longer_raises_type_error(self):
        assert Time.from_timecode("00:00:01:15", fps=29.97).to_frames(29.97) == 45


class TestDropFrame:
    def test_roundtrip_every_frame_in_two_hours(self):
        """216,000 frames: the DF label -> frame mapping must be a bijection."""
        for f in range(0, 2 * 3600 * 30):
            tc = Time.from_frames(f, NTSC).to_timecode(NTSC)
            assert Time.from_timecode(tc, NTSC).to_frames(NTSC) == f, (f, tc)

    def test_one_wall_clock_hour_is_labelled_01_00_00(self):
        assert Time.from_seconds(3600).to_timecode(NTSC) == "01:00:00;00"

    def test_non_drop_label_drifts_from_wall_clock(self):
        assert Time.from_seconds(3600).to_timecode(NTSC, drop_frame=False) == "00:59:56:12"

    def test_dropped_labels_are_rejected(self):
        with pytest.raises(InvalidTimeError, match="dropped"):
            Time.from_timecode("00:01:00;00", 29.97)
        Time.from_timecode("00:10:00;00", 29.97)  # every 10th minute keeps its frames 0/1

    def test_drop_frame_only_valid_at_29_97_and_59_94(self):
        with pytest.raises(InvalidTimeError):
            Time.from_timecode("00:00:01;00", 25)
        with pytest.raises(InvalidTimeError):
            Time.from_seconds(1).to_timecode(25, drop_frame=True)

    def test_frame_field_must_fit_the_timebase(self):
        with pytest.raises(InvalidTimeError):
            Time.from_timecode("00:00:00:30", 30)
        with pytest.raises(InvalidTimeError):
            Time.from_timecode("00:00:00:99", 30)

    @pytest.mark.parametrize("fps", [24, 25, 30, 50, 60])
    def test_non_drop_rates_roundtrip(self, fps):
        for f in range(0, 20000, 7):
            assert Time.from_timecode(Time.from_frames(f, fps).to_timecode(fps), fps).to_frames(fps) == f


class TestExactArithmetic:
    def test_tenth_plus_two_tenths_is_three_tenths(self):
        assert Time(0.1) + Time(0.2) == Time(0.3)

    def test_frame_rounding_is_exact_rational(self):
        assert Time(Fraction(1, 60)).to_frames(30) == 0  # half a frame -> banker's rounding to even
        assert Time(Fraction(3, 60)).to_frames(30) == 2


class TestVariableCoercion:
    def test_string_default_no_longer_recurses(self):
        assert Variable(name="n", default=5).default == "5"

    def test_number_from_string(self):
        assert Variable(name="n", type=VariableType.NUMBER, value="42").value == 42
        assert Variable(name="n", type=VariableType.NUMBER, value="4.5").value == 4.5

    @pytest.mark.parametrize("bad", ["abc", True, float("nan"), float("inf"), [1]])
    def test_invalid_numbers_rejected_not_silently_kept(self, bad):
        with pytest.raises(ValidationError):
            Variable(name="n", type=VariableType.NUMBER, value=bad)

    def test_assignment_is_recoerced_and_validated(self):
        v = Variable(name="n", type=VariableType.NUMBER, value=1)
        v.value = "7"
        assert v.value == 7
        with pytest.raises(ValueError):
            v.value = "xyz"
        assert v.value == 7  # a rejected assignment leaves the old value

    @pytest.mark.parametrize(
        "raw, expected",
        [("False", False), ("true", True), ("no", False), ("1", True), (0, False), (1, True), (False, False)],
    )
    def test_boolean_coercion(self, raw, expected):
        assert Variable(name="b", type=VariableType.BOOLEAN, value=raw).value is expected

    def test_boolean_rejects_nonsense(self):
        with pytest.raises(ValidationError):
            Variable(name="b", type=VariableType.BOOLEAN, value="maybe")

    @pytest.mark.parametrize(
        "ok", ["#3b82f6", "#fff", "#11223344", "rgb(1, 2, 3)", "hsl(120, 50%, 50%)", "red"]
    )
    def test_valid_colors(self, ok):
        assert Variable(name="c", type=VariableType.COLOR, value=ok).value == ok

    @pytest.mark.parametrize("bad", ["javascript:alert(1)", "red; } </style>", "#12", 5, "url(x)"])
    def test_colors_that_could_break_out_of_css_are_rejected(self, bad):
        with pytest.raises(ValidationError):
            Variable(name="c", type=VariableType.COLOR, value=bad)

    def test_asset_requires_non_empty_string(self):
        assert Variable(name="a", type=VariableType.ASSET, value=" logo.svg ").value == "logo.svg"
        for bad in (123, "", "   "):
            with pytest.raises(ValidationError):
                Variable(name="a", type=VariableType.ASSET, value=bad)

    def test_json_string_is_parsed_and_bad_json_rejected(self):
        assert Variable(name="j", type=VariableType.JSON, value='{"a": [1, 2]}').value == {"a": [1, 2]}
        with pytest.raises(ValidationError):
            Variable(name="j", type=VariableType.JSON, value="{bad")
        with pytest.raises(ValidationError):
            Variable(name="j", type=VariableType.JSON, value=object())

    def test_falsey_values_count_as_set_and_beat_the_default(self):
        assert Variable(name="n", type=VariableType.NUMBER, value=0, default=5).resolve_value() == 0
        v = Variable(name="b", type=VariableType.BOOLEAN, value=False)
        assert v.is_set and v.resolve_value() is False

    def test_json_roundtrip_preserves_type_and_value(self):
        v = Variable(name="n", type=VariableType.NUMBER, value=3, default=1)
        again = Variable.model_validate_json(v.model_dump_json())
        assert again.value == 3 and again.type == VariableType.NUMBER

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            Variable(name="")


class TestCodedVisualVariableInference:
    def test_bare_values_keep_their_type(self):
        from visualkit import CodedVisualClip

        clip = CodedVisualClip(source="x.html", variables={"n": 10, "on": True, "s": "hi", "cfg": {"a": 1}})
        assert clip.variables["n"].type == VariableType.NUMBER
        assert clip.variables["on"].type == VariableType.BOOLEAN
        assert clip.variables["s"].type == VariableType.STRING
        assert clip.variables["cfg"].type == VariableType.JSON

    def test_construction_does_not_mutate_the_callers_dict(self):
        from visualkit import CodedVisualClip

        data = {"source": "x.html", "variables": {"a": "b"}}
        CodedVisualClip.model_validate(data)
        assert data == {"source": "x.html", "variables": {"a": "b"}}


class TestTimeMagnitudeAndSpecVsValue:
    """Bugs found by writing the tests above."""

    @pytest.mark.parametrize("huge", ["1e400", 10**10, Fraction(10**12)])
    def test_absurdly_large_times_are_rejected_up_front(self, huge):
        """Fraction('1e400') is a valid exact number that used to be accepted, then blew up
        with OverflowError on .seconds / repr()."""
        with pytest.raises(InvalidTimeError, match="too large|finite"):
            Time(huge)

    def test_from_seconds_and_constructor_agree_on_huge_strings(self):
        with pytest.raises(InvalidTimeError):
            Time.from_seconds("1e400")

    def test_every_constructible_time_can_be_displayed(self):
        from visualkit.utils.time import MAX_TIME_SECONDS

        t = Time(MAX_TIME_SECONDS)
        assert isinstance(t.seconds, float) and repr(t) and str(t)

    def test_dict_valued_variable_is_data_not_a_spec(self):
        from visualkit import CodedVisualClip

        clip = CodedVisualClip(
            source="x.html", variables={"payload": {"a": 1}, "label_only": {"label": "x"}, "empty": {}}
        )
        assert clip.variables["payload"].type == VariableType.JSON
        assert clip.variables["payload"].value == {"a": 1}
        assert clip.variables["label_only"].value == {"label": "x"}
        assert clip.variables["empty"].value == {}

    def test_genuine_variable_spec_dict_is_still_recognised(self):
        from visualkit import CodedVisualClip

        clip = CodedVisualClip(
            source="x.html",
            variables={
                "count": {"type": "number", "value": "5", "label": "Count"},
                "tint": {"type": "color", "default": "#fff"},
            },
        )
        assert clip.variables["count"].value == 5 and clip.variables["count"].label == "Count"
        assert clip.variables["tint"].type == VariableType.COLOR
        assert clip.variables["tint"].default == "#fff"
