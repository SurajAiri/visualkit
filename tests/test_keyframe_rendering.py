"""End-to-end checks that keyframed transforms really render the way `value_at()` says.

Everything here runs the real ffmpeg. Fixtures are *solid colours*, never `testsrc`:
`testsrc` has bright detail everywhere, which makes every geometric measurement ambiguous.
A white rectangle on black has exactly one bounding box, so position, size and centre can
be read straight off the decoded frames.

Every clip in this file that matters starts at a non-zero timeline time, because ffmpeg's
`t` is absolute timeline time and an expression that forgets to subtract the clip start is
only visible when the clip does not start at 0.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.rendering_helpers import FPS, H, W
from tests.rendering_helpers import at as _at
from tests.rendering_helpers import bbox as _bbox
from tests.rendering_helpers import centre as _centre
from tests.rendering_helpers import curve as _curve
from tests.rendering_helpers import make_clip as _make_clip
from tests.rendering_helpers import png as _png
from tests.rendering_helpers import render as _render_clips
from tests.rendering_helpers import size as _size
from visualkit.exporters._render_plan import build_clip_stage
from visualkit.exporters.video import FFmpegVideoExporter
from visualkit.models import MediaClip, Source, Timeline, Transform
from visualkit.models.keyframes import Easing, PropertyCurve
from visualkit.utils.exceptions import ExportError
from visualkit.utils.time import Time

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _clip(png: Path, *, start: float, duration: float, **kw) -> MediaClip:
    return _make_clip(png, start=start, duration=duration, **kw)


def _render(tmp_path: Path, clip: MediaClip, *, resolution=(W, H)) -> np.ndarray:
    return _render_clips(tmp_path, clip, resolution=resolution)


# --------------------------------------------------------------------------- position
class TestAnimatedPosition:
    def test_position_follows_the_curve_for_a_clip_that_starts_late(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=3.0,
            transform=Transform(scale=0.25),
            keyframes={"position.x": _curve((0, 0), (2, 100))},
        )
        frames = _render(tmp_path, clip)
        assert len(frames) == 40

        # Nothing before the clip starts.
        assert _bbox(_at(frames, 0.5)) is None
        # Local time 0 -> x 0, local 1 -> 50, local 2 -> 100, then it holds.
        for abs_t, expect_x in [(1.0, 0), (1.5, 25), (2.0, 50), (3.0, 100), (3.9, 100)]:
            cx, cy = _centre(_bbox(_at(frames, abs_t)))
            assert cx == pytest.approx(W / 2 + expect_x, abs=2), abs_t
            assert cy == pytest.approx(H / 2, abs=2), abs_t

    def test_y_and_x_can_be_animated_independently(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=0.5,
            duration=2.0,
            transform=Transform(scale=0.25, position={"x": -40, "y": 0}),
            keyframes={"position.y": _curve((0, -30), (1, 30))},
        )
        frames = _render(tmp_path, clip)
        for abs_t, expect_y in [(0.5, -30), (1.0, 0), (1.5, 30)]:
            cx, cy = _centre(_bbox(_at(frames, abs_t)))
            assert cx == pytest.approx(W / 2 - 40, abs=2)  # static x untouched
            assert cy == pytest.approx(H / 2 + expect_y, abs=2)

    def test_speed_does_not_change_when_keyframes_fire(self, tmp_path):
        """Handoff D1: keyframe time is clip-local timeline time, not source time."""
        for speed in (1.0, 2.0):
            clip = _clip(
                _png(tmp_path / "w.png"),
                start=1.0,
                duration=2.0,
                speed=speed,
                transform=Transform(scale=0.25),
                keyframes={"position.x": _curve((0, 0), (2, 100))},
            )
            frames = _render(tmp_path, clip)
            cx, _ = _centre(_bbox(_at(frames, 2.0)))
            assert cx == pytest.approx(W / 2 + 50, abs=2), f"speed={speed}"


# --------------------------------------------------------------------------- scale / rotation
class TestAnimatedScale:
    def test_size_follows_the_curve_and_stays_centred(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=2.0,
            keyframes={"scale": _curve((0, 0.25), (2, 0.75))},
        )
        frames = _render(tmp_path, clip)
        for local_t, s in [(0.0, 0.25), (0.5, 0.375), (1.0, 0.5), (1.9, 0.725)]:
            box = _bbox(_at(frames, 1.0 + local_t))
            assert _size(box) == pytest.approx((W * s, H * s), abs=3), local_t
            assert _centre(box) == pytest.approx((W / 2, H / 2), abs=1.5), local_t


class TestAnimatedRotation:
    def test_rotation_stays_centred_and_turns_the_box(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=2.0,
            transform=Transform(scale=0.5),
            keyframes={"rotation": _curve((0, 0), (2, 90))},
        )
        frames = _render(tmp_path, clip)
        # 160x90 box rotating: at 0deg it is 160x90, at 45deg the bbox is (160+90)/sqrt2 square.
        box0 = _bbox(_at(frames, 1.0))
        assert _size(box0) == pytest.approx((160, 90), abs=3)
        box45 = _bbox(_at(frames, 2.0))
        assert _size(box45) == pytest.approx((176.8, 176.8), abs=4)
        # 1.9s -> 85.5deg: almost portrait.
        box85 = _bbox(_at(frames, 2.9))
        assert box85[3] - box85[1] > box85[2] - box85[0]
        for t in (1.0, 1.5, 2.0, 2.5, 2.9):
            assert _centre(_bbox(_at(frames, t))) == pytest.approx((W / 2, H / 2), abs=1.5), t

    def test_scale_and_rotation_animated_together(self, tmp_path):
        """`scale eval=frame` followed by `rotate` used to freeze the rotate box at the first size."""
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=2.0,
            keyframes={"scale": _curve((0, 0.25), (2, 0.5)), "rotation": _curve((0, 0), (2, 0))},
        )
        frames = _render(tmp_path, clip)
        for local_t, s in [(0.0, 0.25), (1.0, 0.375), (1.9, 0.4875)]:
            box = _bbox(_at(frames, 1.0 + local_t))
            assert _size(box) == pytest.approx((W * s, H * s), abs=3), local_t
            assert _centre(box) == pytest.approx((W / 2, H / 2), abs=1.5), local_t

    def test_static_quarter_turn_uses_the_lossless_path(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=0.0,
            duration=1.0,
            transform=Transform(scale=0.5, rotation=90),
        )
        assert "transpose=1" in (build_clip_stage(clip, W, H).chain or "")
        frames = _render(tmp_path, clip)
        box = _bbox(_at(frames, 0.5))
        assert _centre(box) == pytest.approx((W / 2, H / 2), abs=1.5)
        assert _size(box) == pytest.approx((90, 160), abs=3)  # 160x90 turned to portrait


# --------------------------------------------------------------------------- opacity
class TestAnimatedOpacity:
    @staticmethod
    def _level(frame: np.ndarray) -> float:
        return float(frame[H // 2 - 5 : H // 2 + 5, W // 2 - 5 : W // 2 + 5, 1].mean())

    def test_opaque_source_fades_linearly(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=2.0,
            keyframes={"opacity": _curve((0, 0), (2, 100))},
        )
        frames = _render(tmp_path, clip)
        for local_t, pct in [(0.0, 0), (0.5, 25), (1.0, 50), (1.5, 75), (1.9, 95)]:
            assert self._level(_at(frames, 1.0 + local_t)) == pytest.approx(255 * pct / 100, abs=6), local_t

    def test_source_transparency_is_kept_not_replaced(self, tmp_path):
        """An alpha ramp merged with `alphamerge` alone would replace a 50%-alpha PNG's own alpha."""
        half = _png(tmp_path / "half.png", color=(255, 255, 255, 128))
        clip = _clip(half, start=1.0, duration=2.0, keyframes={"opacity": _curve((0, 100), (2, 50))})
        frames = _render(tmp_path, clip)
        for local_t, ramp in [(0.0, 1.0), (1.0, 0.75), (1.9, 0.525)]:
            expected = 255 * (128 / 255) * ramp
            assert self._level(_at(frames, 1.0 + local_t)) == pytest.approx(expected, abs=6), local_t

    def test_static_opacity_still_uses_the_cheap_path(self, tmp_path):
        clip = _clip(_png(tmp_path / "w.png"), start=0, duration=1, transform=Transform(opacity=50))
        chain = build_clip_stage(clip, W, H).chain
        assert "colorchannelmixer=aa=0.5" in chain
        assert "geq" not in chain


