import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class VideoConfig:
    width: int = 1280
    height: int = 720
    fps: int = 30
    codec: str = "H264"  # Changed to H264 for better compatibility

    def __post_init__(self):
        """Validate configuration parameters"""
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Width and height must be positive")
        if self.fps <= 0:
            raise ValueError("FPS must be positive")


class AnimationType(Enum):
    TYPEWRITER = "typewriter"
    FADE_IN = "fade_in"
    SIMPLE = "simple"


class SubtitleElement:
    def __init__(
        self,
        start_time: float,
        end_time: float,
        text: str,
        animation_type: AnimationType = AnimationType.TYPEWRITER,
        typewriter_speed: float = 20.0,
    ):
        if start_time < 0 or end_time < 0:
            raise ValueError("Times must be non-negative")
        if start_time >= end_time:
            raise ValueError("Start time must be less than end time")
        if typewriter_speed <= 0:
            raise ValueError("Typewriter speed must be positive")

        self.start_time = start_time
        self.end_time = end_time
        self.text = text
        self.animation_type = animation_type
        self.typewriter_speed = typewriter_speed
        self._wrapped_text_cache = None
        self._cache_max_width = None

    def is_active(self, timestamp: float) -> bool:
        return self.start_time <= timestamp <= self.end_time

    def get_typewriter_progress(self, timestamp: float) -> float:
        if timestamp < self.start_time or len(self.text) == 0:
            return 0.0
        elapsed = timestamp - self.start_time
        chars_revealed = elapsed * self.typewriter_speed
        return min(chars_revealed / len(self.text), 1.0)

    def get_fade_progress(self, timestamp: float) -> float:
        if not self.is_active(timestamp):
            return 0.0
        duration = self.end_time - self.start_time
        if duration <= 0:
            return 1.0
        return (timestamp - self.start_time) / duration


