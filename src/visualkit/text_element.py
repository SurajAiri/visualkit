from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from visualkit.config import VideoConfig
from visualkit.enums import AnimationType


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