# --------------------------------------------------------------------------- zoom
class TestAnimatedZoom:
    @staticmethod
    def _marker(tmp_path: Path) -> Path:
        """640x360 black frame with a 40px white square 60px right of centre."""
        img = Image.new("RGBA", (640, 360), (0, 0, 0, 255))
        img.paste((255, 255, 255, 255), (380 - 20, 180 - 20, 380 + 20, 180 + 20))
        path = tmp_path / "marker.png"
        img.save(path)
        return path

    @pytest.mark.parametrize("start", [0.0, 1.0])
    def test_zoom_scales_about_the_frame_centre(self, tmp_path, start):
        """Marker drift trap: a zoom that crops with a stale `iw` slides the marker sideways."""
        clip = _clip(
            self._marker(tmp_path),
            start=start,
            duration=2.0,
            keyframes={"zoom": _curve((0, 1), (2, 2))},
        )
        frames = _render(tmp_path, clip, resolution=(640, 360))
        for local_t, zoom in [(0.0, 1.0), (1.0, 1.5), (1.9, 1.95)]:
            frame = frames[round((start + local_t) * FPS)]
            box = _bbox(frame)
            assert box is not None
            assert box[2] - box[0] == pytest.approx(40 * zoom, abs=3), local_t
            assert _centre(box)[0] == pytest.approx(320 + 60 * zoom, abs=3), local_t
            assert _centre(box)[1] == pytest.approx(180, abs=2), local_t


