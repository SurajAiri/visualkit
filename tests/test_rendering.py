"""Tests for browser discovery, deterministic capture, motion detection and scale-to-fit.

Pure-logic tests always run. Tests that drive a real browser are marked
`browser` and skip cleanly when no Chrome/Chromium (or, for animated capture,
Playwright) is available, so the suite stays green on minimal CI machines.
"""

import shutil
from pathlib import Path

import pytest

import visualkit as vk
from visualkit.coded_visual import browser, capture
from visualkit.coded_visual.compiler import CodedVisualCompiler
from visualkit.utils.exceptions import BrowserNotFoundError, CodedVisualCompileError

try:
    import playwright  # noqa: F401

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

HAS_CHROME = browser.find_chrome() is not None
HAS_FFMPEG = shutil.which("ffmpeg") is not None

needs_chrome = pytest.mark.skipif(not HAS_CHROME, reason="no Chrome/Chromium available")
needs_animation_stack = pytest.mark.skipif(
    not (HAS_CHROME and HAS_PLAYWRIGHT and HAS_FFMPEG), reason="needs Chrome + playwright + ffmpeg"
)


# --------------------------------------------------------------------------- discovery
class TestBrowserDiscovery:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        fake = tmp_path / "my-chrome"
        fake.write_text("")
        monkeypatch.setenv(browser.ENV_VAR, str(fake))
        assert browser.find_chrome() == str(fake)
        assert browser.require_chrome() == str(fake)

    def test_env_override_pointing_nowhere_is_an_error_not_a_silent_fallback(self, monkeypatch):
        monkeypatch.setenv(browser.ENV_VAR, "/definitely/not/here")
        assert browser.find_chrome() is None
        with pytest.raises(BrowserNotFoundError, match="does not exist"):
            browser.require_chrome()

    def test_missing_browser_error_says_how_to_fix_it(self, monkeypatch):
        monkeypatch.delenv(browser.ENV_VAR, raising=False)
        monkeypatch.setattr(browser, "find_chrome", lambda: None)
        with pytest.raises(BrowserNotFoundError, match=browser.ENV_VAR):
            browser.require_chrome()

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/x/chrome-headless-shell", True),
            ("/x/headless_shell", True),
            ("/usr/bin/google-chrome", False),
            ("/usr/bin/chromium", False),
        ],
    )
    def test_headless_shell_detection(self, path, expected):
        assert browser._is_headless_shell(path) is expected

    def test_full_chrome_gets_headless_flag_but_headless_shell_does_not(self):
        assert "--headless=new" in browser.base_args("/usr/bin/google-chrome")
        assert not any(a.startswith("--headless") for a in browser.base_args("/x/chrome-headless-shell"))

    def test_no_sandbox_added_when_forced_by_env(self, monkeypatch):
        monkeypatch.setenv("VISUALKIT_NO_SANDBOX", "1")
        assert "--no-sandbox" in browser.base_args("/usr/bin/google-chrome")


# --------------------------------------------------------------------------- pure capture logic
class TestFrameTimes:
    def test_frame_count_and_spacing(self):
        times = capture.frame_times(2.0, 30)
        assert len(times) == 60
        assert times[0] == 0 and times[1] == pytest.approx(1 / 30)

    def test_always_at_least_one_frame(self):
        assert capture.frame_times(0.0, 30) == [0.0]
        assert len(capture.frame_times(0.001, 30)) == 1

    def test_last_frame_is_before_the_end(self):
        assert capture.frame_times(1.0, 10)[-1] < 1.0


class TestMotionHeuristic:
    """The no-Playwright fallback only has to be conservative-correct."""

    @pytest.mark.parametrize(
        "source",
        [
            "<style>@keyframes x{}</style>",
            "<style>div{animation: spin 1s}</style>",
            "<script>requestAnimationFrame(f)</script>",
            "<script>setInterval(f, 10)</script>",
        ],
    )
    def test_detects_animation_hints(self, source):
        assert capture._looks_animated(source) is True

    def test_static_page_is_not_animated(self):
        assert capture._looks_animated("<html><body><h1>Hello</h1></body></html>") is False


