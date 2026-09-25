"""Example 5: Keyframed Transforms, Chroma Key, Masks, Text Style, and Animation Presets

Demonstrates the FFmpeg-exporter-only features on top of the core timeline model:
- Keyframed position, scale and opacity (`VisualClip.keyframes`).
- Chroma key, to remove a green screen (`ChromaKey`).
- A feathered ellipse mask with an animated radius (`Mask`).
- Extended text styling: outline, drop shadow, gradient fill (`TextStyle`).
- In/out animation presets -- fade, slide, pop, wipe -- as sugar over keyframes
  (`ClipAnimation`), which apply to a `TextClip` exactly like any other visual clip.

None of this is supported by the DaVinci Resolve export: `export_to_resolve` ignores
keyframes, `chroma_key`, `mask` and `animation`, and renders the plain static `transform`
instead (see each field's docstring).

This script is runnable end-to-end: it generates its own PNG fixtures with Pillow (a green
screen and a checkerboard background) rather than depending on real footage, and needs `ffmpeg`
on PATH to actually export.
"""

from pathlib import Path

from PIL import Image

import visualkit as vk


def _make_fixtures(assets_dir: Path) -> tuple[Path, Path]:
    """A green-screen subject and a checkerboard backdrop, written as PNGs."""
    assets_dir.mkdir(parents=True, exist_ok=True)

    screen = Image.new("RGBA", (480, 270), (0, 177, 64, 255))  # broadcast chroma green
    for y in range(60, 210):
        for x in range(180, 300):
            screen.putpixel((x, y), (240, 200, 60, 255))  # a plain "subject" block
    screen_path = assets_dir / "green_screen.png"
    screen.save(screen_path)

    backdrop = Image.new("RGBA", (1280, 720), (20, 20, 30, 255))
    tile = 64
    for ty in range(0, 720, tile):
        for tx in range(0, 1280, tile):
            if (tx // tile + ty // tile) % 2 == 0:
                for y in range(ty, min(ty + tile, 720)):
                    for x in range(tx, min(tx + tile, 1280)):
                        backdrop.putpixel((x, y), (35, 35, 50, 255))
    backdrop_path = assets_dir / "backdrop.png"
    backdrop.save(backdrop_path)

    return screen_path, backdrop_path


def main():
    print("=== VisualKit Example 5: Keyframes, Chroma Key, Masks, Text, Animation ===")

    assets_dir = Path("output") / "05_assets"
    screen_path, backdrop_path = _make_fixtures(assets_dir)

    timeline = vk.Timeline()
    duration = vk.Time.from_seconds(4)

    # 1. Backdrop, filling the whole 1280x720 canvas.
    backdrop = vk.MediaClip(id="backdrop", source=str(backdrop_path), duration=duration)
    timeline.add_clip(backdrop, track_index=0)

    # 2. The green-screen subject: keyed transparent, masked to a feathered ellipse whose size
    #    breathes over time, and keyframed across the frame.
    subject = vk.MediaClip(
        id="subject",
        source=str(screen_path),
        duration=duration,
        transform=vk.Transform(size=vk.Size(width=480, height=270)),
        chroma_key=vk.ChromaKey(color="#00B140", similarity=0.15, despill=True),
        mask=vk.Mask(shape="ellipse", width=0.35, height=0.5, feather=0.08),
        keyframes={
            "position.x": vk.PropertyCurve.from_points([(0, -300), (2, 300), (4, -300)]),
            "position.y": vk.PropertyCurve.from_points([(0, 0), (4, 0)]),
            "mask.width": vk.PropertyCurve.from_points(
                [(0, 0.2, vk.Easing.EASE_IN_OUT), (2, 0.4), (4, 0.2, vk.Easing.EASE_IN_OUT)]
            ),
        },
    )
    timeline.add_clip(subject, track_index=1)

    # 3. A title with outline, drop shadow, gradient fill, and a fade+pop entrance.
    title = vk.TextClip(
        id="title",
        text="VisualKit",
        duration=duration,
        style=vk.TextStyle(
            font_size=140,
            color="#ffffff",
            stroke_width=4,
            stroke_color="#101018",
            shadow_color="#000000",
            shadow_offset_x=4,
            shadow_offset_y=6,
            shadow_blur=10,
            gradient=vk.TextGradient(start_color="#38bdf8", end_color="#818cf8", angle=90),
        ),
        transform=vk.Transform(position=vk.Position(x=0, y=-200)),
        animation=vk.ClipAnimation(in_preset="fade", out_preset="pop", in_duration=0.6, out_duration=0.6),
    )
    timeline.add_clip(title, track_index=2)

    # 4. A caption that wipes on, sliding attention across the frame.
    caption = vk.TextClip(
        id="caption",
        text="keyframes + chroma key + masks + text animation",
        timeline_start=vk.Time.from_seconds(0.5),
        duration=vk.Time.from_seconds(3),
        style=vk.TextStyle(font_size=40, color="#e2e8f0", letter_spacing=2, line_height=1.3),
        transform=vk.Transform(position=vk.Position(x=0, y=260)),
        animation=vk.ClipAnimation(in_preset="wipe", in_duration=0.5),
    )
    timeline.add_clip(caption, track_index=3)

    print(f"Total duration: {timeline.duration}")
    print(f"Video tracks:   {len(timeline.video_tracks)}")

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    # 5. Export to FFmpeg -- this is the exporter that honours every feature above.
    video_path = out_dir / "keyframes_and_effects.mp4"
    try:
        timeline.export_to_video(video_path, fps=30, resolution=(1280, 720))
        print(f"Exported video:                  {video_path}")
    except vk.ExportError as err:
        print(f"FFmpeg export failed (is ffmpeg on PATH?): {err}")

    # 6. Export to DaVinci Resolve too, for comparison -- it ignores every effect used above and
    #    renders each clip's plain, static `transform` instead.
    xml_path = out_dir / "keyframes_and_effects_resolve.xml"
    timeline.export_to_resolve(output_path=xml_path, fps=30.0)
    print(f"Exported DaVinci Resolve project: {xml_path}")
    print("(Resolve ignores keyframes/chroma_key/mask/animation -- see field docstrings.)")


if __name__ == "__main__":
    main()
