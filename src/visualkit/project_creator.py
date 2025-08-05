import random
from pathlib import Path

from .media_element import MediaElement
from .transitions import TransitionElement


class ProjectCreator:
    @staticmethod
    def create_project_from_media_and_transcript(
        media: dict,
        transcript: dict,
        media_dir: str = "",
        file_extension: str = "jpg",
        resolution: tuple[int, int] = (720, 1280),
        fps: int = 30,
        codec: str = "avc1",  # Options: avc1, hevc, vp9
        transition_duration: float = 1.0,
        resize_method: str = "fill",  # Options: smart, adaptive, gradual, aspect_ratio
    ):
        """
        Creates a project configuration from media and transcript data.
        Args:
            media (dict): Media assets to include in the project. `media['media']` list of dicts with keys:
                - file_path (str): Path to the media file.
                - start_time (float): Start time of the media in seconds.
                - end_time (float): End time of the media in seconds.
                - type (str): Type of media, e.g., "image" or "video". [optional, default is "image"]

            transcript (dict): Transcript data for subtitles. `transcript['segments']` list of dicts with keys:
                - start (float): Start time of the subtitle in seconds.
                - end (float): End time of the subtitle in seconds.
                - text (str): Text of the subtitle.

            media_dir (str): Directory containing media files.
            file_extension (str): File extension for media files. [default: "jpg"]
            resolution (tuple): Video resolution as (width, height).
            fps (int): Frames per second for the video.
            codec (str): Codec to use for video encoding.
            transition_duration (float): Duration of transitions between media elements.
            resize_method (str): Method to use for resizing images. [adaptive (default)] Options: smart, adaptive, gradual, aspect_ratio.
            Returns:
                dict: Project configuration dictionary.
        """  # noqa: E501

        project = {
            "config": {
                "width": resolution[0],
                "height": resolution[1],
                "fps": fps,
                "codec": codec,
                "resize_method": resize_method,
            },
            "assets": {},
            "main_layer": [],
            "subtitle_layers": [],
        }
        try:
            total_media = len(media["media"])
            # load media assets
            for i, entry in enumerate(media["media"]):
                media_id = f"media_{i + 1:02d}"
                file_path = (
                    entry.get("file_path", None) or f"image_{i}.{file_extension}"
                )
                media_path: str = (
                    file_path
                    if (media_dir is None or media_dir == "")
                    else f"{media_dir}/{file_path}"
                )
                media_type = entry.get("type", "image")
                project["assets"][media_id] = {
                    "path": str(media_path),
                    "type": media_type,
                }
                # if not first index, add a transition
                duration = float(entry["end_time"]) - float(entry["start_time"])
                taken = False

                if i > 0 and duration > 1:
                    project["main_layer"].append(
                        {
                            "type": "transition",
                            "duration": transition_duration,
                            "transition_type": random.choice(
                                TransitionElement.get_available_transitions()
                            ),
                        }
                    )
                    taken = True

                # calculate transition overlapping duration for media element
                sub_duration = 0
                if not taken or total_media == 1:  # Only one media element
                    sub_duration = 0
                elif i == 0 or i == total_media - 1:  # first or last media
                    sub_duration = transition_duration / 2
                else:  # middle media
                    sub_duration = transition_duration

                if media_type == "image":
                    project["main_layer"].append(
                        {
                            "type": "media",
                            "media": media_id,
                            "duration": round(duration - sub_duration, 3),
                            "effect": entry.get(
                                "effect",
                                random.choice(MediaElement.get_moving_effects()),
                            ),
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

            for seg in transcript["sentences"]:
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
        except Exception as e:
            print(f"Error creating project: {e}")
            raise ValueError("Failed to create project") from e
