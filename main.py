import json
import os
import random
from pathlib import Path

from visualkit.editor import SimpleVideoEditor
from visualkit.media_element import MediaElement


# todo: import from src.utils.transcript_formatter in src codebase
def parse_sentence_transcript(data: dict) -> list[dict]:
    """
    Extracts sentences with their start and end timestamps

    Args:
        data (dict): The json of transcript

    Returns:
        list[dict]: A list of dictionary containing sentence with their start and end timestamps
    """
    if "segments" not in data:
        return []

    ans = []
    for seg in data["segments"]:
        ans.append({"start": seg["start"], "end": seg["end"], "text": seg["text"]})

    return ans


def create_project_from_basic_timestamps_json(
    media_json_path: str,
    transcript_json_path: str,
    media_dir: str = "media",
):
    with open(media_json_path, "r") as f:
        media_data = json.load(f)
    with open(transcript_json_path, "r") as f:
        transcript_data = parse_sentence_transcript(json.load(f))

    project = {
        "config": {
            "width": 1280,
            "height": 720,
            "fps": 30,
            "codec": "H264",
        },
        "assets": {},
        "main_layer": [],
        "subtitle_layers": [],
    }

    # load media assets
    for i, entry in enumerate(media_data):
        media_id = f"media_{i + 1:02d}"
        media_path: Path = Path(media_dir) / entry["file_path"]
        media_type = entry.get("type", "image")
        project["assets"][media_id] = {
            "path": str(media_path),
            "type": media_type,
        }
        # if not first index, add a transition
        if i > 0:
            project["main_layer"].append(
                {
                    "type": "transition",
                    "duration": 1.0,
                    "transition_type": random.choice(["crossfade", "slide_left"]),
                }
            )
        if media_type == "image":
            duration = float(entry["end_time"]) - float(entry["start_time"])
            project["main_layer"].append(
                {
                    "type": "media",
                    "media": media_id,
                    "duration": duration,
                    "effect": entry.get(
                        "effect", random.choice(MediaElement.get_available_effects())
                    ),  # todo: select randomly if not specified dynamically
                }
            )
        elif media_type == "video":
            # todo: handle video asset properly
            project["main_layer"].append(
                {
                    "type": "media",
                    "media": media_id,
                    "duration": entry.get("duration", 5.0),
                }
            )

    # transcript elements for subtitle layers
    subtitle_layer = {
        "name": "main_subtitles",
        "elements": [],
    }

    for seg in transcript_data:
        subtitle_layer["elements"].append(
            {
                "start_time": seg["start"],
                "end_time": seg["end"],
                "text": seg["text"],
                "animation_type": "typewriter",
            }
        )

    project["subtitle_layers"].append(subtitle_layer)

    return project


def create_test_project():
    return {
        "config": {"width": 1280, "height": 720, "fps": 30, "codec": "H264"},
        "assets": {
            "img1": {"path": "generated_images/image_01.jpg", "type": "image"},
            "img2": {"path": "generated_images/image_02.jpg", "type": "image"},
            "img3": {"path": "generated_images/image_03.jpg", "type": "image"},
            "vid1": {"path": "data/test1.mp4", "type": "video"},
        },
        "main_layer": [
            {"type": "media", "media": "img1", "duration": 5.0, "effect": "zoom"},
            {"type": "transition", "duration": 1.0, "transition_type": "crossfade"},
            {"type": "media", "media": "img2", "duration": 4.0, "effect": "brightness"},
            {"type": "transition", "duration": 1.0, "transition_type": "slide_left"},
            {"type": "media", "media": "img3", "duration": 4.0, "effect": "blur"},
            {"type": "transition", "duration": 1.0, "transition_type": "crossfade"},
            {"type": "media", "media": "vid1", "duration": 5.0, "effect": "none"},
        ],
        "subtitle_layers": [
            {
                "name": "main_subtitles",
                "elements": [
                    {
                        "start_time": 1.0,
                        "end_time": 5.0,
                        "text": "Welcome to our amazing video editor!",
                        "animation_type": "typewriter",
                        "typewriter_speed": 15.0,
                    },
                    {
                        "start_time": 6.5,
                        "end_time": 10.0,
                        "text": "This text fades in smoothly",
                        "animation_type": "fade_in",
                    },
                    {
                        "start_time": 11.0,
                        "end_time": 15.0,
                        "text": "Multiple lines of text work perfectly! This is a longer subtitle that will wrap automatically.",
                        "animation_type": "typewriter",
                        # "typewriter_speed": 25.0,
                    },
                ],
            }
        ],
    }


def test_simple_editor():
    print("=== Testing Simple Video Editor ===")

    project = create_test_project()

    # project = create_project_from_basic_timestamps_json(
    #     "prompts.json", "test.json", "generated_images"
    # )
    # print(json.dumps(project, indent=2))
    with open("simple_editor_test.json", "w") as f:
        json.dump(project, f, indent=2)
    with open("simple_editor_test.json", "w") as f:
        json.dump(project, f, indent=2)
    resolutions = [
        (854, 480),
        # (480, 854),
    ]
    for width, height in resolutions:
        orientation = "Vertical" if height > width else "Landscape"
        print(f"\n--- Testing {width}x{height} ({orientation}) ---")
        project["config"]["width"] = width
        project["config"]["height"] = height
        editor = SimpleVideoEditor()
        editor.load_from_json(project)
        test_times = [2.5, 7.0, 12.0]
        for test_time in test_times:
            test_frame = editor.render_frame(test_time)
            print(f"✓ Frame rendered at {test_time}s: {test_frame.shape}")
        output_path = f"simple_test_{width}x{height}.mp4"
        success = editor.render_video(output_path)
        if success:
            print(f"✓ Video rendered: {output_path}")
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"File size: {file_size / (1024 * 1024):.1f} MB")
        else:
            print(f"✗ Failed to render: {output_path}")
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    test_simple_editor()
