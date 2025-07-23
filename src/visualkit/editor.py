from typing import Any, Dict

import cv2
import numpy as np

from visualkit.config import VideoConfig
from visualkit.enums import AnimationType
from visualkit.media_element import MediaElement
from visualkit.text_element import SubtitleElement, TextRenderer
from visualkit.timeline import Timeline
from visualkit.transitions import TransitionElement
from visualkit.utils import logger


class SimpleVideoEditor:
    def __init__(self, config: VideoConfig | None = None):
        self.config = config or VideoConfig()
        self.text_renderer = TextRenderer(self.config)
        self.timeline = Timeline()
        self.subtitle_elements = []

    def load_from_json(self, json_data: Dict[str, Any]):
        try:
            config_data = json_data.get("config", {})
            self.config.width = config_data.get("width", self.config.width)
            self.config.height = config_data.get("height", self.config.height)
            self.config.fps = config_data.get("fps", self.config.fps)
            self.config.codec = config_data.get("codec", self.config.codec)
            self.config.resize_method = config_data.get(
                "resize_method", self.config.resize_method
            )
            self.config.__post_init__()
            self.text_renderer = TextRenderer(self.config)
            assets = json_data.get("assets", {})
            main_layer = json_data.get("main_layer", [])
            current_time = 0.0
            for element_data in main_layer:
                element_type = element_data.get("type")
                if element_type == "media":
                    media_id = element_data.get("media")
                    duration = element_data.get("duration", 5.0)
                    effect = element_data.get("effect", "none")
                    if media_id in assets:
                        asset_path = assets[media_id]["path"]
                        try:
                            media_element = MediaElement(asset_path, duration, effect)
                            self.timeline.add_element(
                                media_element, current_time, current_time + duration
                            )
                            current_time += duration
                        except Exception as e:
                            logger.error(f"Failed to load media {asset_path}: {e}")
                            continue
                elif element_type == "transition":
                    duration = element_data.get("duration", 1.0)
                    transition_type = element_data.get("transition_type", "crossfade")
                    try:
                        transition_element = TransitionElement(
                            duration, transition_type
                        )
                        self.timeline.add_element(
                            transition_element, current_time, current_time + duration
                        )
                        current_time += duration
                    except Exception as e:
                        logger.error(f"Failed to create transition: {e}")
                        continue
            subtitle_layers = json_data.get("subtitle_layers", [])
            for layer_data in subtitle_layers:
                for subtitle_data in layer_data.get("elements", []):
                    try:
                        start_time = self._parse_time(
                            subtitle_data.get("start_time", 0)
                        )
                        end_time = self._parse_time(subtitle_data.get("end_time", 5))
                        text = subtitle_data.get("text", "")
                        animation_type = AnimationType(
                            subtitle_data.get("animation_type", "typewriter")
                        )
                        typewriter_speed = subtitle_data.get("typewriter_speed", 20.0)
                        subtitle = SubtitleElement(
                            start_time, end_time, text, animation_type, typewriter_speed
                        )
                        self.subtitle_elements.append(subtitle)
                    except Exception as e:
                        logger.error(f"Failed to create subtitle: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error loading project: {e}")
            raise

    def _parse_time(self, time_str) -> float:
        if isinstance(time_str, (int, float)):
            return float(time_str)
        if ":" in str(time_str):
            try:
                parts = str(time_str).split(":")
                if len(parts) == 2:
                    minutes = int(parts[0])
                    seconds = int(parts[1])
                    return minutes * 60 + seconds
            except ValueError:
                pass
        return float(time_str)

    def get_duration(self) -> float:
        return self.timeline.get_duration()

    def render_frame(self, timestamp: float) -> np.ndarray:
        frame = np.zeros((self.config.height, self.config.width, 3), dtype=np.uint8)
        active_element_info = self.timeline.get_active_element(timestamp)
        if active_element_info:
            element = active_element_info["element"]
            local_time = timestamp - active_element_info["start_time"]
            if isinstance(element, MediaElement):
                frame = element.get_frame(local_time, self.config)
            elif isinstance(element, TransitionElement):
                prev_info = self.timeline.get_previous_media_element(
                    active_element_info["start_time"]
                )
                next_info = self.timeline.get_next_media_element(
                    active_element_info["end_time"]
                )
                prev_frame = frame
                next_frame = frame
                if prev_info:
                    prev_frame = prev_info["element"].get_frame(
                        prev_info["element"].duration - 0.001, self.config
                    )
                if next_info:
                    next_frame = next_info["element"].get_frame(0.001, self.config)
                frame = element.apply(prev_frame, next_frame, local_time)
        for subtitle in self.subtitle_elements:
            frame = self.text_renderer.render_subtitle(frame, subtitle, timestamp)
        return frame

    def render_video(self, output_path: str, show_progress: bool = True) -> bool:
        duration = self.get_duration()
        if duration <= 0:
            logger.error("Project has no duration")
            return False
        total_frames = int(duration * self.config.fps)
        if total_frames <= 0:
            logger.error("Invalid frame count")
            return False
        fourcc = cv2.VideoWriter_fourcc(*self.config.codec)
        out = cv2.VideoWriter(
            output_path,
            fourcc,
            self.config.fps,
            (self.config.width, self.config.height),
        )
        if not out.isOpened():
            logger.error(f"Could not open video writer for {output_path}")
            return False
        try:
            for frame_idx in range(total_frames):
                timestamp = frame_idx / self.config.fps
                frame = self.render_frame(timestamp)
                if frame.shape[:2] != (self.config.height, self.config.width):
                    frame = cv2.resize(
                        frame,
                        (self.config.width, self.config.height),
                        interpolation=cv2.INTER_AREA,
                    )
                out.write(frame)
                if show_progress and frame_idx % 30 == 0:
                    progress = (frame_idx + 1) / total_frames
                    print(f"\rRendering: {progress:.1%}", end="", flush=True)
            if show_progress:
                print("\nRendering complete!")
            return True
        except Exception as e:
            logger.error(f"Error during rendering: {e}")
            return False
        finally:
            out.release()
            self.cleanup()

    def cleanup(self):
        for elem_info in self.timeline.elements:
            if isinstance(elem_info["element"], MediaElement):
                elem_info["element"].cleanup()
