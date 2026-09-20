"""Example 2: Coded visuals (HTML/CSS/JS infographics with typed variables)

A *coded visual* is a small web project that draws an infographic or an
animation. VisualKit renders it in a headless browser into ordinary media --
a PNG for a still visual, a video for an animated one -- and that file is then
used like any other clip on the timeline.

Demonstrates:
- Referencing a visual bundle (a directory with index.html, manifest.json and
  local assets such as an SVG logo).
- Pulling its design canvas and variable schema from the manifest.
- Typed variables: required/optional, colors, numbers, labels for UI builders.
- Rendering a still preview, and rendering the animation to video.
- Placing the visual on a timeline and flattening it into a normal media clip.

Requires: Chrome/Chromium (set VISUALKIT_CHROME if it is not auto-detected),
FFmpeg, and `pip install visualkit[render]` for the animated part.
"""

from pathlib import Path

import visualkit as vk
from visualkit.coded_visual.compiler import CodedVisualCompiler

BUNDLE = Path(__file__).parent / "assets" / "stat_card"


def main() -> None:
    print("=== VisualKit Example 2: Coded Visuals & Infographics ===")

    # 1. Reference the bundle. Nothing is rendered yet.
    clip = vk.CodedVisualClip(
        id="stat_card",
        source=str(BUNDLE),
        timeline_start=vk.Time.from_seconds(1),
        duration=vk.Time.from_seconds(4),
    )

    # 2. The design canvas and variable schema come from manifest.json / <meta> tags.
    clip.load_manifest()
    print(f"Design canvas : {clip.design_size[0]}x{clip.design_size[1]} ({clip.design_aspect_ratio})")
    print("Variables     :", ", ".join(clip.variables))
    print("Still needed  :", clip.get_missing_required_variables())

    # 3. Fill in values. Assignments are type-checked: a bad color raises immediately.
    clip.set_variable("title", "Global Active Users")
    clip.set_variable("value", "10.5M")
    clip.set_variable("accent", "#22c55e")
    clip.set_variable("progress", 84)
    print("Still needed  :", clip.get_missing_required_variables(), "(after setting values)")

    try:
        clip.set_variable("accent", "not; a } color")
    except ValueError as err:
        print("Rejected bad color:", str(err).splitlines()[-1][:70])

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    compiler = CodedVisualCompiler()

    # 4. A still preview is cheap: one screenshot at the design size.
    still = compiler.render_to_image(clip)
    print(f"Still preview : {still}")

    # 5. The full animation. Frames are stepped deterministically (identical on any machine)
    #    and streamed to FFmpeg. Needs the optional 'playwright' package.
    try:
        video = compiler.render_to_video(clip, output_path=out_dir / "stat_card.mp4", fps=30.0)
        print(f"Video         : {video}")
    except vk.CodedVisualCompileError as err:
        print(f"Video skipped : {err}")

    # 6. On a timeline, the visual is just a clip. flatten() renders it (video if it moves,
    #    PNG if it doesn't) and returns plain media clips. The original timeline is untouched.
    timeline = vk.Timeline()
    timeline.add_clip(clip)
    try:
        flat = timeline.flatten()
        resolved = flat.video_tracks[0].clips[0]
        print(f"Flattened     : {resolved.clip_type} -> {Path(resolved.source.source).name}")
    except vk.CodedVisualCompileError as err:
        print(f"Flatten skipped: {err}")


if __name__ == "__main__":
    main()
