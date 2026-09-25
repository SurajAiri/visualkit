"""TextStyle growth (outline, shadow, letter spacing, line height, gradient).

Most of it is CSS, so the pure tests check the generated HTML and the validators, and the
pixel tests (Chrome) prove each feature actually paints something: a CSS property that a font
fallback or a browser quirk silently drops would otherwise look fine in the HTML.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from visualkit.coded_visual import browser
from visualkit.exporters.video import FFmpegVideoExporter
from visualkit.models import TextClip, TextStyle, Timeline
from visualkit.models.clips.text import TextGradient
from visualkit.utils.time import Time

needs_chrome = pytest.mark.skipif(browser.find_chrome() is None, reason="no Chrome/Chromium available")

W, H = 640, 360  # reference scale is 1/3, so font_size=300 -> 100 px glyphs


def _clip(text="MM", **style) -> TextClip:
    return TextClip(
        id="t",
        text=text,
        duration=Time(1),
        style=TextStyle(font_size=300, color="#ffffff", **style),
    )


def _html(clip: TextClip) -> str:
    return FFmpegVideoExporter._text_html(clip, W, H)


def _render(tmp_path: Path, clip: TextClip) -> np.ndarray:
    exporter = FFmpegVideoExporter(cache_dir=tmp_path / "cache")
    return np.array(Image.open(exporter._render_text_to_image(clip, W, H)).convert("RGBA")).astype(int)


def _bbox(rgba: np.ndarray, min_alpha=64):
    ys, xs = np.where(rgba[:, :, 3] >= min_alpha)
    assert len(xs), "nothing was painted"
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


# --------------------------------------------------------------------------- model / html
class TestModel:
    def test_defaults_change_nothing_in_the_generated_html(self):
        html = _html(_clip())
        for absent in ("letter-spacing", "text-stroke", "text-shadow", "drop-shadow", "linear-gradient"):
            assert absent not in html
        assert "line-height:1.2;" in html

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"stroke_color": "red;background:url(x)"},
            {"shadow_color": "red}body{display:none"},
            {"shadow_color": "<script>"},
            {"stroke_width": -1},
            {"shadow_blur": -1},
            {"line_height": 0},
            {"letter_spacing": 1000},
        ],
    )
    def test_invalid_values_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            TextStyle(**kwargs)

    @pytest.mark.parametrize("bad", ["red;x:y", "rgb(1,2,3)}", "<b>"])
    def test_gradient_colours_are_validated_like_the_text_colour(self, bad):
        with pytest.raises(ValidationError):
            TextGradient(start_color=bad, end_color="#fff")
        with pytest.raises(ValidationError):
            TextGradient(start_color="#fff", end_color=bad)

    def test_unknown_style_field_is_still_rejected(self):
        with pytest.raises(ValidationError):
            TextStyle(stroke_colour="#fff")  # type: ignore[call-arg]

    def test_style_round_trips_through_json(self):
        style = TextStyle(
            stroke_width=4,
            stroke_color="#ff0000",
            shadow_color="#000000",
            shadow_offset_x=3,
            shadow_offset_y=-2,
            shadow_blur=8,
            letter_spacing=2.5,
            line_height=1.5,
            gradient=TextGradient(start_color="#f00", end_color="#00f", angle=45),
        )
        assert TextStyle.model_validate_json(style.model_dump_json()) == style


class TestHtml:
    def test_lengths_scale_with_the_frame_like_the_font_size(self):
        clip = _clip(stroke_width=6, shadow_color="#000", shadow_offset_x=9, shadow_blur=12, letter_spacing=3)
        small = FFmpegVideoExporter._text_html(clip, 640, 360)  # 1/3 of the reference
        full = FFmpegVideoExporter._text_html(clip, 1920, 1080)
        assert "letter-spacing:1px" in small and "letter-spacing:3px" in full
        assert "text-shadow:3px 0 4px #000" in small and "text-shadow:9px 0 12px #000" in full
        assert "-webkit-text-stroke:4px" in small and "-webkit-text-stroke:12px" in full

    def test_gradient_shadow_uses_drop_shadow_not_text_shadow(self):
        html = _html(_clip(shadow_color="#000", gradient=TextGradient(start_color="#f00", end_color="#00f")))
        assert "drop-shadow(" in html and "text-shadow" not in html
        assert "linear-gradient(180deg,#f00,#00f)" in html

    def test_user_text_is_still_escaped(self):
        assert "<script>" not in _html(_clip("<script>alert(1)</script>", stroke_width=2))


@needs_chrome
class TestCacheDistinguishesNewFields:
    @pytest.mark.parametrize(
        "field, value",
        [
            ("stroke_width", 5.0),
            ("stroke_color", "#ff0000"),
            ("shadow_color", "#000000"),
            ("shadow_offset_x", 5.0),
            ("letter_spacing", 5.0),
            ("line_height", 2.0),
            ("gradient", TextGradient(start_color="#f00", end_color="#00f")),
        ],
    )
    def test_styles_differing_in_one_new_field_render_to_different_files(self, tmp_path, field, value):
        # stroke_color/shadow_offset only matter alongside their partner field, so start from a
        # style where the field under test is meaningful.
        base = {"stroke_width": 3.0, "shadow_color": "#111111", "shadow_offset_x": 1.0}
        exporter = FFmpegVideoExporter(cache_dir=tmp_path / "cache")
        a = exporter._render_text_to_image(_clip(**base), W, H)
        b = exporter._render_text_to_image(_clip(**{**base, field: value}), W, H)
        assert a != b


# --------------------------------------------------------------------------- pixels
@needs_chrome
class TestPixels:
    def test_plain_text_paints_glyphs(self, tmp_path):
        rgba = _render(tmp_path, _clip())
        x0, y0, x1, y1 = _bbox(rgba)
        assert (x1 - x0) > 80 and (y1 - y0) > 40

    def test_stroke_paints_an_outline_outside_the_glyphs(self, tmp_path):
        plain = _bbox(_render(tmp_path, _clip()))
        rgba = _render(tmp_path, _clip(stroke_width=12, stroke_color="#ff0000"))
        outlined = _bbox(rgba)
        # 12 reference px = 4 px on this canvas, on each side.
        assert plain[0] - outlined[0] == pytest.approx(4, abs=2)
        assert outlined[2] - plain[2] == pytest.approx(4, abs=2)
        assert outlined[1] < plain[1] and outlined[3] > plain[3]
        red = (rgba[:, :, 0] > 200) & (rgba[:, :, 1] < 60) & (rgba[:, :, 3] > 200)
        assert red.sum() > 200
        # ...and the glyph itself stays white on top of the outline.
        white = (rgba[:, :, :3] > 240).all(axis=2) & (rgba[:, :, 3] > 240)
        assert white.sum() > 500

    def test_shadow_is_offset_by_the_requested_amount(self, tmp_path):
        plain = _bbox(_render(tmp_path, _clip()))
        rgba = _render(tmp_path, _clip(shadow_color="#0000ff", shadow_offset_x=60, shadow_offset_y=30))
        shadowed = _bbox(rgba)
        assert shadowed[0] == pytest.approx(plain[0], abs=2)  # left edge unchanged
        assert shadowed[2] - plain[2] == pytest.approx(20, abs=3)  # 60 ref px -> 20 px right
        assert shadowed[3] - plain[3] == pytest.approx(10, abs=3)  # 30 ref px -> 10 px down
        blue = (rgba[:, :, 2] > 200) & (rgba[:, :, 0] < 60) & (rgba[:, :, 3] > 200)
        assert blue.sum() > 200

    def test_shadow_blur_softens_the_edge(self, tmp_path):
        hard = _render(tmp_path, _clip(shadow_color="#0000ff", shadow_offset_x=60))
        soft = _render(tmp_path, _clip(shadow_color="#0000ff", shadow_offset_x=60, shadow_blur=45))
        partial = lambda a: int(((a[:, :, 3] > 10) & (a[:, :, 3] < 245)).sum())  # noqa: E731
        assert partial(soft) > partial(hard) * 2

    def test_letter_spacing_widens_the_text(self, tmp_path):
        """Also the 'glyphs must actually appear' check: this property once rendered an empty row."""
        plain = _bbox(_render(tmp_path, _clip("MMMM")))
        spaced_rgba = _render(tmp_path, _clip("MMMM", letter_spacing=60))  # 20 px
        spaced = _bbox(spaced_rgba)
        assert (spaced_rgba[:, :, 3] > 200).sum() > 500, "text vanished"
        # 3 gaps between 4 letters (the trailing one is empty space).
        assert (spaced[2] - spaced[0]) - (plain[2] - plain[0]) == pytest.approx(60, abs=10)

    def test_line_height_spreads_wrapped_lines(self, tmp_path):
        text = "M" * 22 + " " + "M" * 22  # wraps into two lines at 40 columns
        loose = _bbox(
            _render(
                tmp_path,
                TextClip(id="t", text=text, duration=Time(1), style=TextStyle(font_size=60, line_height=3.0)),
            )
        )
        tight = _bbox(
            _render(
                tmp_path,
                TextClip(id="t", text=text, duration=Time(1), style=TextStyle(font_size=60, line_height=1.0)),
            )
        )
        # font 60 -> 20 px; the two baselines move 2 * 20 = 40 px further apart.
        assert (loose[3] - loose[1]) - (tight[3] - tight[1]) == pytest.approx(40, abs=6)

    def test_gradient_runs_top_to_bottom(self, tmp_path):
        rgba = _render(tmp_path, _clip(gradient=TextGradient(start_color="#ff0000", end_color="#0000ff")))
        x0, y0, x1, y1 = _bbox(rgba)
        solid = rgba[:, :, 3] > 250
        top = rgba[y0 : y0 + 10][solid[y0 : y0 + 10]]
        bottom = rgba[y1 - 10 : y1][solid[y1 - 10 : y1]]
        assert top[:, 0].mean() > top[:, 2].mean() + 100  # red at the top
        assert bottom[:, 2].mean() > bottom[:, 0].mean() + 100  # blue at the bottom

    def test_gradient_horizontal_angle(self, tmp_path):
        rgba = _render(
            tmp_path, _clip(gradient=TextGradient(start_color="#ff0000", end_color="#0000ff", angle=90))
        )
        x0, y0, x1, y1 = _bbox(rgba)
        solid = rgba[:, :, 3] > 250
        left = rgba[:, x0 : x0 + 12][solid[:, x0 : x0 + 12]]
        right = rgba[:, x1 - 12 : x1][solid[:, x1 - 12 : x1]]
        assert left[:, 0].mean() > left[:, 2].mean() + 80
        assert right[:, 2].mean() > right[:, 0].mean() + 80

    def test_shadow_does_not_cover_a_gradient_fill(self, tmp_path):
        """`text-shadow` under clipped-background text paints over the fill; drop-shadow must not."""
        rgba = _render(
            tmp_path,
            _clip(shadow_color="#000000", gradient=TextGradient(start_color="#ff0000", end_color="#ff0000")),
        )
        solid = rgba[:, :, 3] > 250
        assert (rgba[:, :, 0][solid] > 200).mean() > 0.9  # still red, not smothered in black


# --------------------------------------------------------------------------- other consumers
class TestOtherConsumers:
    def test_resolve_export_ignores_the_new_fields_without_crashing(self, tmp_path):
        timeline = Timeline()
        timeline.add_clip(
            _clip(
                stroke_width=3,
                shadow_color="#000000",
                letter_spacing=2,
                line_height=1.4,
                gradient=TextGradient(start_color="#f00", end_color="#00f"),
            )
        )
        out = timeline.export_to_resolve(tmp_path / "t.xml")
        assert Path(out).exists()
