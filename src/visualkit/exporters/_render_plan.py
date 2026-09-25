"""One place that turns a visual clip's transform (+ keyframes) into ffmpeg filters.

`FFmpegVideoExporter.export` and `preview_media_image` both used to build the
transform chain and overlay position on their own; every new feature would have
been implemented twice and drifted. Both now call `build_clip_stage`.

Stage order (matches the documented contract of `Transform`)::

    [chroma key] -> fit -> zoom -> [mask, opacity ramp] -> scale -> rotate -> [static opacity]
    ...then overlay at position

Facts this module is built around (all measured against ffmpeg 6.1.1; see the handoff notes):

* ``t`` inside ``overlay``/``scale``/``rotate``/``crop`` is **absolute timeline time**,
  because each clip is shifted with ``setpts=...+start/TB``. Keyframe expressions are
  therefore written against ``clip_start + keyframe_time`` (`PropertyCurve.to_expr`).
* ``colorchannelmixer`` rejects expressions, so animated opacity is an *alpha ramp*:
  a 16x16 gray frame whose value comes from ``geq`` (cheap at that size), scaled up and
  multiplied into the clip's own alpha. The ramp is derived from **the clip's own frames**
  (crop -> geq) so both streams carry identical timestamps by construction; a separately
  generated ramp source drifted against clips of a different frame rate.
* ``scale eval=frame`` changes the size of every frame but ``rotate`` (and anything else that
  reads the link's size) keeps using the first frame's, freezing the result. Uniform scale and
  rotation about the same centre commute, so when both are present the order is swapped:
  pre-scale to the largest scale, rotate at a fixed size, then animate the scale *down*.
* ``crop``'s default offset uses a stale ``iw`` after ``scale eval=frame``; animated zoom
  therefore computes the crop offset from the same expression that sized the frame.
* ``geq`` is far too slow at full resolution (6x-20x). The opacity ramp runs it on 16x16 and a
  mask on a frame of at most ~130k pixels (a quarter of 1080p), both scaled up afterwards.
* The chroma key comes first, before anything resamples the picture, so the key colour is not
  blended into edges. A mask and an opacity ramp both modulate alpha, so they are *multiplied*
  into the clip's own alpha (``alphamerge`` alone would replace it).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from visualkit.models.clips.visual import Transform, VisualClip
from visualkit.models.effects import ChromaKey, Mask
from visualkit.models.keyframes import PropertyCurve, fmt_num, validate_curves

# Tokens substituted when a stage is rendered into a filter_complex (see `ClipStage.statements`).
_IN, _OUT, _UID, _PRE = "@IN@", "@OUT@", "@U@", "@PRE@"


@dataclass(frozen=True)
class ClipStage:
    """Everything needed to composite one clip: its filters, and where to overlay it."""

    _templates: tuple[str, ...]
    #: overlay option string, e.g. ``x=12.0:y=0.0`` or ``eval=frame:x='...':y='...'``
    overlay_options: str
    #: True when the overlay position/size changes per frame
    eval_frame: bool
    #: final frame size when it is constant (static path); ``None`` when scale is animated
    effective_size: tuple[int, int] | None
    #: the whole chain as one comma-joined string when it needs no side branches (static and most keyed clips)
    chain: str | None

    def statements(self, in_label: str, out_label: str, uid: str, prefix: str = "") -> list[str]:
        """filter_complex statements taking `in_label` and producing `out_label`.

        `prefix` is any filters that must run first (the exporter's ``trim,setpts``), given with a
        trailing comma. `uid` keeps side-branch labels unique between clips.
        """
        return [
            t.replace(_IN, in_label).replace(_OUT, out_label).replace(_UID, f"k{uid}_").replace(_PRE, prefix)
            for t in self._templates
        ]


# --------------------------------------------------------------------------- geometry helpers
def _even_up(n: int) -> int:
    return n + (n % 2)


def rotation_box(frame_w: int, frame_h: int, lo_deg: float, hi_deg: float) -> tuple[int, int]:
    """Smallest even box that holds a `frame_w`x`frame_h` frame rotated by any angle in ``[lo, hi]``.

    ffmpeg's ``rotate`` needs a fixed output box, and its cost is proportional to the box area, so
    a 0->10 degree animation should not pay for the full diagonal. The bounding box of a rotated
    rectangle is ``w|cos|+h|sin|`` by ``w|sin|+h|cos|``; each is maximal at +-atan(h/w) (resp.
    atan(w/h)) modulo 180, so only the endpoints and those critical angles need checking.
    """
    lo, hi = min(lo_deg, hi_deg), max(lo_deg, hi_deg)

    def extents(deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        c, s = abs(math.cos(rad)), abs(math.sin(rad))
        return frame_w * c + frame_h * s, frame_w * s + frame_h * c

    if hi - lo >= 180.0:
        diag = math.hypot(frame_w, frame_h)
        max_w = max_h = diag
    else:
        a = math.degrees(math.atan2(frame_h, frame_w))
        candidates = [lo, hi]
        for base in (a, -a, 90.0 - a, a - 90.0):
            k = math.floor((lo - base) / 180.0)
            for n in (k, k + 1, k + 2):
                angle = base + 180.0 * n
                if lo < angle < hi:
                    candidates.append(angle)
        max_w = max(extents(d)[0] for d in candidates)
        max_h = max(extents(d)[1] for d in candidates)
    return _even_up(math.ceil(max_w - 1e-6)), _even_up(math.ceil(max_h - 1e-6))


def _quarter_turns(rotation_deg: float) -> int | None:
    """0..3 if `rotation_deg` is an exact multiple of 90 degrees, else ``None``."""
    turned = rotation_deg % 360.0
    q = round(turned / 90.0)
    return q % 4 if abs(turned - q * 90.0) < 1e-9 else None


def _scaled_dim(base: int, factor_expr: str, divisor: str = "1") -> str:
    """ffmpeg expression for ``base * factor / divisor`` rounded to an even number >= 2."""
    scaled = f"{base}*({factor_expr})" + ("" if divisor == "1" else f"/{divisor}")
    return f"max(2,2*round({scaled}/2))"


# --------------------------------------------------------------------------- masks / key
#: Largest frame (in pixels) a mask is generated at with ``geq``; a quarter of 1080p.
MASK_PIXEL_BUDGET = 130_000


def mask_frame_size(width: int, height: int) -> tuple[int, int, int]:
    """Size ``(w, h)`` a mask is computed at, and the integer factor ``k`` it is scaled up by."""
    k = max(1, math.ceil(math.sqrt(width * height / MASK_PIXEL_BUDGET)))
    return max(2, math.ceil(width / k)), max(2, math.ceil(height / k)), k


def mask_level_expr(mask: Mask, curves: Mapping[str, PropertyCurve], clip_start_s: float) -> str:
    """A ``geq`` luma expression (0-255, 255 = visible) for `mask`, in the mask frame's pixels.

    Coverage is ``clip(0.5 - d / F, 0, 1)`` where ``d`` is the signed distance to the outline in
    pixels (negative inside) and ``F`` the feather width (at least one pixel, which is the
    anti-aliasing). Animated parameters are evaluated once per pixel into ``st``/``ld`` slots
    rather than pasted into every use.
    """
    prelude: list[str] = []
    slots: dict[str, str] = {}

    def param(name: str, slot: int) -> str:
        key = f"mask.{name}"
        if key in curves:
            prelude.append(f"st({slot},{curves[key].to_expr(clip_start_s, var='T')})")
            return f"ld({slot})"
        return fmt_num(getattr(mask, name))

    cx, cy = param("x", 0), param("y", 1)
    w, h, feather = param("width", 2), param("height", 3), param("feather", 4)
    slots.update(cx=cx, cy=cy, w=w, h=h, f=feather)

    px = f"(X+0.5-({cx})*W)"
    py = f"(Y+0.5-({cy})*H)"
    half_w = f"(({w})*W/2)"
    half_h = f"(({h})*H/2)"
    band = f"max(1,({feather})*min(W,H))"

    if mask.shape == "rect":
        qx, qy = f"(abs({px})-{half_w})", f"(abs({py})-{half_h})"
        dist = f"(hypot(max({qx},0),max({qy},0))+min(max({qx},{qy}),0))"
    else:
        a, b = f"max({half_w},0.001)", f"max({half_h},0.001)"
        r = f"hypot({px}/{a},{py}/{b})"
        grad = f"(hypot({px}/({a}*{a}),{py}/({b}*{b}))/max({r},0.000001))"
        dist = f"(({r}-1)/max({grad},0.000000001))"

    coverage = f"clip(0.5-{dist}/{band},0,1)"
    if mask.invert:
        coverage = f"(1-{coverage})"
    return ";".join([*prelude, f"255*{coverage}"])


def _key_filters(key: ChromaKey) -> list[str]:
    """The filters that key `key.color` out (then, optionally, de-spill), ending in rgba."""
    options = f"color={key.ffmpeg_color}:similarity={fmt_num(key.similarity)}:blend={fmt_num(key.blend)}"
    filters = [f"{key.method}={options}"]
    if key.despill:
        filters.append(f"despill=type={key.despill_type}")
    filters.append("format=rgba")
    return filters


# --------------------------------------------------------------------------- the builder
class _Graph:
    """Accumulates plain filters into chains and closes them into labelled statements."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self._prefix = f"[{_IN}]{_PRE}"
        self._filters: list[str] = []

    def add(self, *filters: str) -> None:
        self._filters.extend(filters)

    def close(self, output_labels: str) -> None:
        self.statements.append(self._prefix + ",".join(self._filters) + output_labels)
        self._prefix, self._filters = "", []

    def side_branch(self, statement: str) -> None:
        self.statements.append(statement)

    def restart_from(self, input_labels: str) -> None:
        self._prefix, self._filters = input_labels, []

    @property
    def is_single_chain(self) -> bool:
        return not self.statements


def _build(
    transform: Transform,
    curves: Mapping[str, PropertyCurve],
    width: int,
    height: int,
    clip_start_s: float,
    chroma_key: ChromaKey | None = None,
    mask: Mask | None = None,
) -> ClipStage:
    validate_curves(dict(curves))  # names/bounds only; guards against in-place dict edits after construction

    def expr(name: str, var: str = "t") -> str:
        return curves[name].to_expr(clip_start_s, var=var)

    keyed = set(curves)
    g = _Graph()
    rgba = False

    # 0. Chroma key: before anything resamples the picture (fit scales it).
    if chroma_key is not None:
        g.add(*_key_filters(chroma_key))
        rgba = True

    # 1. Fit to explicit Size, or to the canvas if Size is (0, 0).
    if transform.size.width > 0 and transform.size.height > 0:
        target_w, target_h = int(transform.size.width), int(transform.size.height)
    else:
        target_w, target_h = width, height
    g.add(
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease",
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black@0",
    )

    # 2. Zoom: crop into the centre by 1/zoom, then scale back up to the same footprint.
    if "zoom" in keyed:
        # crop cannot take a time-dependent size, so scale UP by zoom(t) and crop back to the
        # fixed footprint. Offsets come from the same expression as the scaled size, never from
        # `iw` (stale after `scale eval=frame`). Zoom < 1 cannot be expressed as a crop; clamp to 1.
        z = f"max(1,{expr('zoom')})"
        zw, zh = _scaled_dim(target_w, z), _scaled_dim(target_h, z)
        g.add(
            f"scale=w='{zw}':h='{zh}':eval=frame:flags=bilinear",
            f"crop={target_w}:{target_h}:x='({zw}-{target_w})/2':y='({zh}-{target_h})/2'",
        )
    elif transform.zoom != 1.0 and transform.zoom > 0:
        crop_w = max(1, round(target_w / transform.zoom))
        crop_h = max(1, round(target_h / transform.zoom))
        g.add(f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:(ih-{crop_h})/2", f"scale={target_w}:{target_h}")

    # 3. Mask and animated opacity, applied here while the frame still has its fixed footprint so
    # each modulator always matches the frame size (scale/rotate that follow carry the alpha along).
    # Each becomes a gray frame derived from the clip's own frames (so timestamps agree by
    # construction); their product is merged into the clip's alpha.
    modulators: list[str] = []
    if mask is not None:
        mw, mh, k = mask_frame_size(target_w, target_h)
        level = mask_level_expr(mask, curves, clip_start_s)
        sharpen = ""
        if k > 1 and mask.feather == 0 and "mask.feather" not in keyed:
            # A hard edge computed at 1/k resolution ramps over k pixels once scaled up; a steep
            # curve squeezes it back to about one.
            sharpen = f"lut=y='clip(128+(val-128)*{k},0,255)',"
        modulators.append(
            f"crop=w='min(iw,16)':h='min(ih,16)':x=0:y=0,scale={mw}:{mh},format=gray,"
            f"geq=lum='{level}',scale={target_w}:{target_h}:flags=bilinear,{sharpen}format=gray"
        )
    if "opacity" in keyed:
        # opacity is 0-100; the ramp is a 0-255 gray level.
        level = f"255*({expr('opacity', var='T')})/100"
        modulators.append(
            f"crop=w='min(iw,16)':h='min(ih,16)':x=0:y=0,format=gray,"
            f"geq=lum='{level}',scale={target_w}:{target_h}:flags=bilinear,format=gray"
        )
    if modulators:
        n = len(modulators)
        branch_labels = "".join(f"[{_UID}m{i}]" for i in range(n))
        g.add("format=rgba", f"split={n + 2}")
        g.close(f"[{_UID}c][{_UID}a]{branch_labels}")
        for i, chain in enumerate(modulators):
            g.side_branch(f"[{_UID}m{i}]{chain}[{_UID}g{i}]")
        g.side_branch(f"[{_UID}a]alphaextract[{_UID}p0]")
        # multiply (not alphamerge alone): alphamerge REPLACES alpha, which would erase the
        # source's own transparency (PNG, text, keyed video).
        for i in range(n):
            g.side_branch(f"[{_UID}p{i}][{_UID}g{i}]blend=all_mode=multiply:shortest=1[{_UID}p{i + 1}]")
        g.restart_from(f"[{_UID}c][{_UID}p{n}]")
        g.add("alphamerge")
        rgba = True

    static_opacity = "opacity" not in keyed and transform.opacity != 100
    scale_keyed = "scale" in keyed

    def apply_static_opacity() -> None:
        nonlocal rgba
        if not rgba:
            g.add("format=rgba")
            rgba = True
        g.add(f"colorchannelmixer=aa={transform.opacity / 100.0}")

    # After `scale eval=frame` no processing filter may follow (frame size no longer matches the link),
    # so with animated scale the (commuting) static opacity is applied first, at the fixed size.
    opacity_done = static_opacity and scale_keyed
    if opacity_done:
        apply_static_opacity()

    # 4/5. Scale and rotation. Cases (see module docstring for why scale/rotate can be reordered):
    rot_keyed = "rotation" in keyed
    quarter = None if rot_keyed else _quarter_turns(transform.rotation)
    rotates = rot_keyed or (quarter is None) or (quarter != 0)

    frame_w, frame_h = target_w, target_h
    scale_expr: str | None = None
    final_scale_ratio: str | None = None  # animated shrink applied AFTER rotation
    scale_max = 1.0

    if scale_keyed:
        scale_expr = expr("scale")
        if rotates:
            scale_max = curves["scale"].max_value
            frame_w, frame_h = max(1, round(target_w * scale_max)), max(1, round(target_h * scale_max))
            if (frame_w, frame_h) != (target_w, target_h):
                g.add(f"scale={frame_w}:{frame_h}")
            final_scale_ratio = f"({scale_expr})/{fmt_num(scale_max)}"
        else:
            g.add(
                f"scale=w='{_scaled_dim(target_w, scale_expr)}':h='{_scaled_dim(target_h, scale_expr)}'"
                ":eval=frame"
            )
    elif transform.scale != 1.0:
        frame_w = max(1, round(target_w * transform.scale))
        frame_h = max(1, round(target_h * transform.scale))
        g.add(f"scale={frame_w}:{frame_h}")

    if rot_keyed:
        curve = curves["rotation"]
        frame_w, frame_h = rotation_box(frame_w, frame_h, curve.min_value, curve.max_value)
        if not rgba:
            g.add("format=rgba")
            rgba = True
        g.add(f"rotate=a='PI/180*({expr('rotation')})':ow={frame_w}:oh={frame_h}:c=black@0")
    elif quarter is None:
        if not rgba:
            g.add("format=rgba")
            rgba = True
        radians = math.radians(transform.rotation)
        cos_a, sin_a = abs(math.cos(radians)), abs(math.sin(radians))
        rot_w = math.ceil(frame_w * cos_a + frame_h * sin_a - 1e-6)
        rot_h = math.ceil(frame_w * sin_a + frame_h * cos_a - 1e-6)
        frame_w, frame_h = _even_up(rot_w), _even_up(rot_h)
        g.add(f"rotate={radians}:ow={frame_w}:oh={frame_h}:c=black@0")
    elif quarter == 1:
        g.add("transpose=1")  # exact 90 deg clockwise: no interpolation, no oversized box, no alpha
        frame_w, frame_h = frame_h, frame_w
    elif quarter == 2:
        g.add("hflip", "vflip")
    elif quarter == 3:
        g.add("transpose=2")
        frame_w, frame_h = frame_h, frame_w

    if final_scale_ratio is not None:
        new_w = _scaled_dim(frame_w, final_scale_ratio)
        new_h = _scaled_dim(frame_h, final_scale_ratio)
        g.add(f"scale=w='{new_w}':h='{new_h}':eval=frame")

    # 6. Static opacity: the original cheap path, kept for unkeyed opacity.
    if static_opacity and not opacity_done:
        apply_static_opacity()

    single_chain = g.is_single_chain
    chain = ",".join(g._filters) if single_chain else None
    g.close(f"[{_OUT}]")

    # ---- overlay position ----
    pos_x_keyed, pos_y_keyed = "position.x" in keyed, "position.y" in keyed
    size_varies = scale_keyed
    eval_frame = size_varies or pos_x_keyed or pos_y_keyed

    if not eval_frame:
        overlay_x = (width - frame_w) / 2 + transform.position.x
        overlay_y = (height - frame_h) / 2 + transform.position.y
        options = f"x={overlay_x}:y={overlay_y}"
        effective: tuple[int, int] | None = (frame_w, frame_h)
    else:

        def axis(main: str, over: str, canvas: int, frame: int, name: str, static: float) -> str:
            # `overlay` exposes the main size as W/H and the (per-frame) overlay size as w/h.
            centre = f"({main}-{over})/2" if size_varies else fmt_num((canvas - frame) / 2)
            offset = expr(name) if name in keyed else fmt_num(static)
            return f"{centre}+({offset})"

        x_expr = axis("W", "w", width, frame_w, "position.x", transform.position.x)
        y_expr = axis("H", "h", height, frame_h, "position.y", transform.position.y)
        options = f"eval=frame:x='{x_expr}':y='{y_expr}'"
        effective = None if size_varies else (frame_w, frame_h)

    return ClipStage(
        _templates=tuple(g.statements),
        overlay_options=options,
        eval_frame=eval_frame,
        effective_size=effective,
        chain=chain,
    )


def build_clip_stage(clip: VisualClip, width: int, height: int, *, clip_start_s: float = 0.0) -> ClipStage:
    """The filter statements and overlay options that composite `clip` onto a `width`x`height` canvas.

    `clip_start_s` is the clip's ``timeline_start`` in seconds; keyframe curves are shifted by it
    because ffmpeg's ``t`` is absolute timeline time. A single-frame preview passes ``-time`` so
    that ``t = 0`` corresponds to `time` seconds into the clip.
    """
    return _build(
        clip.transform,
        clip.effective_keyframes(),
        width,
        height,
        clip_start_s,
        chroma_key=clip.chroma_key,
        mask=clip.effective_mask(),
    )


def build_static_stage(transform: Transform, width: int, height: int) -> ClipStage:
    """Stage for a bare `Transform` (no keyframes)."""
    return _build(transform, {}, width, height, 0.0)