# --------------------------------------------------------------------------- combinations
_ALL_CURVES = {
    "position.x": ((0, 0), (1, 40)),
    "position.y": ((0, 0), (1, -20)),
    "scale": ((0, 0.3), (1, 0.6)),
    "rotation": ((0, 0), (1, 45)),
    "zoom": ((0, 1), (1, 1.5)),
    "opacity": ((0, 20), (1, 100)),
}


class TestCombinations:
    """Filters interact (frame-size changes, alpha, ordering), so keyed properties are exercised together."""

    @pytest.mark.parametrize("static", [False, True], ids=["plain", "static-rotation-and-opacity"])
    @pytest.mark.parametrize(
        "names",
        [
            *[(n,) for n in _ALL_CURVES],
            ("scale", "rotation"),
            ("scale", "opacity"),
            ("rotation", "opacity"),
            ("zoom", "opacity"),
            ("zoom", "scale", "rotation"),
            ("position.x", "position.y", "scale", "rotation"),
            tuple(_ALL_CURVES),
        ],
        ids="+".join,
    )
    def test_every_combination_exports_a_full_length_video(self, tmp_path, names, static):
        transform = Transform(rotation=30, opacity=70) if static else Transform()
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=0.5,
            duration=1.0,
            transform=transform,
            keyframes={n: _curve(*_ALL_CURVES[n]) for n in names},
        )
        frames = _render(tmp_path, clip)
        assert len(frames) == 15
        assert _bbox(_at(frames, 0.2)) is None  # nothing before the clip starts
        if "opacity" not in names and not static:
            assert _bbox(_at(frames, 1.0)) is not None


# --------------------------------------------------------------------------- previews
class TestPreviewHonoursKeyframes:
    def test_preview_frame_matches_the_export_frame_at_the_same_clip_time(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=2.0,
            transform=Transform(scale=0.25),
            keyframes={"position.x": _curve((0, 0), (2, 100))},
        )
        for local_t in (0.0, 1.0, 2.0):
            png = clip.preview_image(local_t, resolution=(W, H), cache_dir=tmp_path / "cache")
            box = _bbox(np.array(Image.open(png).convert("RGB")).astype(int))
            assert _centre(box)[0] == pytest.approx(W / 2 + 50 * local_t, abs=2), local_t

    def test_distinct_times_do_not_share_a_cached_frame(self, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=0.0,
            duration=2.0,
            keyframes={"position.x": _curve((0, 0), (2, 100))},
        )
        a = clip.preview_image(0.0, resolution=(W, H), cache_dir=tmp_path / "cache")
        b = clip.preview_image(2.0, resolution=(W, H), cache_dir=tmp_path / "cache")
        assert a != b