# --------------------------------------------------------------------------- prepared HTML
class TestPreparedHtml:
    def _prep(self, html, variables=None, w=1080, h=1920, ratio="9:16", **kw):
        return CodedVisualCompiler.prepare_html(
            html, variables or {}, vk.Size(width=w, height=h), ratio, **kw
        )

    def test_canvas_is_locked_to_design_size_and_scaled_by_a_variable(self):
        out = self._prep("<html><head></head><body></body></html>")
        assert "width: 1080px; height: 1920px" in out
        assert "--vk-scale" in out
        assert "aspect-ratio: 9 / 16" in out

    def test_scale_to_fit_can_be_disabled(self):
        out = self._prep("<html><head></head><body></body></html>", scale_to_fit=False)
        assert "--vk-scale" not in out and 'id="visualkit-fit"' not in out

    def test_double_brace_is_escaped_triple_brace_is_raw(self):
        out = self._prep("<html><head></head><body>{{ a }}|{{{ a }}}</body></html>", {"a": "<b>x</b>"})
        assert "&lt;b&gt;x&lt;/b&gt;|<b>x</b>" in out

    def test_variable_cannot_close_the_script_block(self):
        out = self._prep("<html><head></head></html>", {"a": "</script><script>alert(1)</script>"})
        json_line = next(line for line in out.splitlines() if line.startswith("window.__VARIABLES__"))
        assert "</script>" not in json_line
        assert "\\u003c/script\\u003e" in json_line

    def test_backslashes_in_values_survive_substitution(self):
        out = self._prep("<html><head></head><body>{{ p }}</body></html>", {"p": r"C:\new\1"})
        assert r"C:\new\1" in out

    @pytest.mark.parametrize(
        "html",
        [
            '<html><head lang="en"></head></html>',
            "<HTML><HEAD></HEAD></HTML>",
            "<html><body></body></html>",
            "<p>bare</p>",
        ],
    )
    def test_injection_works_for_any_document_shape(self, html):
        assert 'id="visualkit-variables"' in self._prep(html)

    def test_unknown_placeholders_are_left_alone(self):
        out = self._prep("<html><head></head><body>{{ nope }}</body></html>", {"a": 1})
        assert "{{ nope }}" in out


# --------------------------------------------------------------------------- cache keys
class TestCacheKey:
    def _key(self, **over):
        args = dict(
            source_content="<html/>",
            variables={"a": 1},
            canvas_size=vk.Size(width=10, height=10),
            aspect_ratio="1:1",
            fps=30,
            duration=2,
        )
        args.update(over)
        return CodedVisualCompiler.compute_cache_key(**args)

    def test_stable_for_identical_inputs(self):
        assert self._key() == self._key()

    @pytest.mark.parametrize(
        "change",
        [
            {"source_content": "<html>x</html>"},
            {"variables": {"a": 2}},
            {"canvas_size": vk.Size(width=20, height=10)},
            {"fps": 60},
            {"duration": 3},
            {"render_mode": "video"},
            {"bundle_digest": "abc"},
        ],
    )
    def test_any_input_change_changes_the_key(self, change):
        assert self._key(**change) != self._key()

    def test_editing_a_bundle_asset_busts_the_cache(self, tmp_path):
        (tmp_path / "index.html").write_text("<html/>")
        (tmp_path / "style.css").write_text("a{}")
        first = CodedVisualCompiler._bundle_digest(tmp_path / "index.html")
        (tmp_path / "style.css").write_text("a{color:red}")
        assert CodedVisualCompiler._bundle_digest(tmp_path / "index.html") != first

    def test_single_file_visual_has_empty_bundle_digest(self, tmp_path):
        (tmp_path / "only.html").write_text("<html/>")
        assert CodedVisualCompiler._bundle_digest(tmp_path / "only.html") == ""


# --------------------------------------------------------------------------- real-browser behaviour
STILL = """<!DOCTYPE html><html><head>
<meta name="canvas-size" content="400x300">
</head><body><div class="visualkit-canvas" style="background:#ff0000">{{ t }}</div></body></html>"""

ANIMATED = """<!DOCTYPE html><html><head>
<meta name="canvas-size" content="200x100">
<style>#b{position:absolute;left:0;top:0;height:100px;width:0;background:#00f;animation:g 2s linear forwards}
@keyframes g{from{width:0}to{width:200px}}</style></head><body><div id="b"></div></body></html>"""


@pytest.fixture
def compiler(tmp_path):
    return CodedVisualCompiler(cache_dir=tmp_path / "cache")


