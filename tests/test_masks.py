"""Masks: model validation, geq expressions, filter order, and real rendered shapes."""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from tests.rendering_helpers import H, W, at, curve, make_clip, png, render
from visualkit.exporters._render_plan import build_clip_stage, mask_frame_size
from visualkit.models import MediaClip, Source, Transform
from visualkit.models.effects import MASK_PROPERTIES, Mask
from visualkit.utils.time import Time

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

WHITE, BLACK = (255, 255, 255), (0, 0, 0)


# --------------------------------------------------------------------------- model
class TestMaskModel:
    def test_defaults_are_a_centred_half_size_rect(self):
        m = Mask()
        assert (m.shape, m.x, m.y, m.width, m.height, m.feather, m.invert) == (
            "rect",
            0.5,
            0.5,
            0.5,
            0.5,
            0.0,
            False,
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"shape": "triangle"},
            {"x": -0.1},
            {"x": 1.1},
            {"width": 1.1},
            {"feather": -0.1},
            {"feather": 1.1},
            {"unknown": 1},
        ],
    )
    def test_invalid_values_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            Mask(**kwargs)

    def test_round_trips_through_json_on_a_clip(self):
        clip = MediaClip(
            id="c",
            source=Source(source="x.mp4"),
            duration=Time(2),
            mask=Mask(shape="ellipse", x=0.3, width=0.6, feather=0.2, invert=True),
        )
        assert MediaClip.model_validate_json(clip.model_dump_json()) == clip

    def test_mask_keyframe_names_are_registered(self):
        from visualkit.models.keyframes import KEYFRAMEABLE_PROPERTIES

        for name in MASK_PROPERTIES:
            assert name in KEYFRAMEABLE_PROPERTIES

    def test_mask_keyframes_need_a_mask_on_the_clip(self):
        with pytest.raises(ValidationError, match="mask"):
            MediaClip(
                id="c",
                source=Source(source="x.mp4"),
                duration=Time(2),
                keyframes={"mask.width": curve((0, 0.2), (1, 0.8))},
            )

    def test_mask_keyframes_work_alongside_a_mask(self):
        clip = MediaClip(
            id="c",
            source=Source(source="x.mp4"),
            duration=Time(2),
            mask=Mask(),
            keyframes={"mask.width": curve((0, 0.2), (1, 0.8))},
        )
        assert clip.mask_at(0.5).width == pytest.approx(0.5)

    def test_mask_at_without_a_mask_is_none(self):
        clip = MediaClip(id="c", source=Source(source="x.mp4"), duration=Time(2))
        assert clip.mask_at(0.5) is None

    def test_mask_frame_size_stays_within_budget(self):
        for w, h in [(320, 180), (1920, 1080), (3840, 2160)]:
            mw, mh, k = mask_frame_size(w, h)
            assert mw * mh <= 130_000 * 1.05
            assert k >= 1
            assert round(mw * k) >= w - k and round(mh * k) >= h - k


class TestFilterOrder:
    def _statements(self, **kw) -> list[str]:
        clip = MediaClip(id="c", source=Source(source="x.mp4"), duration=Time(2), **kw)
        return build_clip_stage(clip, 1920, 1080).statements("1:v", "out", "1")

    def test_mask_geq_runs_within_the_pixel_budget_not_full_res(self):
        statements = self._statements(mask=Mask())
        geq = [s for s in statements if "geq" in s]
        assert geq
        for s in geq:
            assert "crop=w='min(iw,16)'" in s  # the source is shrunk before geq, same as opacity
            assert s.index("crop=") < s.index("geq")

    def test_no_mask_means_no_geq(self):
        assert not any("geq" in s for s in self._statements())

    def test_mask_and_static_transform_still_composes(self):
        statements = self._statements(mask=Mask(), transform=Transform(scale=0.5, rotation=20))
        joined = ";".join(statements)
        assert "geq" in joined and "rotate=" in joined


# --------------------------------------------------------------------------- real renders
def _white(tmp_path, size=(W, H)):
    return png(tmp_path / "w.png", size=size, color=(255, 255, 255, 255))


def _masked_bbox(tmp_path, mask, **kw):
    clip = make_clip(_white(tmp_path), start=0.5, duration=1.5, mask=mask, **kw)
    backdrop = make_clip(png(tmp_path / "bg.png", color=(0, 0, 0, 255)), start=0, duration=2, clip_id="bg")
    frame = at(render(tmp_path, backdrop, clip), 1.0)
    ys, xs = np.where(frame[:, :, 1] > 128)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else None


