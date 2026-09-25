"""Small ffmpeg plumbing shared by the video exporter and the single-clip preview."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator


def option_for_ffmpeg_version(version_line: str) -> str:
    """The flag that reads a filtergraph from a file, for the ffmpeg build named by `version_line`.

    ``-filter_complex_script`` exists through ffmpeg 6 and is deprecated from 7 in favour of
    ``-/filter_complex``. Unparseable version strings (distro suffixes, git builds) are treated
    as modern except for a plain ``version 4/5/6`` prefix.
    """
    match = re.search(r"version\s+n?(\d+)", version_line)
    if match:
        return "-/filter_complex" if int(match.group(1)) >= 7 else "-filter_complex_script"
    if re.search(r"version\s+N-\d+", version_line):  # git master build
        return "-/filter_complex"
    return "-filter_complex_script"


@lru_cache(maxsize=8)
def filter_script_option(ffmpeg: str = "ffmpeg") -> str:
    """Probe `ffmpeg -version` once and pick the right filtergraph-file flag."""
    try:
        out = subprocess.run([ffmpeg, "-version"], capture_output=True, check=False, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return "-filter_complex_script"
    first = out.decode("utf-8", errors="replace").splitlines()[:1]
    return option_for_ffmpeg_version(first[0] if first else "")


@contextmanager
def filtergraph_script(graph: str, *, directory: Path, stem: str) -> Iterator[Path]:
    """Write `graph` to a temp script file in `directory`, and always delete it afterwards.

    Passing the graph on the command line overflows the OS argument limit at a few thousand
    keyframes ("Argument list too long"); a script file does not. The file lives next to the
    output so it is on the same filesystem and easy to spot if a crash ever leaves one behind.
    """
    fd, name = tempfile.mkstemp(dir=directory, prefix=f".{stem}.", suffix=".filtergraph.txt")
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(graph)
        yield path
    finally:
        path.unlink(missing_ok=True)
