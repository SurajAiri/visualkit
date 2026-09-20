"""Locating and running a headless Chrome/Chromium.

VisualKit never bundles a browser. It uses one already installed, found in
this order:

1. the ``VISUALKIT_CHROME`` environment variable (explicit override),
2. ``chrome-headless-shell`` / ``chromium`` / ``google-chrome`` on ``PATH``,
3. well-known install locations (macOS, Linux, Windows),
4. browsers downloaded by Playwright or Puppeteer (``~/.cache/...``).

``chrome-headless-shell`` is preferred when present: it is smaller, starts
faster and, unlike full Chrome, does not need a display server or profile
directory to take a screenshot.
"""

from __future__ import annotations

import glob
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from visualkit.utils.exceptions import BrowserNotFoundError, CodedVisualCompileError

ENV_VAR = "VISUALKIT_CHROME"

_PATH_NAMES = (
    "chrome-headless-shell",
    "headless_shell",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
)

_KNOWN_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

_CACHE_GLOBS = (
    "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux/headless_shell",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-mac/headless_shell",
    "~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell",
    "~/.cache/puppeteer/chrome/*/chrome-linux*/chrome",
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
)


def find_chrome() -> str | None:
    """Return the path to a usable Chrome/Chromium executable, or None."""
    override = os.environ.get(ENV_VAR)
    if override:
        return override if Path(override).exists() else None

    for name in _PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in _KNOWN_PATHS:
        if Path(candidate).exists():
            return candidate
    for pattern in _CACHE_GLOBS:
        matches = sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)
        if matches:
            return matches[0]
    return None


def require_chrome() -> str:
    """Like `find_chrome` but raises `BrowserNotFoundError` with fix instructions."""
    override = os.environ.get(ENV_VAR)
    if override and not Path(override).exists():
        raise BrowserNotFoundError(f"{ENV_VAR}={override!r} does not exist.")
    chrome = find_chrome()
    if chrome is None:
        raise BrowserNotFoundError(
            "No Chrome/Chromium executable found. Install Google Chrome or Chromium, or point "
            f"the {ENV_VAR} environment variable at one (e.g. `npx @puppeteer/browsers install "
            "chrome-headless-shell`)."
        )
    return chrome


def _needs_no_sandbox() -> bool:
    """Chrome refuses to start as root / in most containers without --no-sandbox."""
    if sys.platform.startswith("win"):
        return False
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    return is_root or Path("/.dockerenv").exists() or bool(os.environ.get("VISUALKIT_NO_SANDBOX"))


def _is_headless_shell(chrome: str) -> bool:
    """`chrome-headless-shell` / `headless_shell` are always headless and reject ``--headless=new``."""
    return "headless" in Path(chrome).name.lower()


def base_args(chrome: str | None = None) -> list[str]:
    """Flags every invocation needs for reliable, deterministic headless rendering."""
    chrome = chrome or require_chrome()
    args = [
        "--disable-gpu",
        "--hide-scrollbars",
        "--mute-audio",
        "--no-first-run",
        "--disable-background-networking",
        "--disable-dev-shm-usage",
        "--force-color-profile=srgb",
        "--allow-file-access-from-files",
    ]
    if not _is_headless_shell(chrome):
        args.insert(0, "--headless=new")
    if _needs_no_sandbox():
        args.append("--no-sandbox")
    return args


def screenshot(
    html_path: Path,
    out_png: Path,
    width: int,
    height: int,
    *,
    timeout: float = 60.0,
    virtual_time_budget_ms: int = 2000,
    transparent: bool = True,
) -> None:
    """Render `html_path` to a PNG of exactly ``width`` x ``height`` using the Chrome CLI.

    Raises `CodedVisualCompileError` with Chrome's stderr on failure or timeout.
    """
    chrome = require_chrome()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if out_png.exists():
        out_png.unlink()

    profile = tempfile.mkdtemp(prefix="visualkit-chrome-")
    cmd = [
        chrome,
        *base_args(chrome),
        f"--user-data-dir={profile}",
        f"--screenshot={out_png}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={virtual_time_budget_ms}",
    ]
    if transparent:
        cmd.append("--default-background-color=00000000")
    cmd.append(html_path.resolve().as_uri())

    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as err:
        _kill_tree(proc)
        raise CodedVisualCompileError(
            f"Chrome did not finish rendering {html_path.name} within {timeout:g}s (killed)."
        ) from err
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    if proc.returncode != 0 or not out_png.exists():
        tail = stderr.decode("utf-8", errors="replace").strip()[-800:] if stderr else "(no stderr)"
        raise CodedVisualCompileError(
            f"Chrome failed to render {html_path.name} (exit {proc.returncode}): {tail}"
        )


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform.startswith("win"):
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()