# --------------------------------------------------------------------------- one builder
class TestPreviewAndExportShareTheBuilder:
    def _capture_graphs(self, monkeypatch, tmp_path, clip):
        """Run preview + export with subprocess.run spied on; return (preview_graph, export_graph)."""
        import visualkit.exporters.single_clip as single
        import visualkit.exporters.video as video

        graphs: dict[str, str] = {}
        real_run = subprocess.run

        def spy_preview(cmd, *a, **kw):
            graphs["preview"] = cmd[cmd.index("-filter_complex") + 1]
            return real_run(cmd, *a, **kw)

        def spy_export(cmd, *a, **kw):
            flag = next(f for f in ("-filter_complex_script", "-/filter_complex") if f in cmd)
            graphs["export"] = Path(cmd[cmd.index(flag) + 1]).read_text()
            return real_run(cmd, *a, **kw)

        monkeypatch.setattr(single.subprocess, "run", spy_preview)
        clip.preview_image(0.0, resolution=(W, H), cache_dir=tmp_path / "cache", force=True)
        monkeypatch.setattr(single.subprocess, "run", real_run)

        monkeypatch.setattr(video.subprocess, "run", spy_export)
        timeline = Timeline()
        timeline.add_clip(clip, track_index=0)
        timeline.export_to_video(tmp_path / "o.mp4", fps=FPS, resolution=(W, H))
        return graphs["preview"], graphs["export"]

    def test_static_transform_chain_is_identical(self, monkeypatch, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=0.0,
            duration=1.0,
            transform=Transform(scale=0.5, rotation=30, opacity=60),
        )
        preview, export = self._capture_graphs(monkeypatch, tmp_path, clip)
        chain = build_clip_stage(clip, W, H).chain
        assert chain and chain in preview and chain in export

    def test_keyframed_chain_is_identical_at_time_zero(self, monkeypatch, tmp_path):
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=0.0,
            duration=1.0,
            keyframes={"scale": _curve((0, 0.5), (1, 1)), "position.x": _curve((0, 0), (1, 20))},
        )
        preview, export = self._capture_graphs(monkeypatch, tmp_path, clip)
        stage = build_clip_stage(clip, W, H)
        assert stage.chain in preview and stage.chain in export
        assert stage.overlay_options in preview and stage.overlay_options in export


# --------------------------------------------------------------------------- graph shape / performance
class TestGraphShape:
    def test_geq_never_runs_at_full_resolution(self):
        clip = MediaClip(
            id="c",
            source=Source(source="x.mp4"),
            duration=Time.from_seconds(3),
            keyframes={"opacity": _curve((0, 0), (3, 100))},
        )
        statements = build_clip_stage(clip, 1920, 1080).statements("1:v", "out", "1")
        geq = [s for s in statements if "geq" in s]
        assert geq
        for s in geq:
            assert "crop=w='min(iw,16)':h='min(ih,16)'" in s
            assert s.index("crop=") < s.index("geq")

    def test_static_clip_graph_has_no_new_filters(self):
        clip = MediaClip(id="c", source=Source(source="x.mp4"), duration=Time.from_seconds(3))
        stage = build_clip_stage(clip, 1920, 1080)
        for banned in ("geq", "eval=frame", "rotate", "split"):
            assert banned not in (stage.chain or banned)
        assert not stage.eval_frame

    def test_expression_depth_is_flat_for_many_keyframes(self):
        points = [(i * 0.01, float(i % 7)) for i in range(400)]
        clip = MediaClip(
            id="c",
            source=Source(source="x.mp4"),
            duration=Time.from_seconds(5),
            keyframes={"position.x": _curve(*points)},
        )
        assert "if(if(" not in build_clip_stage(clip, 640, 360).overlay_options

    def test_many_keyframes_really_export(self, tmp_path):
        """Thousands of keyframes overflow a command line; the script file must carry them."""
        points = [(i * 0.002, (i % 50) * 1.0) for i in range(1500)]
        clip = _clip(
            _png(tmp_path / "w.png"),
            start=1.0,
            duration=3.0,
            transform=Transform(scale=0.25),
            keyframes={"position.x": _curve(*points)},
        )
        frames = _render(tmp_path, clip)
        assert len(frames) == 40
        assert _bbox(_at(frames, 2.0)) is not None


