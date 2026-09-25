"""Guards for fields that must survive `CodedVisualClip.to_media_clip()`.

`to_media_clip()` used to build the `MediaClip` by naming fields one by one, so
any field later added to `VisualClip` (keyframes, chroma key, mask, ...) was
silently dropped for coded visuals. These tests fail loudly if that recurs:
every `VisualClip` field needs a *non-default* sample value below, and each one
must come out the other side of `to_media_clip()`.
"""

from __future__ import annotations

import pytest

from visualkit.models import CodedVisualClip, CompileStatus, MediaClip, Transform, VisualClip
from visualkit.models.keyframes import PropertyCurve
from visualkit.utils.time import Time

#: One non-default value per `VisualClip` field (including the `BaseClip` ones).
#: When `VisualClip` gains a field, `test_every_field_has_a_sample` fails until a
#: non-default sample is added here -- which then proves `to_media_clip()` copies it.
SAMPLES = {
    "id": "cv_sample",
    "timeline_start": Time.from_seconds(3),
    "duration": Time.from_seconds(4),
    "speed": 2.0,
    "transform": Transform(scale=0.5, opacity=40, rotation=10),
    "keyframes": {"opacity": PropertyCurve.from_points([(0, 0), (1, 100)])},
}


def _compiled_clip() -> CodedVisualClip:
    clip = CodedVisualClip(source="does_not_matter.html", **SAMPLES)
    clip.media_source = "/tmp/render.png"
    clip.compile_status = CompileStatus.READY
    return clip


def test_every_field_has_a_sample():
    missing = set(VisualClip.model_fields) - set(SAMPLES)
    assert not missing, (
        f"VisualClip gained field(s) {sorted(missing)}: add a NON-DEFAULT sample to SAMPLES so this "
        "suite can prove CodedVisualClip.to_media_clip() copies them."
    )
    assert not set(SAMPLES) - set(VisualClip.model_fields), "SAMPLES names a field VisualClip no longer has"


@pytest.mark.parametrize("field", sorted(SAMPLES))
def test_to_media_clip_carries_the_field(field: str):
    clip = _compiled_clip()
    default = MediaClip(source="x.mp4")  # defaults for every field
    assert getattr(clip, field) != getattr(default, field) or field == "duration", (
        f"sample for {field!r} equals the default, so it cannot detect a dropped field"
    )
    media = clip.to_media_clip()
    assert isinstance(media, MediaClip)
    assert getattr(media, field) == getattr(clip, field), f"to_media_clip() dropped or changed {field!r}"


def test_to_media_clip_result_is_independent_of_the_source_clip():
    clip = _compiled_clip()
    media = clip.to_media_clip()
    media.transform.opacity = 10
    media.keyframes["opacity"].keyframes[0].value = 50
    assert clip.transform.opacity == 40
    assert clip.keyframes["opacity"].keyframes[0].value == 0