@needs_chrome
class TestStillRendering:
    def test_still_renders_a_png_at_the_design_size(self, tmp_path, compiler):
        from PIL import Image

        (tmp_path / "v.html").write_text(STILL)
        clip = vk.CodedVisualClip(
            id="s", source=str(tmp_path / "v.html"), duration=vk.Time(1), variables={"t": "hi"}
        )
        out = compiler.compile(clip, render_video=False)
        assert out.endswith(".png")
        assert Image.open(out).size == (400, 300)  # from the <meta>, not a 1920x1080 default
        assert clip.compile_status == vk.CompileStatus.READY

    def test_render_is_cached_and_variable_change_rerenders(self, tmp_path, compiler):
        (tmp_path / "v.html").write_text(STILL)
        clip = vk.CodedVisualClip(
            id="s", source=str(tmp_path / "v.html"), duration=vk.Time(1), variables={"t": "a"}
        )
        first = compiler.compile(clip, render_video=False)
        clip.set_variable("t", "b")  # also invalidates
        second = compiler.compile(clip, render_video=False)
        assert first != second

    def test_direct_variable_mutation_never_serves_a_stale_render(self, tmp_path, compiler):
        """Bypassing set_variable() must still change the cache key (content-addressed)."""
        (tmp_path / "v.html").write_text(STILL)
        clip = vk.CodedVisualClip(
            id="s", source=str(tmp_path / "v.html"), duration=vk.Time(1), variables={"t": "a"}
        )
        first = compiler.compile(clip, render_video=False)
        clip.variables["t"].value = "changed"
        assert compiler.compile(clip, render_video=False, force=False) != first

    def test_missing_source_is_a_clear_error(self, compiler):
        clip = vk.CodedVisualClip(id="s", source="/no/such/file.html", duration=vk.Time(1))
        with pytest.raises(CodedVisualCompileError, match="not found"):
            compiler.compile(clip, render_video=False)
        assert clip.compile_status == vk.CompileStatus.FAILED

    def test_missing_required_variable_is_a_clear_error(self, tmp_path, compiler):
        (tmp_path / "v.html").write_text(STILL)
        clip = vk.CodedVisualClip(id="s", source=str(tmp_path / "v.html"), duration=vk.Time(1))
        clip.define_variable("t", required=True)
        with pytest.raises(CodedVisualCompileError, match="missing required variable"):
            compiler.compile(clip, render_video=False)


@needs_chrome
class TestScaleToFit:
    @pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="needs playwright to resize a viewport")
    @pytest.mark.parametrize("viewport", [(1080, 1920), (1920, 1080), (540, 960), (1000, 1000)])
    def test_canvas_keeps_aspect_ratio_and_stays_inside_the_viewport(self, tmp_path, compiler, viewport):
        from playwright.sync_api import sync_playwright

        (tmp_path / "v.html").write_text(STILL.replace("400x300", "1080x1920"))
        clip = vk.CodedVisualClip(id="s", source=str(tmp_path / "v.html"), duration=vk.Time(1))
        html_path, _ = compiler.prepare_bundle(clip)
        vw, vh = viewport
        chrome = browser.require_chrome()
        with sync_playwright() as pw:
            b = pw.chromium.launch(
                executable_path=chrome,
                args=[a for a in browser.base_args(chrome) if not a.startswith("--headless")],
            )
            page = b.new_page(viewport={"width": vw, "height": vh})
            page.goto(html_path.as_uri())
            r = page.evaluate(
                "(() => { const e = document.querySelector('.visualkit-canvas').getBoundingClientRect();"
                " return {x: e.x, y: e.y, w: e.width, h: e.height}; })()"
            )
            b.close()
        assert r["w"] / r["h"] == pytest.approx(1080 / 1920, rel=1e-3)
        assert r["x"] >= -0.5 and r["y"] >= -0.5
        assert r["x"] + r["w"] <= vw + 0.5 and r["y"] + r["h"] <= vh + 0.5