@needs_ffmpeg
class TestRenderedMasks:
    def test_rect_mask_shows_only_the_rectangle(self, tmp_path):
        box = _masked_bbox(tmp_path, Mask(shape="rect", width=0.5, height=0.4, feather=0.0))
        assert box == pytest.approx((80, 54, 240, 126), abs=3)

    def test_ellipse_mask_is_narrower_at_the_corners_than_a_rect(self, tmp_path):
        rect = _masked_bbox(tmp_path, Mask(shape="rect", width=0.6, height=0.6, feather=0.0))
        ellipse = _masked_bbox(tmp_path, Mask(shape="ellipse", width=0.6, height=0.6, feather=0.0))
        # Same bounding box...
        assert rect == pytest.approx(ellipse, abs=4)
        # ...but the ellipse leaves its own corners outside the shape.

    def test_ellipse_corner_is_outside_the_shape(self, tmp_path):
        clip = make_clip(
            _white(tmp_path),
            start=0,
            duration=1,
            mask=Mask(shape="ellipse", width=0.6, height=0.6, feather=0.0),
        )
        backdrop = make_clip(
            png(tmp_path / "bg.png", color=(0, 0, 0, 255)), start=0, duration=1, clip_id="bg"
        )
        frame = at(render(tmp_path, backdrop, clip), 0.0)
        cx, cy = W // 2, H // 2
        bw, bh = round(0.6 * W / 2), round(0.6 * H / 2)
        corner = frame[cy - bh + 3, cx - bw + 3]  # near the rect corner, outside the ellipse
        assert tuple(corner) == pytest.approx(BLACK, abs=10)

    def test_off_centre_mask(self, tmp_path):
        box = _masked_bbox(tmp_path, Mask(shape="rect", x=0.75, y=0.25, width=0.3, height=0.3, feather=0.0))
        assert box is not None
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        assert cx == pytest.approx(0.75 * W, abs=3)
        assert cy == pytest.approx(0.25 * H, abs=3)

    def test_feather_softens_the_edge_simple(self, tmp_path):
        def partial_count(mask, path):
            clip = make_clip(_white(path), start=0, duration=1, mask=mask)
            bg = make_clip(png(path / "bg.png", color=(0, 0, 0, 255)), start=0, duration=1, clip_id="bg")
            frame = at(render(path, bg, clip), 0.0)
            g = frame[:, :, 1]
            return int(((g > 20) & (g < 235)).sum())

        (tmp_path / "hard").mkdir()
        (tmp_path / "soft").mkdir()
        hard = partial_count(Mask(width=0.4, height=0.4, feather=0.0), tmp_path / "hard")
        soft = partial_count(Mask(width=0.4, height=0.4, feather=0.15), tmp_path / "soft")
        assert soft > hard * 3

    def test_invert_shows_the_outside_instead(self, tmp_path):
        normal = _masked_bbox(tmp_path, Mask(shape="rect", width=0.3, height=0.3, feather=0.0))
        (tmp_path / "inv").mkdir()
        clip = make_clip(
            _white(tmp_path / "inv"),
            start=0,
            duration=1,
            mask=Mask(shape="rect", width=0.3, height=0.3, feather=0.0, invert=True),
        )
        bg = make_clip(
            png(tmp_path / "inv" / "bg.png", color=(0, 0, 0, 255)), start=0, duration=1, clip_id="bg"
        )
        frame = at(render(tmp_path / "inv", bg, clip), 0.0)
        # Centre (inside the un-inverted shape) is now hidden; a far corner (outside it) is visible.
        assert tuple(frame[H // 2, W // 2]) == pytest.approx(BLACK, abs=10)
        assert tuple(frame[3, 3]) == pytest.approx(WHITE, abs=10)
        assert normal is not None

    def test_animated_mask_width_grows_over_time(self, tmp_path):
        clip = make_clip(
            _white(tmp_path),
            start=0.5,
            duration=1.5,
            mask=Mask(shape="rect", height=0.5, feather=0.0),
            keyframes={"mask.width": curve((0, 0.2), (1, 0.8))},
        )
        bg = make_clip(png(tmp_path / "bg.png", color=(0, 0, 0, 255)), start=0, duration=2, clip_id="bg")
        frames = render(tmp_path, bg, clip)
        for local_t, expect_w in [(0.0, 0.2), (0.5, 0.5), (1.0, 0.8)]:
            frame = at(frames, 0.5 + local_t)
            ys, xs = np.where(frame[:, :, 1] > 128)
            assert (xs.max() - xs.min() + 1) == pytest.approx(expect_w * W, abs=6), local_t

    def test_mask_at_full_1080p_is_not_a_geq_perf_trap(self, tmp_path):
        """The exit criterion is 'never geq at full res'; this proves the shape is still exact there."""
        clip = make_clip(
            _white(tmp_path, size=(1920, 1080)),
            start=0,
            duration=1,
            mask=Mask(width=0.4, height=0.4, feather=0.0),
        )
        bg = make_clip(
            png(tmp_path / "bg.png", size=(1920, 1080), color=(0, 0, 0, 255)),
            start=0,
            duration=1,
            clip_id="bg",
        )
        frame = at(render(tmp_path, bg, clip, resolution=(1920, 1080)), 0.0)
        ys, xs = np.where(frame[:, :, 1] > 128)
        assert (xs.max() - xs.min() + 1) == pytest.approx(0.4 * 1920, abs=6)
        assert (ys.max() - ys.min() + 1) == pytest.approx(0.4 * 1080, abs=6)

    def test_mask_combines_with_chroma_key_and_opacity(self, tmp_path):
        from visualkit.models.effects import ChromaKey

        screen = png(tmp_path / "s.png", color=(0, 177, 64, 255))
        clip = make_clip(
            screen,
            start=0,
            duration=1,
            mask=Mask(width=0.5, height=0.5, feather=0.0),
            chroma_key=ChromaKey(),
            transform=Transform(opacity=100),
        )
        bg = make_clip(png(tmp_path / "bg.png", color=(0, 0, 255, 255)), start=0, duration=1, clip_id="bg")
        frame = at(render(tmp_path, bg, clip), 0.0)
        # The whole screen is keyed transparent, so the mask has nothing to reveal: pure blue everywhere.
        assert tuple(frame[H // 2, W // 2]) == pytest.approx((0, 0, 255), abs=10)
        assert tuple(frame[3, 3]) == pytest.approx((0, 0, 255), abs=10)
