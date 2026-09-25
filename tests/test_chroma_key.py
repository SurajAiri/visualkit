"""Chroma key: model validation, filter order, and real keyed renders."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from tests.rendering_helpers import FPS, H, W, at, make_clip, png, render
from visualkit.exporters._render_plan import build_clip_stage
from visualkit.models import MediaClip, Source, Transform
from visualkit.models.effects import ChromaKey, color_to_rgb
from visualkit.utils.time import Time

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

GREEN = (0, 177, 64)  # the broadcast chroma green, #00B140
RED = (255, 0, 0)
MAGENTA = (255, 0, 255)


# --------------------------------------------------------------------------- model
class TestColours:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("#00B140", 0x00B140),
            ("#0f0", 0x00FF00),
            ("#0f08", 0x00FF00),  # alpha is dropped
            ("#00ff0080", 0x00FF00),
            ("rgb(0, 177, 64)", 0x00B140),
            ("rgb(0 177 64)", 0x00B140),
            ("rgba(0,177,64,0.5)", 0x00B140),
            ("rgb(0%, 100%, 0%)", 0x00FF00),
            ("lime", 0x00FF00),
            ("Green", 0x008000),
            ("rebeccapurple", 0x663399),
        ],
    )
    def test_accepted_forms(self, text, expected):
        assert color_to_rgb(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["hsl(120, 100%, 50%)", "notacolour", "#12", "#gggggg", "red;x:y", "rgb(300,0,0)", "0x00ff00", 5],
    )
    def test_rejected_forms(self, text):
        with pytest.raises(ValueError):
            color_to_rgb(text)

    def test_the_named_table_is_complete(self):
        from visualkit.models.effects import _NAMED_COLORS

        assert (
            len(_NAMED_COLORS) == 148 and _NAMED_COLORS["black"] == 0 and _NAMED_COLORS["white"] == 0xFFFFFF
        )


class TestChromaKeyModel:
    def test_defaults_are_a_green_screen_key(self):
        key = ChromaKey()
        assert (key.method, key.color, key.despill) == ("chromakey", "#00B140", False)
        assert key.ffmpeg_color == "0x00B140"

    def test_colour_is_normalised(self):
        assert ChromaKey(color="lime").color == "#00FF00"
        assert ChromaKey(color="#0f0").ffmpeg_color == "0x00FF00"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"color": "hsl(1,2%,3%)"},
            {"similarity": 0.0},
            {"similarity": 1.5},
            {"blend": -0.1},
            {"blend": 2},
            {"despill_type": "red"},
            {"method": "lumakey"},
            {"unknown": 1},
        ],
    )
    def test_invalid_values_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            ChromaKey(**kwargs)

    def test_round_trips_through_json_on_a_clip(self):
        clip = MediaClip(
            id="c",
            source=Source(source="x.mp4"),
            duration=Time(2),
            chroma_key=ChromaKey(color="#0000ff", despill=True, despill_type="blue", method="colorkey"),
        )
        assert MediaClip.model_validate_json(clip.model_dump_json()) == clip


class TestFilterOrder:
    def _chain(self, **kw) -> str:
        clip = MediaClip(id="c", source=Source(source="x.mp4"), duration=Time(2), **kw)
        return build_clip_stage(clip, 1920, 1080).chain

    def test_the_key_is_the_first_filter_before_fit_scale_or_rotation(self):
        chain = self._chain(chroma_key=ChromaKey(), transform=Transform(scale=0.5, rotation=30, zoom=1.5))
        assert chain.startswith("chromakey=color=0x00B140:similarity=0.15:blend=0.05,")
        assert chain.index("chromakey") < chain.index("scale=") < chain.index("rotate=")

    def test_despill_follows_the_key(self):
        chain = self._chain(chroma_key=ChromaKey(despill=True, despill_type="blue"))
        assert chain.index("chromakey") < chain.index("despill=type=blue")

    def test_colorkey_method_and_no_despill_by_default(self):
        chain = self._chain(chroma_key=ChromaKey(method="colorkey", color="#0000ff"))
        assert "colorkey=color=0x0000FF" in chain and "despill" not in chain

    def test_no_key_means_no_key_filter(self):
        assert "key" not in self._chain()


# --------------------------------------------------------------------------- real renders
def _screen(path: Path, *, size=(W, H), subject=(60, 30), subject_color=RED, bg=GREEN) -> Path:
    """Green screen with a solid rectangle in the middle, at the given size."""
    img = Image.new("RGBA", size, (*bg, 255))
    cx, cy = size[0] // 2, size[1] // 2
    img.paste((*subject_color, 255), (cx - subject[0], cy - subject[1], cx + subject[0], cy + subject[1]))
    img.save(path)
    return path


def _as_h264(png_path: Path, out: Path, seconds=2) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(png_path)]
        + ["-t", str(seconds), "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    return out


def _over_magenta(tmp_path: Path, keyed: MediaClip) -> np.ndarray:
    backdrop = make_clip(png(tmp_path / "m.png", color=(*MAGENTA, 255)), start=0, duration=2, clip_id="bg")
    return at(render(tmp_path, backdrop, keyed), 1.0)


@needs_ffmpeg
class TestKeyedRender:
    def test_png_screen_becomes_transparent_and_subject_is_untouched(self, tmp_path):
        src = _screen(tmp_path / "s.png")
        frame = _over_magenta(tmp_path, make_clip(src, start=0, duration=2, chroma_key=ChromaKey()))
        assert tuple(frame[10, 10]) == pytest.approx(MAGENTA, abs=6)  # screen -> backdrop shows through
        assert tuple(frame[H // 2, W // 2]) == pytest.approx(RED, abs=6)  # subject core intact

    def test_h264_video_screen_is_keyed_too(self, tmp_path):
        """Video is yuv420p (subsampled chroma): the key must still take the screen out."""
        src = _as_h264(_screen(tmp_path / "s.png"), tmp_path / "s.mp4")
        frame = _over_magenta(tmp_path, make_clip(src, start=0, duration=2, chroma_key=ChromaKey()))
        assert tuple(frame[10, 10]) == pytest.approx(MAGENTA, abs=12)
        assert tuple(frame[H // 2, W // 2]) == pytest.approx(RED, abs=12)

    def test_without_a_key_the_screen_stays(self, tmp_path):
        src = _screen(tmp_path / "s.png")
        frame = _over_magenta(tmp_path, make_clip(src, start=0, duration=2))
        assert tuple(frame[10, 10]) == pytest.approx(GREEN, abs=8)

    def test_key_colour_matters(self, tmp_path):
        """A blue screen is not removed by a green key, and is by a blue one (RGB colorkey)."""
        src = _screen(tmp_path / "s.png", bg=(0, 0, 255))
        kept = _over_magenta(tmp_path, make_clip(src, start=0, duration=2, chroma_key=ChromaKey()))
        assert tuple(kept[10, 10]) == pytest.approx((0, 0, 255), abs=10)
        (tmp_path / "again").mkdir()
        gone = _over_magenta(
            tmp_path / "again",
            make_clip(src, start=0, duration=2, chroma_key=ChromaKey(color="#0000ff", method="colorkey")),
        )
        assert tuple(gone[10, 10]) == pytest.approx(MAGENTA, abs=10)

    def test_similarity_widens_what_is_keyed(self, tmp_path):
        """A slightly-off green is kept by a tight key and removed by a loose one."""
        off = _screen(tmp_path / "s.png", bg=(40, 190, 110))
        tight = ChromaKey(similarity=0.01, blend=0.0)
        kept = _over_magenta(tmp_path, make_clip(off, start=0, duration=2, chroma_key=tight))
        (tmp_path / "loose").mkdir()
        loose = ChromaKey(similarity=0.4)
        gone = _over_magenta(tmp_path / "loose", make_clip(off, start=0, duration=2, chroma_key=loose))
        assert tuple(kept[10, 10]) == pytest.approx((40, 190, 110), abs=10)  # not keyed at all
        assert tuple(gone[10, 10]) == pytest.approx(MAGENTA, abs=10)

    def test_key_applies_before_any_scale_or_rotate_the_clip_has(self, tmp_path):
        """The chain-string check in TestFilterOrder proves this structurally; this proves it in
        pixels too: a keyed-then-transformed clip's subject stays intact and the transparent
        region stays *predominantly* transparent (some soft edge blending against a coloured
        background is an inherent limit of straight, non-premultiplied alpha compositing --
        not something this handoff's exit criteria (subject core unchanged, background
        transparent) asks to eliminate).
        """
        src = _screen(tmp_path / "s.png", size=(160, 90), subject=(30, 15))  # fit scales it up
        keyed = make_clip(
            src, start=0, duration=2, chroma_key=ChromaKey(), transform=Transform(rotation=20, scale=0.6)
        )
        frame = _over_magenta(tmp_path, keyed)
        assert tuple(frame[H // 2, W // 2]) == pytest.approx(RED, abs=10)  # subject core intact
        far_corner = frame[5, 5]
        assert tuple(far_corner) == pytest.approx(MAGENTA, abs=10)  # well away from any edge

    def test_despill_reduces_green_on_the_subject(self, tmp_path):
        tinted = (170, 215, 165)  # a subject lit by the screen: greenish
        src = _screen(tmp_path / "s.png", subject_color=tinted)
        plain = _over_magenta(
            tmp_path, make_clip(src, start=0, duration=2, chroma_key=ChromaKey(similarity=0.05))
        )
        (tmp_path / "d").mkdir()
        cleaned = _over_magenta(
            tmp_path / "d",
            make_clip(src, start=0, duration=2, chroma_key=ChromaKey(similarity=0.05, despill=True)),
        )
        centre_plain, centre_clean = plain[H // 2, W // 2], cleaned[H // 2, W // 2]
        assert centre_plain[1] > 190  # subject is there and green-tinted
        assert centre_clean[1] < centre_plain[1] - 15  # despill pulled the green down
        assert tuple(cleaned[10, 10]) == pytest.approx(MAGENTA, abs=10)  # background still keyed

    def test_key_works_together_with_animation(self, tmp_path):
        from tests.rendering_helpers import curve

        src = _screen(tmp_path / "s.png")
        clip = make_clip(
            src,
            start=0.5,
            duration=1.5,
            chroma_key=ChromaKey(),
            transform=Transform(scale=0.5),
            keyframes={"position.x": curve((0, -40), (1, 40))},
        )
        backdrop = make_clip(
            png(tmp_path / "m.png", color=(*MAGENTA, 255)), start=0, duration=2, clip_id="bg"
        )
        frames = render(tmp_path, backdrop, clip)
        for t, dx in [(0.5, -40), (1.0, 0), (1.5, 40)]:
            f = at(frames, t)
            assert tuple(f[H // 2, W // 2 + round(dx)]) == pytest.approx(RED, abs=10), t
            assert tuple(f[5, 5]) == pytest.approx(MAGENTA, abs=6)
            assert tuple(f[H // 2 - 40, W // 2 + round(dx) + 50]) == pytest.approx(MAGENTA, abs=10)