@needs_animation_stack
class TestAnimatedRendering:
    def test_animation_progresses_frame_exactly(self, tmp_path, compiler):
        import subprocess

        from PIL import Image

        (tmp_path / "a.html").write_text(ANIMATED)
        clip = vk.CodedVisualClip(
            id="a", source=str(tmp_path / "a.html"), duration=vk.Time(2), render_mode=vk.RenderMode.VIDEO
        )
        mp4 = Path(compiler.compile(clip))
        widths = []
        for ts in ("0", "0.5", "1.0", "1.5"):
            png = tmp_path / f"f{ts}.png"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", ts, "-i", str(mp4), "-frames:v", "1", str(png)],
                check=True,
            )
            im = Image.open(png).convert("RGB")
            widths.append(
                sum(
                    1
                    for x in range(im.width)
                    if im.getpixel((x, 50))[2] > 200 and im.getpixel((x, 50))[0] < 90
                )
            )
        assert widths[0] == 0
        assert widths == sorted(widths) and len(set(widths)) == 4  # strictly growing
        assert widths[2] == pytest.approx(100, abs=3)  # halfway through a 200px, 2s sweep

    def test_video_has_expected_frame_count_and_size(self, tmp_path, compiler):
        import subprocess

        (tmp_path / "a.html").write_text(ANIMATED)
        clip = vk.CodedVisualClip(
            id="a", source=str(tmp_path / "a.html"), duration=vk.Time(2), render_mode=vk.RenderMode.VIDEO
        )
        mp4 = compiler.compile(clip)
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                # Matroska stores no frame count in its header, so count the decoded frames.
                "-count_frames",
                "-show_entries",
                "stream=width,height,nb_read_frames",
                "-of",
                "csv=p=0",
                mp4,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        w, h, n = probe.split(",")
        assert (int(w), int(h)) == (200, 100)
        assert int(n) == round(2 * clip.fps)

    def test_auto_mode_detects_motion_and_stillness(self, tmp_path, compiler):
        (tmp_path / "a.html").write_text(ANIMATED)
        (tmp_path / "s.html").write_text(STILL)
        animated = vk.CodedVisualClip(id="a", source=str(tmp_path / "a.html"), duration=vk.Time(2))
        still = vk.CodedVisualClip(
            id="s", source=str(tmp_path / "s.html"), duration=vk.Time(2), variables={"t": "x"}
        )
        assert compiler.is_animated(animated) is True
        assert compiler.is_animated(still) is False
        assert compiler.compile(still).endswith(".png")

    def test_no_partial_file_left_after_failed_render(self, tmp_path, compiler):
        """ffmpeg must actually start and fail *mid-encode*, otherwise the cleanup path never runs."""
        # A wrapper that creates the output file, then exits non-zero: exactly a crashed encode.
        fake = tmp_path / "fake-ffmpeg"
        fake.write_text(
            "#!/bin/sh\n"
            "for last; do :; done\n"
            'printf partial > "$last"\n'
            "cat >/dev/null\n"
            "echo boom >&2\n"
            "exit 1\n"
        )
        fake.chmod(0o755)

        (tmp_path / "a.html").write_text(ANIMATED)
        clip = vk.CodedVisualClip(
            id="a", source=str(tmp_path / "a.html"), duration=vk.Time(1), render_mode=vk.RenderMode.VIDEO
        )
        compiler.ffmpeg = str(fake)
        with pytest.raises(CodedVisualCompileError, match="boom"):
            compiler.compile(clip)
        assert not list(compiler.cache_dir.rglob("*.mp4")) + list(compiler.cache_dir.rglob("*.mkv")), (
            "a broken render must not be left where a cache hit could find it"
        )
        assert clip.compile_status == vk.CompileStatus.FAILED

    def test_missing_ffmpeg_is_a_clear_error(self, tmp_path, compiler):
        (tmp_path / "a.html").write_text(ANIMATED)
        clip = vk.CodedVisualClip(
            id="a", source=str(tmp_path / "a.html"), duration=vk.Time(1), render_mode=vk.RenderMode.VIDEO
        )
        compiler.ffmpeg = "ffmpeg-does-not-exist"
        with pytest.raises(CodedVisualCompileError, match="ffmpeg was not found"):
            compiler.compile(clip)


@needs_animation_stack
class TestAutoRenderDefaults:
    """Every entry point must pick video for motion and PNG for stills by default.

    Regression: flatten()/export_to_resolve() defaulted to render_video=False, so an
    animated visual silently exported as a single frozen PNG.
    """

    @staticmethod
    def _media_name(timeline):
        return timeline.video_tracks[0].clips[0].source.source.rsplit("/", 1)[1]

    def _clips(self, tmp_path):
        (tmp_path / "a.html").write_text(ANIMATED)
        (tmp_path / "s.html").write_text(STILL)
        animated = vk.CodedVisualClip(id="a", source=str(tmp_path / "a.html"), duration=vk.Time(2))
        still = vk.CodedVisualClip(
            id="s", source=str(tmp_path / "s.html"), duration=vk.Time(2), variables={"t": "x"}
        )
        return animated, still

    def test_flatten_default(self, tmp_path):
        animated, still = self._clips(tmp_path)
        # Animated visuals keep their transparency: lossless FFV1 in Matroska.
        for clip, expected in ((animated, "render.mkv"), (still, "render.png")):
            t = vk.Timeline()
            t.add_clip(clip)
            assert self._media_name(t.flatten()) == expected

    def test_explicit_override_wins_over_auto_detection(self, tmp_path):
        animated, _ = self._clips(tmp_path)
        t = vk.Timeline()
        t.add_clip(animated)
        assert self._media_name(t.flatten(render_video=False)) == "render.png"

    def test_resolve_export_default(self, tmp_path):
        animated, still = self._clips(tmp_path)
        for clip, expected in ((animated, "render.mp4"), (still, "render.png")):
            t = vk.Timeline()
            t.add_clip(clip)
            xml = Path(t.export_to_resolve(tmp_path / f"{clip.id}.xml")).read_text()
            assert f"/{expected}</pathurl>" in xml

    def test_flatten_does_not_modify_the_source_timeline(self, tmp_path):
        animated, _ = self._clips(tmp_path)
        t = vk.Timeline()
        t.add_clip(animated)
        t.flatten()
        assert animated.media_source is None
        assert animated.compile_status == vk.CompileStatus.PENDING