class TextRenderer:
    def __init__(self, config: VideoConfig):
        self.config = config
        self.font = cv2.FONT_HERSHEY_SIMPLEX
        self.font_scale = 1.0
        self.thickness = 2
        self.outline_thickness = 4
        self.background_color = (0, 0, 0)
        self.background_opacity = 0.85
        self.complete_text_color = (180, 180, 180)
        self.active_text_color = (255, 255, 0)
        self.outline_color = (0, 0, 0)
        self.margin = 60
        self.line_spacing = 8
        self.corner_radius = 15
        self.background_padding = 20

    def _wrap_text(self, text: str, max_width: int) -> List[str]:
        if not text:
            return []
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            (text_width, _), _ = cv2.getTextSize(
                test_line, self.font, self.font_scale, self.thickness
            )
            if text_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def _get_text_dimensions(self, lines: List[str]) -> Tuple[int, int]:
        if not lines:
            return 0, 0
        max_width = 0
        total_height = 0
        for i, line in enumerate(lines):
            (text_width, text_height), baseline = cv2.getTextSize(
                line, self.font, self.font_scale, self.thickness
            )
            max_width = max(max_width, text_width)
            total_height += text_height + (self.line_spacing if i > 0 else 0)
        return max_width, total_height

    def _get_text_position(
        self,
        text: str,
        line_index: int = 0,
        total_lines: int = 1,
        text_y_start: int = 0,
    ) -> Tuple[int, int]:
        (text_width, text_height), baseline = cv2.getTextSize(
            text, self.font, self.font_scale, self.thickness
        )
        x = (self.config.width - text_width) // 2
        line_height = text_height + self.line_spacing
        y = text_y_start + text_height + (line_index * line_height)
        return x, y

    def _draw_rounded_rectangle(
        self,
        img: np.ndarray,
        pt1: Tuple[int, int],
        pt2: Tuple[int, int],
        color: Tuple[int, int, int],
        radius: int = 10,
    ):
        x1, y1 = pt1
        x2, y2 = pt2
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
        if radius <= 0:
            cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
            return
        cv2.rectangle(img, (x1, y1 + radius), (x2, y2 - radius), color, -1)
        cv2.rectangle(img, (x1 + radius, y1), (x2 - radius, y2), color, -1)
        cv2.circle(img, (x1 + radius, y1 + radius), radius, color, -1)
        cv2.circle(img, (x2 - radius, y1 + radius), radius, color, -1)
        cv2.circle(img, (x1 + radius, y2 - radius), radius, color, -1)
        cv2.circle(img, (x2 - radius, y2 - radius), radius, color, -1)

    def _draw_background(self, frame: np.ndarray, lines: List[str]):
        if not lines:
            return
        text_width, text_height = self._get_text_dimensions(lines)
        x_center = self.config.width // 2
        y_bottom = self.config.height - self.margin
        x1 = max(0, x_center - text_width // 2 - self.background_padding)
        x2 = min(
            self.config.width, x_center + text_width // 2 + self.background_padding
        )
        y1 = max(0, y_bottom - text_height - self.background_padding)
        y2 = min(self.config.height, y_bottom + self.background_padding)
        overlay = frame.copy()
        self._draw_rounded_rectangle(
            overlay, (x1, y1), (x2, y2), self.background_color, self.corner_radius
        )
        cv2.addWeighted(
            overlay,
            self.background_opacity,
            frame,
            1 - self.background_opacity,
            0,
            frame,
        )

    def _draw_text_with_outline(
        self,
        frame: np.ndarray,
        text: str,
        position: Tuple[int, int],
        color: Tuple[int, int, int],
        outline_color: Tuple[int, int, int],
    ):
        x, y = position
        cv2.putText(
            frame,
            text,
            (x, y),
            self.font,
            self.font_scale,
            outline_color,
            self.outline_thickness,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            text,
            (x, y),
            self.font,
            self.font_scale,
            color,
            self.thickness,
            cv2.LINE_AA,
        )

    def render_subtitle(
        self, frame: np.ndarray, subtitle: SubtitleElement, timestamp: float
    ) -> np.ndarray:
        if not subtitle.is_active(timestamp):
            return frame
        max_width = self.config.width - (2 * self.background_padding) - 100
        if (
            subtitle._wrapped_text_cache is None
            or subtitle._cache_max_width != max_width
        ):
            subtitle._wrapped_text_cache = self._wrap_text(subtitle.text, max_width)
            subtitle._cache_max_width = max_width
        lines = subtitle._wrapped_text_cache
        if not lines:
            return frame
        self._draw_background(frame, lines)  # Uncomment if background is needed
        text_width, text_height = self._get_text_dimensions(lines)
        text_y_start = self.config.height - self.margin - text_height
        total_chars = sum(len(line) for line in lines)
        if subtitle.animation_type == AnimationType.TYPEWRITER:
            progress = subtitle.get_typewriter_progress(timestamp)
            chars_to_show = int(total_chars * progress)
        else:
            chars_to_show = total_chars
        char_offset = 0
        for line_idx, line in enumerate(lines):
            position = self._get_text_position(line, line_idx, len(lines), text_y_start)
            if subtitle.animation_type == AnimationType.TYPEWRITER:
                self._render_typewriter_line(
                    frame, line, position, chars_to_show, char_offset
                )
            elif subtitle.animation_type == AnimationType.FADE_IN:
                fade_progress = subtitle.get_fade_progress(timestamp)
                self._render_fade_line(frame, line, position, fade_progress)
            else:
                self._render_simple_line(frame, line, position)
            char_offset += len(line)
        return frame

    def _render_typewriter_line(
        self,
        frame: np.ndarray,
        line: str,
        position: Tuple[int, int],
        chars_to_show: int,
        char_offset: int,
    ):
        self._draw_text_with_outline(
            frame, line, position, self.complete_text_color, self.outline_color
        )
        line_start = char_offset
        if chars_to_show > line_start:
            active_chars_in_line = min(chars_to_show - line_start, len(line))
            if active_chars_in_line > 0:
                active_text = line[:active_chars_in_line]
                self._draw_text_with_outline(
                    frame,
                    active_text,
                    position,
                    self.active_text_color,
                    self.outline_color,
                )

    def _render_fade_line(
        self, frame: np.ndarray, line: str, position: Tuple[int, int], progress: float
    ):
        opacity = min(1.0, progress * 2)
        overlay = frame.copy()
        self._draw_text_with_outline(
            overlay, line, position, self.active_text_color, self.outline_color
        )
        cv2.addWeighted(overlay, opacity, frame, 1 - opacity, 0, frame)

    def _render_simple_line(
        self, frame: np.ndarray, line: str, position: Tuple[int, int]
    ):
        self._draw_text_with_outline(
            frame, line, position, self.active_text_color, self.outline_color
        )


import math

import numpy as np


class MediaElement:
    def __init__(self, asset_path: str, duration: float, effect_type: str = "none"):
        if not os.path.exists(asset_path):
            raise FileNotFoundError(f"Media file not found: {asset_path}")
        if duration <= 0:
            raise ValueError("Duration must be positive")
        self.asset_path = asset_path
        self.duration = duration
        self.effect_type = effect_type
        self._cached_frame = None
        self._last_timestamp = -1
        self._last_effect_frame = None
        self._cap = None  # For video sources

    @staticmethod
    def get_available_effects():
        """Return a list of all available effects"""
        return [
            "none",
            "zoom",
            "brightness",
            "blur",
            "pan_left",
            "pan_right",
            "pan_up",
            "pan_down",
            "zoom_out",
            "rotate_clockwise",
            "rotate_counterclockwise",
            "shake",
            "bounce",
            "pulse",
            "fade_in",
            "fade_out",
            "spiral",
        ]

    def get_frame(self, timestamp: float, config: VideoConfig) -> np.ndarray:
        try:
            if self._cached_frame is None:
                self._load_and_resize_with_aspect_ratio(config)
            if (
                self._last_effect_frame is None
                or abs(timestamp - self._last_timestamp) > 0.01
            ):
                frame = self._cached_frame.copy()
                if frame.shape[:2] != (
                    config.height,
                    config.width,
                ):  # Validate dimensions
                    frame = cv2.resize(
                        frame,
                        (config.width, config.height),
                        interpolation=cv2.INTER_AREA,
                    )
                frame = self._apply_effect(frame, timestamp, config)
                self._last_effect_frame = frame
                self._last_timestamp = timestamp
            return self._last_effect_frame.copy()
        except Exception as e:
            logger.error(f"Error getting frame from {self.asset_path}: {e}")
            return np.zeros((config.height, config.width, 3), dtype=np.uint8)

    def _load_and_resize_with_aspect_ratio(self, config: VideoConfig):
        try:
            if self.asset_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                original_frame = cv2.imread(self.asset_path)
            else:
                if self._cap is None:
                    self._cap = cv2.VideoCapture(self.asset_path)
                ret, original_frame = self._cap.read()
                if not ret:
                    raise ValueError("Could not read video file")
            if original_frame is None:
                raise ValueError("Could not load media file")

            # Store original frame at higher resolution for movement effects
            original_h, original_w = original_frame.shape[:2]
            target_w, target_h = config.width, config.height

            # Create a larger frame for movement effects (1.5x size)
            enlarged_w = int(target_w * 1.5)
            enlarged_h = int(target_h * 1.5)

            original_aspect = original_w / original_h
            enlarged_aspect = enlarged_w / enlarged_h

            if original_aspect > enlarged_aspect:
                new_h = enlarged_h
                new_w = int(enlarged_h * original_aspect)
            else:
                new_w = enlarged_w
                new_h = int(enlarged_w / original_aspect)

            resized = cv2.resize(
                original_frame, (new_w, new_h), interpolation=cv2.INTER_AREA
            )

            # Center crop to enlarged size
            y_offset = max(0, (new_h - enlarged_h) // 2)
            x_offset = max(0, (new_w - enlarged_w) // 2)
            cropped = resized[
                y_offset : y_offset + enlarged_h, x_offset : x_offset + enlarged_w
            ]

            # Pad if needed
            if cropped.shape[:2] != (enlarged_h, enlarged_w):
                padded = np.zeros((enlarged_h, enlarged_w, 3), dtype=np.uint8)
                y_start = (enlarged_h - cropped.shape[0]) // 2
                x_start = (enlarged_w - cropped.shape[1]) // 2
                padded[
                    y_start : y_start + cropped.shape[0],
                    x_start : x_start + cropped.shape[1],
                ] = cropped
                self._cached_frame = padded
            else:
                self._cached_frame = cropped

        except Exception as e:
            logger.error(f"Error loading media {self.asset_path}: {e}")
            # Create enlarged black frame
            enlarged_w = int(config.width * 1.5)
            enlarged_h = int(config.height * 1.5)
            self._cached_frame = np.zeros((enlarged_h, enlarged_w, 3), dtype=np.uint8)

    def _apply_effect(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply the specified effect to the frame"""
        if self.effect_type == "zoom":
            return self._apply_zoom(frame, timestamp, config)
        if self.effect_type == "brightness":
            return self._apply_brightness(frame, timestamp, config)
        if self.effect_type == "blur":
            return self._apply_blur(frame, timestamp, config)
        if self.effect_type == "pan_left":
            return self._apply_pan_left(frame, timestamp, config)
        if self.effect_type == "pan_right":
            return self._apply_pan_right(frame, timestamp, config)
        if self.effect_type == "pan_up":
            return self._apply_pan_up(frame, timestamp, config)
        if self.effect_type == "pan_down":
            return self._apply_pan_down(frame, timestamp, config)
        if self.effect_type == "zoom_out":
            return self._apply_zoom_out(frame, timestamp, config)
        if self.effect_type == "rotate_clockwise":
            return self._apply_rotate_clockwise(frame, timestamp, config)
        if self.effect_type == "rotate_counterclockwise":
            return self._apply_rotate_counterclockwise(frame, timestamp, config)
        if self.effect_type == "shake":
            return self._apply_shake(frame, timestamp, config)
        if self.effect_type == "bounce":
            return self._apply_bounce(frame, timestamp, config)
        if self.effect_type == "pulse":
            return self._apply_pulse(frame, timestamp, config)
        if self.effect_type == "fade_in":
            return self._apply_fade_in(frame, timestamp, config)
        if self.effect_type == "fade_out":
            return self._apply_fade_out(frame, timestamp, config)
        if self.effect_type == "spiral":
            return self._apply_spiral(frame, timestamp, config)
        return self._crop_to_target(frame, config)

    def _crop_to_target(self, frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """Crop the frame to target dimensions"""
        h, w = frame.shape[:2]
        target_h, target_w = config.height, config.width

        start_y = (h - target_h) // 2
        start_x = (w - target_w) // 2

        # Ensure we don't go out of bounds
        start_y = max(0, min(start_y, h - target_h))
        start_x = max(0, min(start_x, w - target_w))

        cropped = frame[start_y : start_y + target_h, start_x : start_x + target_w]

        if cropped.shape[:2] != (target_h, target_w):
            cropped = cv2.resize(
                cropped, (target_w, target_h), interpolation=cv2.INTER_AREA
            )

        return cropped

    def _apply_zoom(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        scale = 1.0 + (0.3 * progress)
        return self._scale_and_crop(frame, scale, config)

    def _apply_zoom_out(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        scale = 1.3 - (0.3 * progress)
        return self._scale_and_crop(frame, scale, config)

    def _apply_brightness(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        brightness = 30 * progress
        frame_float = frame.astype(np.float32)
        bright_frame = frame_float + brightness
        result = np.clip(bright_frame, 0, 255).astype(np.uint8)
        return self._crop_to_target(result, config)

    def _apply_blur(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        kernel_size = max(1, int(5 * progress))
        if kernel_size % 2 == 0:
            kernel_size += 1
        result = cv2.GaussianBlur(frame, (kernel_size, kernel_size), 0)
        return self._crop_to_target(result, config)

    def _apply_pan_left(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Pan from right to left (start at right edge, end at left edge)
        x_offset = int(max_x_movement * (1 - progress))

        # Center vertically
        y_offset = max_y_movement // 2

        # Ensure we don't go out of bounds
        x_offset = max(0, min(x_offset, max_x_movement))
        y_offset = max(0, min(y_offset, max_y_movement))

        # Extract the target region
        cropped = frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

        return cropped

    def _apply_pan_right(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Pan from left to right (start at left edge, end at right edge)
        x_offset = int(max_x_movement * progress)

        # Center vertically
        y_offset = max_y_movement // 2

        # Ensure we don't go out of bounds
        x_offset = max(0, min(x_offset, max_x_movement))
        y_offset = max(0, min(y_offset, max_y_movement))

        # Extract the target region
        cropped = frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

        return cropped

    def _apply_pan_up(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Pan from bottom to top (start at bottom edge, end at top edge)
        y_offset = int(max_y_movement * (1 - progress))

        # Center horizontally
        x_offset = max_x_movement // 2

        # Ensure we don't go out of bounds
        y_offset = max(0, min(y_offset, max_y_movement))
        x_offset = max(0, min(x_offset, max_x_movement))

        # Extract the target region
        cropped = frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

        return cropped

    def _apply_pan_down(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Pan from top to bottom (start at top edge, end at bottom edge)
        y_offset = int(max_y_movement * progress)

        # Center horizontally
        x_offset = max_x_movement // 2

        # Ensure we don't go out of bounds
        y_offset = max(0, min(y_offset, max_y_movement))
        x_offset = max(0, min(x_offset, max_x_movement))

        # Extract the target region
        cropped = frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

        return cropped

    def _apply_rotate_clockwise(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        angle = 15 * progress  # Rotate up to 15 degrees
        return self._rotate_and_crop(frame, angle, config)

    def _apply_rotate_counterclockwise(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)
        angle = -15 * progress  # Rotate up to -15 degrees
        return self._rotate_and_crop(frame, angle, config)

    def _apply_shake(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        # Create shake effect with random offsets
        shake_intensity = 20  # Increased intensity
        frequency = 30  # Shake frequency

        # Use different frequencies for x and y to create more realistic shake
        x_offset = int(shake_intensity * math.sin(timestamp * frequency))
        y_offset = int(shake_intensity * math.cos(timestamp * frequency * 1.3))

        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Calculate center position
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        # Apply shake offset from center
        start_x = center_x + x_offset
        start_y = center_y + y_offset

        # Ensure we don't go out of bounds
        start_x = max(0, min(start_x, max_x_movement))
        start_y = max(0, min(start_y, max_y_movement))

        # Extract the shaken region
        cropped = frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

        return cropped

    def _apply_bounce(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        # Create bouncing effect using sine wave
        bounce_height = 60  # Increased bounce height
        bounce_frequency = 1.5  # bounces per second

        # Use timestamp directly for continuous bouncing
        bounce_offset = int(
            bounce_height * abs(math.sin(timestamp * bounce_frequency * math.pi))
        )

        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Calculate center position
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        # Apply bounce offset (moving up and down from center)
        start_y = center_y - bounce_offset
        start_x = center_x

        # Ensure we don't go out of bounds
        start_y = max(0, min(start_y, max_y_movement))
        start_x = max(0, min(start_x, max_x_movement))

        # Extract the bounced region
        cropped = frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

        return cropped

    def _apply_fade_in(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)

        # Create black background
        result = np.zeros((config.height, config.width, 3), dtype=np.uint8)

        # Get the frame portion
        frame_cropped = self._crop_to_target(frame, config)

        # Apply fade
        alpha = progress
        result = cv2.addWeighted(result, 1 - alpha, frame_cropped, alpha, 0)

        return result

    def _apply_fade_out(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)

        # Create black background
        result = np.zeros((config.height, config.width, 3), dtype=np.uint8)

        # Get the frame portion
        frame_cropped = self._crop_to_target(frame, config)

        # Apply fade
        alpha = 1 - progress
        result = cv2.addWeighted(result, 1 - alpha, frame_cropped, alpha, 0)

        return result

    def _apply_spiral(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        progress = min(1.0, timestamp / self.duration)

        # Combine rotation with zoom
        angle = 180 * progress
        scale = 1.0 + 0.3 * progress

        # Apply rotation first
        rotated = self._rotate_frame(frame, angle)

        # Then apply scale
        return self._scale_and_crop(rotated, scale, config)

    def _scale_and_crop(
        self, frame: np.ndarray, scale: float, config: VideoConfig
    ) -> np.ndarray:
        """Scale frame and crop to target dimensions"""
        if scale <= 0:
            scale = 1.0

        h, w = frame.shape[:2]
        new_h, new_w = int(h * scale), int(w * scale)

        if new_h <= 0 or new_w <= 0:
            return self._crop_to_target(frame, config)

        scaled = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Crop to target size
        start_y = max(0, (new_h - config.height) // 2)
        start_x = max(0, (new_w - config.width) // 2)

        end_y = min(new_h, start_y + config.height)
        end_x = min(new_w, start_x + config.width)

        cropped = scaled[start_y:end_y, start_x:end_x]

        # Ensure exact dimensions
        if cropped.shape[:2] != (config.height, config.width):
            cropped = cv2.resize(
                cropped, (config.width, config.height), interpolation=cv2.INTER_AREA
            )

        return cropped

    def _rotate_frame(self, frame: np.ndarray, angle: float) -> np.ndarray:
        """Rotate frame by given angle"""
        h, w = frame.shape[:2]
        center = (w // 2, h // 2)

        # Get rotation matrix
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

        # Apply rotation
        rotated = cv2.warpAffine(frame, rotation_matrix, (w, h))

        return rotated

    def _rotate_and_crop(
        self, frame: np.ndarray, angle: float, config: VideoConfig
    ) -> np.ndarray:
        """Rotate frame and crop to target dimensions"""
        rotated = self._rotate_frame(frame, angle)
        return self._crop_to_target(rotated, config)

    def cleanup(self):
        self._cached_frame = None
        self._last_effect_frame = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class TransitionElement:
    def __init__(self, duration: float, transition_type: str = "crossfade"):
        if duration <= 0:
            raise ValueError("Transition duration must be positive")
        self.duration = duration
        self.transition_type = transition_type

    def apply(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, timestamp: float
    ) -> np.ndarray:
        if prev_frame.shape != next_frame.shape:
            logger.warning("Frame shape mismatch in transition, resizing next frame")
            next_frame = cv2.resize(
                next_frame,
                (prev_frame.shape[1], prev_frame.shape[0]),
                interpolation=cv2.INTER_AREA,
            )
        progress = min(1.0, max(0.0, timestamp / self.duration))
        if self.transition_type == "crossfade":
            return self._crossfade(prev_frame, next_frame, progress)
        if self.transition_type == "slide_left":
            return self._slide_left(prev_frame, next_frame, progress)
        return next_frame

    def _crossfade(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        prev_float = prev_frame.astype(np.float32)
        next_float = next_frame.astype(np.float32)
        result = prev_float * (1 - progress) + next_float * progress
        return np.clip(result, 0, 255).astype(np.uint8)

    def _slide_left(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        split_point = int(w * progress)
        result = prev_frame.copy()
        if split_point > 0:
            result[:, :split_point] = next_frame[:, :split_point]
        return result


class Timeline:
    def __init__(self):
        self.elements = []

    def add_element(self, element, start_time: float, end_time: float):
        if start_time >= end_time:
            raise ValueError("Start time must be less than end time")
        self.elements.append(
            {"element": element, "start_time": start_time, "end_time": end_time}
        )
        self.elements.sort(key=lambda x: x["start_time"])

    def get_active_element(self, timestamp: float):
        for elem_info in self.elements:
            if elem_info["start_time"] <= timestamp <= elem_info["end_time"]:
                return elem_info
        return None

    def get_duration(self) -> float:
        if not self.elements:
            return 0.0
        return max(elem["end_time"] for elem in self.elements)

    def get_previous_media_element(self, current_start_time: float):
        candidates = []
        for elem_info in self.elements:
            if elem_info["end_time"] <= current_start_time and isinstance(
                elem_info["element"], MediaElement
            ):
                candidates.append(elem_info)
        if candidates:
            return max(candidates, key=lambda x: x["end_time"])
        return None

    def get_next_media_element(self, current_end_time: float):
        candidates = []
        for elem_info in self.elements:
            if elem_info["start_time"] >= current_end_time and isinstance(
                elem_info["element"], MediaElement
            ):
                candidates.append(elem_info)
        if candidates:
            return min(candidates, key=lambda x: x["start_time"])
        return None


class SimpleVideoEditor:
    def __init__(self, config: VideoConfig = None):
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


import random
from pathlib import Path


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




def test_all_media_effects():
    test_dir = "test_media_effects"
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)

    image_path = "generated_images/image_01.jpg"

    # Check if test image exists
    if not os.path.exists(image_path):
        print(f"Error: Test image not found at {image_path}")
        return

    print("=== Testing All Media Effects ===")

    # Create a simple video config
    config = VideoConfig(width=854, height=480, fps=30)

    for effect in MediaElement.get_available_effects():
        print(f"Testing effect: {effect}")

        try:
            # Create MediaElement with the effect
            media_element = MediaElement(image_path, duration=5.0, effect_type=effect)

            # Create a short video showing the effect
            video_filename = f"{effect}_effect.mp4"
            video_path = os.path.join(test_dir, video_filename)

            # Create video writer
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(
                video_path, fourcc, 10.0, (config.width, config.height)
            )

            if out.isOpened():
                # Generate 50 frames (5 seconds at 10 fps)
                for frame_idx in range(50):
                    timestamp = frame_idx / 10.0  # 10 fps
                    frame = media_element.get_frame(timestamp, config)
                    out.write(frame)

                out.release()
                print(f"  ✓ Created video: {video_filename}")
            else:
                print(f"  ✗ Failed to create video: {video_filename}")

            # Cleanup
            media_element.cleanup()

        except Exception as e:
            print(f"  ✗ Error testing effect '{effect}': {e}")

        print()  # Empty line for readability

    print("=== All Effects Testing Complete ===")
    print(f"Results saved in: {test_dir}")


if __name__ == "__main__":
    # test_simple_editor()
    test_all_media_effects()