# --------------------------------------------------------------------------- filtergraph script file
class TestFiltergraphScript:
    @staticmethod
    def _timeline(tmp_path) -> Timeline:
        timeline = Timeline()
        timeline.add_clip(_clip(_png(tmp_path / "w.png"), start=0.0, duration=1.0), track_index=0)
        return timeline

    def test_command_uses_a_script_file_and_removes_it_on_success(self, monkeypatch, tmp_path):
        import visualkit.exporters.video as video

        seen: dict = {}
        real_run = subprocess.run

        def spy(cmd, *a, **kw):
            seen["cmd"] = list(cmd)
            flag = next(f for f in ("-filter_complex_script", "-/filter_complex") if f in cmd)
            script = Path(cmd[cmd.index(flag) + 1])
            seen["script"] = script
            seen["existed_during_run"] = script.exists()
            return real_run(cmd, *a, **kw)

        monkeypatch.setattr(video.subprocess, "run", spy)
        self._timeline(tmp_path).export_to_video(tmp_path / "o.mp4", fps=FPS, resolution=(W, H))

        assert "-filter_complex" not in seen["cmd"], "the graph must not be passed inline"
        assert seen["existed_during_run"]
        assert not seen["script"].exists()
        assert not list(tmp_path.glob(".*filtergraph*")), "no script file may be left behind"

    def test_script_file_is_removed_when_ffmpeg_fails(self, monkeypatch, tmp_path):
        import visualkit.exporters.video as video

        seen: dict = {}

        class Failed:
            returncode = 1
            stderr = b"boom"

        def failing(cmd, *a, **kw):
            flag = next(f for f in ("-filter_complex_script", "-/filter_complex") if f in cmd)
            seen["script"] = Path(cmd[cmd.index(flag) + 1])
            assert seen["script"].exists()
            return Failed()

        monkeypatch.setattr(video.subprocess, "run", failing)
        with pytest.raises(ExportError):
            self._timeline(tmp_path).export_to_video(tmp_path / "o.mp4", fps=FPS, resolution=(W, H))
        assert not seen["script"].exists()
        assert not list(tmp_path.glob(".*filtergraph*"))

    def test_script_file_is_removed_when_ffmpeg_is_missing(self, monkeypatch, tmp_path):
        import visualkit.exporters.video as video

        seen: dict = {}

        def missing(cmd, *a, **kw):
            flag = next(f for f in ("-filter_complex_script", "-/filter_complex") if f in cmd)
            seen["script"] = Path(cmd[cmd.index(flag) + 1])
            raise FileNotFoundError("ffmpeg")

        monkeypatch.setattr(video.subprocess, "run", missing)
        with pytest.raises(ExportError, match="not found"):
            self._timeline(tmp_path).export_to_video(tmp_path / "o.mp4", fps=FPS, resolution=(W, H))
        assert not seen["script"].exists()

    @pytest.mark.parametrize(
        "version_line, flag",
        [
            ("ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023", "-filter_complex_script"),
            ("ffmpeg version 4.4.2 Copyright", "-filter_complex_script"),
            ("ffmpeg version 7.0 Copyright", "-/filter_complex"),
            ("ffmpeg version n7.1.1 Copyright", "-/filter_complex"),
            ("ffmpeg version N-118000-gabcdef Copyright", "-/filter_complex"),
            ("something unparseable", "-filter_complex_script"),
        ],
    )
    def test_flag_choice_by_ffmpeg_version(self, version_line, flag):
        from visualkit.exporters._ffmpeg import option_for_ffmpeg_version

        assert option_for_ffmpeg_version(version_line) == flag


def test_exporter_class_is_still_the_public_entry_point():
    assert FFmpegVideoExporter.__name__ == "FFmpegVideoExporter"
    assert Easing.LINEAR.value == "linear"
