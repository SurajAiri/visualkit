"""Example 2: Coded Visuals (HTML/CSS/JS Infographics & Dynamic Variables)

Demonstrates:
- Creating a CodedVisualClip referencing an external HTML template.
- Declaring and inspecting variables (required, labels, descriptions for AI agents).
- Injecting dynamic values into Jinja-like {{ placeholders }} and window.__VARIABLES__.
- Rendering the infographic animation into an MP4 video asset using headless Chrome + FFmpeg.
- Compiling and placing the rendered visual onto a timeline.
"""

from pathlib import Path

import visualkit as vk
from visualkit.coded_visual.compiler import CodedVisualCompiler


def main():
    print("=== VisualKit Example 2: Coded Visuals & Infographics ===")

    template_path = Path(__file__).parent / "assets" / "infographic.html"

    # 1. Create a CodedVisualClip with variable definitions
    clip = vk.CodedVisualClip(
        id="stat_card",
        source=str(template_path),
        timeline_start=vk.Time.from_seconds(1),
        duration=vk.Time.from_seconds(4),
        variables={
            "title": vk.Variable(
                name="title",
                label="Card Title",
                description="Short header text for the statistic",
                required=True,
                value="Global Active Users",
            ),
            "value": vk.Variable(
                name="value",
                label="Metric Value",
                description="The highlighted numerical statistic",
                required=True,
                value="10.5M",
            ),
            "subtitle": vk.Variable(
                name="subtitle",
                label="Subtitle",
                description="Secondary context line",
                default="Updated this quarter",
            ),
        },
    )

    # 2. Inspect variable state (useful for UI builders & AI agents)
    print("Set variables:             ", list(clip.get_set_variables().keys()))
    print("Unset variables:           ", list(clip.get_unset_variables().keys()))
    print("Missing required variables:", clip.get_missing_required_variables())
    print(f"Canvas size:                {clip.canvas_size.width}x{clip.canvas_size.height}")
    print(f"Aspect ratio:               {clip.aspect_ratio}")

    # 3. Render directly to a standalone MP4 video using the compiler
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    video_out = out_dir / "stat_card.mp4"

    compiler = CodedVisualCompiler()
    print("Rendering coded visual to video with headless Chrome + FFmpeg...")
    rendered_path = compiler.render_to_video(clip, output_path=video_out, fps=30.0)
    print(f"Rendered video saved to: {rendered_path}")

    # 4. Integrate into a timeline and flatten into a concrete MediaClip
    timeline = vk.Timeline()
    timeline.add_clip(clip)

    flattened = timeline.flatten(render_video=True)
    resolved_clip = flattened.video_tracks[0].clips[0]
    print(f"Flattened clip type: {resolved_clip.clip_type}")
    print(f"Resolved media source: {resolved_clip.source.source}")


if __name__ == "__main__":
    main()
