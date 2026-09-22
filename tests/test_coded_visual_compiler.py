import json
from pathlib import Path

import pytest

from visualkit.coded_visual.compiler import CodedVisualCompiler
from visualkit.coded_visual.project import CodedVisualManifest, load_coded_visual
from visualkit.models import CodedVisualClip, CompileStatus, Size, Variable, VariableType
from visualkit.utils.time import Time


@pytest.fixture
def temp_templates_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary directory with single HTML and bundle templates."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    # 1. Create a single-file HTML template with meta tags
    single_html = templates_dir / "single_stat.html"
    single_html.write_text(
        """<!DOCTYPE html>
<html>
<head>
    <meta name="aspect-ratio" content="9:16">
    <meta name="canvas-size" content="1080x1920">
    <meta name="fps" content="60">
    <title>Story Infographic</title>
</head>
<body>
    <div class="visualkit-canvas">
        <h1>{{ headline }}</h1>
        <p class="counter">{{ count }}</p>
    </div>
</body>
</html>
""",
        encoding="utf-8",
    )

    # 2. Create a directory bundle template with manifest.json and assets
    bundle_dir = templates_dir / "chart_bundle"
    bundle_dir.mkdir()
    assets_dir = bundle_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "logo.svg").write_text("<svg></svg>", encoding="utf-8")

    manifest_data = {
        "name": "Bar Chart Template",
        "aspect_ratio": "16:9",
        "canvas_size": {"width": 1920, "height": 1080},
        "fps": 30.0,
        "duration": 6.0,
        "variables": {
            "title": {
                "name": "title",
                "type": "string",
                "default": "Q3 Growth",
                "label": "Chart Title",
                "description": "Main title above bar chart",
            },
            "bar_color": {
                "name": "bar_color",
                "type": "color",
                "default": "#4f46e5",
                "label": "Bar Fill Color",
                "description": "Hex color for the bars",
            },
        },
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    (bundle_dir / "index.html").write_text(
        """<!DOCTYPE html>
<html>
<head>
    <title>Bar Chart</title>
    <link rel="stylesheet" href="./style.css">
</head>
<body>
    <div class="visualkit-canvas">
        <img src="./assets/logo.svg" alt="Logo">
        <h2 id="chart-title">{{ title }}</h2>
    </div>
    <script>
        document.body.style.color = window.__VARIABLES__.bar_color;
    </script>
</body>
</html>
""",
        encoding="utf-8",
    )

    return templates_dir


def test_load_single_html_meta(temp_templates_dir: Path):
    single_html = temp_templates_dir / "single_stat.html"
    entrypoint, manifest, raw_html = load_coded_visual(single_html)

    assert entrypoint == single_html.resolve()
    assert manifest.aspect_ratio == "9:16"
    assert manifest.canvas_size.width == 1080
    assert manifest.canvas_size.height == 1920
    assert manifest.fps == 60.0
    assert "{{ headline }}" in raw_html


def test_load_directory_bundle(temp_templates_dir: Path):
    bundle_dir = temp_templates_dir / "chart_bundle"
    entrypoint, manifest, raw_html = load_coded_visual(bundle_dir)

    assert entrypoint == (bundle_dir / "index.html").resolve()
    assert manifest.name == "Bar Chart Template"
    assert manifest.aspect_ratio == "16:9"
    assert manifest.canvas_size.width == 1920
    assert manifest.canvas_size.height == 1080
    assert "title" in manifest.variables
    assert manifest.variables["title"].label == "Chart Title"
    assert "assets/logo.svg" in raw_html


def test_clip_load_manifest_integration(temp_templates_dir: Path):
    bundle_dir = temp_templates_dir / "chart_bundle"
    clip = CodedVisualClip(source=str(bundle_dir))

    # Auto-load manifest metadata into clip
    clip.load_manifest()

    assert clip.aspect_ratio == "16:9"
    assert clip.canvas_size.width == 1920
    assert "title" in clip.variables
    assert clip.variables["title"].resolve_value() == "Q3 Growth"
    assert clip.variables["bar_color"].resolve_value() == "#4f46e5"


def test_load_manifest_backfills_duration(temp_templates_dir: Path):
    """`clip.duration` should reflect the manifest's declared duration (6.0s here)
    once `load_manifest()` has run, without needing to compile -- previously
    `clip.duration` stayed at its zero default even after loading a manifest
    that declares one, silently disagreeing with what the compiler would
    actually render for."""
    bundle_dir = temp_templates_dir / "chart_bundle"
    clip = CodedVisualClip(source=str(bundle_dir))

    assert clip.duration.seconds == 0.0  # unset before load_manifest()
    clip.load_manifest()
    assert clip.duration.seconds == 6.0  # backfilled from manifest.json's "duration": 6.0


def test_load_manifest_does_not_override_explicit_duration(temp_templates_dir: Path):
    """An explicitly-set duration must win over the manifest's, matching the
    precedence `load_manifest()` already documents for canvas_size/fps."""
    bundle_dir = temp_templates_dir / "chart_bundle"
    clip = CodedVisualClip(source=str(bundle_dir), duration=Time.from_seconds(9))

    clip.load_manifest()
    assert clip.duration.seconds == 9.0  # untouched, not overwritten by manifest's 6.0


def test_compiler_deterministic_cache_key():
    key1 = CodedVisualCompiler.compute_cache_key(
        source_content="<div>test</div>",
        variables={"a": 1, "b": 2},
        canvas_size=Size(width=1920, height=1080),
        aspect_ratio="16:9",
        fps=30.0,
        duration=5.0,
    )
    # Order of variables in dict should not alter the cache key
    key2 = CodedVisualCompiler.compute_cache_key(
        source_content="<div>test</div>",
        variables={"b": 2, "a": 1},
        canvas_size=Size(width=1920, height=1080),
        aspect_ratio="16:9",
        fps=30.0,
        duration=5.0,
    )
    assert key1 == key2

    # Changing a variable changes the key
    key3 = CodedVisualCompiler.compute_cache_key(
        source_content="<div>test</div>",
        variables={"a": 999, "b": 2},
        canvas_size=Size(width=1920, height=1080),
        aspect_ratio="16:9",
        fps=30.0,
        duration=5.0,
    )
    assert key1 != key3


def test_compiler_prepare_html_injections():
    raw = "<html><head><title>Test</title></head><body><h1>{{ title }}</h1></body></html>"
    prepared = CodedVisualCompiler.prepare_html(
        raw_html=raw,
        variables={"title": "Super Cool Chart", "bg": "#000"},
        canvas_size=Size(width=1080, height=1920),
        aspect_ratio="9:16",
        base_dir=Path("/custom/base/dir"),
    )

    # 1. Jinja placeholder replaced
    assert "<h1>Super Cool Chart</h1>" in prepared

    # 2. window.__VARIABLES__ injected
    assert "window.__VARIABLES__ =" in prepared
    assert '"title": "Super Cool Chart"' in prepared

    # 3. Base tag injected for relative asset resolution
    assert '<base href="file:///custom/base/dir/">' in prepared

    # 4. Aspect ratio locked viewport CSS injected. CSS requires `9 / 16`; the
    # previous output `aspect-ratio: 9:16` is invalid CSS and was silently ignored.
    assert "aspect-ratio: 9 / 16;" in prepared
    assert "aspect-ratio: 9:16" not in prepared
    assert "width: 1080px;" in prepared
    assert "height: 1920px;" in prepared


def test_compiler_compile_end_to_end(tmp_path: Path, temp_templates_dir: Path):
    compiler_cache = tmp_path / "compiler_cache"
    compiler = CodedVisualCompiler(cache_dir=compiler_cache)

    bundle_dir = temp_templates_dir / "chart_bundle"
    clip = CodedVisualClip(
        source=str(bundle_dir),
        duration=Time.from_seconds(4),
        variables={"title": "Revenue 2026", "bar_color": "#10b981"},
    )

    # Compile the clip. The output must be real media, not the intermediate HTML.
    media_source = compiler.compile(clip, render_video=False)

    assert clip.compile_status == CompileStatus.READY
    assert clip.media_source == media_source
    assert Path(media_source).suffix == ".png"
    assert Path(media_source).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # a real PNG

    # The prepared page it was rendered from carries the variables and asset base.
    prepared_html = (Path(media_source).parent / "index.html").read_text(encoding="utf-8")
    assert "Revenue 2026" in prepared_html
    assert "#10b981" in prepared_html
    assert '<base href="' in prepared_html


def test_preview_frame_seeks_animation(tmp_path: Path):
    """`preview_frame(t)` must render the page's actual state at virtual time
    `t`, not always frame 0 -- and must not touch media_source/compile_status
    (unlike compile()), since it's meant for cheap mid-animation checks
    before committing to a real render."""
    bundle_dir = tmp_path / "bar_grow"
    bundle_dir.mkdir()
    (bundle_dir / "index.html").write_text(
        """<!DOCTYPE html>
<html><head><meta name="canvas-size" content="400x200"></head>
<body>
<style>
  .visualkit-canvas { background: #000; }
  #bar { width: 0px; height: 40px; background: #f00; animation: grow 2s linear forwards; }
  @keyframes grow { to { width: 400px; } }
</style>
<div class="visualkit-canvas"><div id="bar"></div></div>
</body></html>
""",
        encoding="utf-8",
    )
    compiler = CodedVisualCompiler(cache_dir=tmp_path / "cache")
    clip = CodedVisualClip(source=str(bundle_dir), duration=Time.from_seconds(2))

    frame_start = clip.preview_frame(0.0, compiler=compiler)
    frame_mid = clip.preview_frame(1.0, compiler=compiler)

    assert frame_start.exists() and frame_mid.exists()
    assert frame_start != frame_mid  # distinct cached files per timestamp
    assert frame_start.read_bytes() != frame_mid.read_bytes()  # and genuinely different pixels

    # preview_frame must not mark the clip as compiled / set its media
    assert clip.compile_status == CompileStatus.PENDING
    assert clip.media_source is None


@pytest.mark.asyncio
async def test_coded_visual_clip_async_resolve(temp_templates_dir: Path):
    bundle_dir = temp_templates_dir / "chart_bundle"
    clip = CodedVisualClip(
        id="cv_test_resolve",
        source=str(bundle_dir),
        timeline_start=Time.from_seconds(3),
        duration=Time.from_seconds(7),
        speed=1.5,
    )
    resolved_media = await clip.resolve()
    assert resolved_media.id == "cv_test_resolve"
    assert resolved_media.timeline_start.seconds == 3.0
    assert resolved_media.duration.seconds == 7.0
    assert resolved_media.speed == 1.5
    assert resolved_media.source.source.endswith(".png")  # rendered media, never the html
