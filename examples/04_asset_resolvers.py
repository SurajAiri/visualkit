"""Example 4: Asset Resolvers for Decoupled Cloud / Dynamic Asset Management

Demonstrates:
- Using abstract asset references (e.g. 'asset://broll_01', 'asset://voiceover') in clip schemas.
- Keeping timeline metadata decoupled from concrete local paths, CDN URLs, or temporary cache files.
- Providing an AssetResolver or DictAssetResolver at export time to dynamically resolve media paths.
"""

from pathlib import Path

import visualkit as vk
from visualkit.engine import AssetResolver, DictAssetResolver


def main():
    print("=== VisualKit Example 4: Asset Resolvers ===")

    # 1. Create a timeline with abstract asset identifiers
    timeline = vk.Timeline()

    # Video clip with abstract asset URI
    timeline.add_clip(
        vk.MediaClip(
            id="intro_broll",
            source="asset://drone_skyline",
            timeline_start=vk.Time.from_seconds(0),
            duration=vk.Time.from_seconds(5),
        ),
        track_index=0,
    )

    # Audio clip with abstract asset URI
    timeline.add_clip(
        vk.AudioClip(
            id="narration",
            source="asset://vo_intro",
            timeline_start=vk.Time.from_seconds(0.5),
            duration=vk.Time.from_seconds(4),
        ),
        track_index=0,
    )

    print("Timeline created with abstract asset sources:")
    print("  Video clip source:", timeline.video_tracks[0].clips[0].source.source)
    print("  Audio clip source:", timeline.audio_tracks[0].clips[0].source.source)

    # 2. Define an asset resolver map (can be backed by local disk, S3, or a CMS)
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    # Mock sample media files for resolution
    mock_video = out_dir / "sample_drone.mp4"
    mock_audio = out_dir / "sample_vo.wav"
    mock_video.touch(exist_ok=True)
    mock_audio.touch(exist_ok=True)

    resolver = DictAssetResolver(
        {
            "asset://drone_skyline": str(mock_video.resolve()),
            "asset://vo_intro": str(mock_audio.resolve()),
        }
    )

    # 3. Export to DaVinci Resolve with asset resolution
    # DaVinci Resolve XML output will link directly to the resolved physical media URIs!
    output_xml = out_dir / "resolved_project.xml"
    timeline.export_to_resolve(
        output_path=output_xml,
        fps=30.0,
        asset_resolver=resolver,
    )

    print(f"\nExported DaVinci Resolve project with resolved assets: {output_xml}")

    # Read XML to show resolved file path URLs
    xml_content = output_xml.read_text(encoding="utf-8")
    for line in xml_content.splitlines():
        if "<pathurl>" in line:
            print("  Resolve <pathurl>:", line.strip())


if __name__ == "__main__":
    main()
