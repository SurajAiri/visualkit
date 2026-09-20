"""Deterministic frame capture of animated HTML, and motion detection.

Animation in a web page is driven by several independent clocks. To render
it *frame-exactly* (identical output regardless of how fast the machine is)
both are controlled explicitly:

* **JavaScript time** -- ``Date``, ``performance.now``, ``setTimeout``,
  ``setInterval`` and ``requestAnimationFrame`` -- runs on a *virtual clock*
  that only advances when we tell it to.
* **CSS animations / transitions / Web Animations** -- these follow the
  document timeline, not JS timers, so every animation is paused and its
  ``currentTime`` set to the frame's timestamp.

Frames are then captured one by one in a **single** browser session and
piped to ffmpeg. This needs the optional ``playwright`` package
(``pip install visualkit[render]``); it is used only as a DevTools-protocol
driver for the browser found by `visualkit.coded_visual.browser`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from visualkit.coded_visual import browser
from visualkit.utils.exceptions import CodedVisualCompileError

# Pause + seek every CSS/Web animation to `ms`.
_SEEK_JS = """(ms) => {
  for (const a of document.getAnimations()) {
    try { a.pause(); a.currentTime = ms; } catch (e) {}
  }
}"""

# Wait for web fonts and <img> decoding so frame 0 is not a half-loaded page.
_SETTLE_JS = """async () => {
  if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (e) {} }
  const imgs = Array.from(document.images);
  await Promise.all(imgs.map(i => i.decode ? i.decode().catch(() => {}) : Promise.resolve()));
}"""


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as err:  # pragma: no cover - exercised only when the extra is missing
        raise CodedVisualCompileError(
            "Rendering animated coded visuals needs the optional 'playwright' package: "
            "`pip install visualkit[render]` (VisualKit still uses your installed Chrome; it does "
            "not download a browser). Still-image visuals do not need it."
        ) from err
    return sync_playwright


def _launch(pw):
    chrome = browser.require_chrome()
    args = [a for a in browser.base_args(chrome) if not a.startswith("--headless")]
    try:
        return pw.chromium.launch(executable_path=chrome, args=args, headless=True, timeout=30_000)
    except Exception as err:
        raise CodedVisualCompileError(f"Could not launch Chrome at {chrome}: {err}") from err


def _new_page(pw_browser, html_path: Path, width: int, height: int):
    context = pw_browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
    page = context.new_page()
    page.clock.install(time=0)  # virtual clock: nothing advances until we say so
    page.goto(html_path.resolve().as_uri(), wait_until="load", timeout=60_000)
    page.evaluate(_SETTLE_JS)
    return context, page


def frame_times(duration: float, fps: float) -> list[float]:
    """Timestamps (seconds) of every output frame: ``round(duration*fps)`` frames, at least one."""
    count = max(1, round(duration * fps))
    return [i / fps for i in range(count)]


def capture_video(
    *,
    html_path: Path,
    out_file: Path,
    width: int,
    height: int,
    duration: float,
    fps: float,
    ffmpeg: str = "ffmpeg",
    timeout: float = 300.0,
) -> None:
    """Render ``html_path`` for ``duration`` seconds at ``fps`` into ``out_file`` (H.264 MP4).

    Frames are streamed straight into ffmpeg's stdin as PNGs; nothing is written
    to disk per frame. Raises `CodedVisualCompileError` (with ffmpeg's stderr) on failure.
    """
    sync_playwright = _require_playwright()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        out_file.unlink()
    tmp_out = out_file.with_suffix(".part.mp4")

    times = frame_times(duration, fps)
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-framerate",
        f"{fps:g}",
        "-c:v",
        "png",
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        # yuv420p needs even dimensions.
        "-vf",
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        str(tmp_out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with sync_playwright() as pw:
            pw_browser = _launch(pw)
            try:
                context, page = _new_page(pw_browser, html_path, width, height)
                previous_ms = 0
                for t in times:
                    # The virtual clock only accepts whole milliseconds. Step by the
                    # difference of *rounded absolute* targets (not rounded deltas) so
                    # sub-millisecond error never accumulates over a long clip.
                    target_ms = int(round(t * 1000.0))
                    step = target_ms - previous_ms
                    if step > 0:
                        page.clock.run_for(step)
                    previous_ms = target_ms
                    page.evaluate(_SEEK_JS, t * 1000.0)
                    png = page.screenshot(type="png", omit_background=True, animations="allow")
                    if proc.stdin is None or proc.poll() is not None:
                        break
                    proc.stdin.write(png)
                context.close()
            finally:
                pw_browser.close()
        # communicate() flushes and closes stdin itself; closing it here first makes
        # its own flush raise "flush of closed file".
        _, stderr = proc.communicate(timeout=timeout)
    except CodedVisualCompileError:
        _abort(proc, tmp_out)
        raise
    except BrokenPipeError as err:
        _, stderr = proc.communicate()
        _abort(proc, tmp_out)
        raise CodedVisualCompileError(
            f"ffmpeg exited early: {stderr.decode(errors='replace')[-600:]}"
        ) from err
    except Exception as err:
        _abort(proc, tmp_out)
        raise CodedVisualCompileError(f"Failed to capture {html_path.name}: {err}") from err

    if proc.returncode != 0 or not tmp_out.exists():
        _abort(proc, tmp_out)
        raise CodedVisualCompileError(
            f"ffmpeg failed encoding {html_path.name} (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[-600:]}"
        )
    tmp_out.replace(out_file)  # atomic: a partial file never masquerades as a finished render


def _abort(proc: subprocess.Popen, partial: Path) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    finally:
        if partial.exists():
            partial.unlink()


def detect_motion(html_path: Path, width: int, height: int, *, timeout: float = 120.0) -> bool:
    """True if the page renders differently at two virtual times (i.e. it is animated).

    Renders at t=0 and at t=1.5s on the virtual clock (with CSS animations seeked to
    match) and compares the pixels. If Playwright is not installed, falls back to
    a static heuristic (CSS ``animation``/``@keyframes``/``requestAnimationFrame``
    in the source) so still visuals never require the optional dependency.
    """
    try:
        sync_playwright = _require_playwright()
    except CodedVisualCompileError:
        return _looks_animated(html_path.read_text(encoding="utf-8", errors="replace"))

    with sync_playwright() as pw:
        pw_browser = _launch(pw)
        try:
            context, page = _new_page(pw_browser, html_path, width, height)
            page.evaluate(_SEEK_JS, 0)
            first = page.screenshot(type="png", animations="allow")
            page.clock.run_for(1500)
            page.evaluate(_SEEK_JS, 1500)
            second = page.screenshot(type="png", animations="allow")
            context.close()
        finally:
            pw_browser.close()
    return first != second


_ANIM_HINTS = (
    "@keyframes",
    "animation:",
    "animation-name",
    "requestanimationframe",
    "setinterval",
    "transition:",
)


def _looks_animated(source: str) -> bool:
    lowered = source.lower()
    return any(hint in lowered for hint in _ANIM_HINTS)
