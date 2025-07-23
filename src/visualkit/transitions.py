import math

import cv2
import numpy as np

from visualkit.utils import logger


class TransitionElement:
    def __init__(self, duration: float, transition_type: str = "crossfade"):
        if duration <= 0:
            raise ValueError("Transition duration must be positive")
        self.duration = duration
        self.transition_type = transition_type

    @staticmethod
    def get_available_transitions():
        """Return a list of all available transitions"""
        return [
            "none",
            "crossfade",
            "slide_left",
            "slide_right",
            "slide_up",
            "slide_down",
            "slide_diagonal",  # little slow
            "wipe_left",
            "wipe_right",
            "wipe_up",
            "wipe_down",
            "wipe_center_out",
            "wipe_center_in",
            "push_left",
            "push_right",
            "push_up",
            "push_down",
            "zoom_in",
            "zoom_out",
            "scale_up",
            "scale_down",
            # "split_vertical", # not working
            # "split_horizontal", # not working
            "venetian_blinds",
            "vertical_blinds",
            "circle_in",
            "circle_out",
            "fade_to_black",
            "fade_to_white",
        ]

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

        # Existing transitions
        if self.transition_type == "crossfade":
            return self._crossfade(prev_frame, next_frame, progress)
        if self.transition_type == "slide_left":
            return self._slide_left(prev_frame, next_frame, progress)

        # New slide transitions
        if self.transition_type == "slide_right":
            return self._slide_right(prev_frame, next_frame, progress)
        if self.transition_type == "slide_up":
            return self._slide_up(prev_frame, next_frame, progress)
        if self.transition_type == "slide_down":
            return self._slide_down(prev_frame, next_frame, progress)
        if self.transition_type == "slide_diagonal":
            return self._slide_diagonal(prev_frame, next_frame, progress)

        # Wipe transitions
        if self.transition_type == "wipe_left":
            return self._wipe_left(prev_frame, next_frame, progress)
        if self.transition_type == "wipe_right":
            return self._wipe_right(prev_frame, next_frame, progress)
        if self.transition_type == "wipe_up":
            return self._wipe_up(prev_frame, next_frame, progress)
        if self.transition_type == "wipe_down":
            return self._wipe_down(prev_frame, next_frame, progress)
        if self.transition_type == "wipe_center_out":
            return self._wipe_center_out(prev_frame, next_frame, progress)
        if self.transition_type == "wipe_center_in":
            return self._wipe_center_in(prev_frame, next_frame, progress)

        # Push transitions
        if self.transition_type == "push_left":
            return self._push_left(prev_frame, next_frame, progress)
        if self.transition_type == "push_right":
            return self._push_right(prev_frame, next_frame, progress)
        if self.transition_type == "push_up":
            return self._push_up(prev_frame, next_frame, progress)
        if self.transition_type == "push_down":
            return self._push_down(prev_frame, next_frame, progress)

        # Zoom/Scale transitions
        if self.transition_type == "zoom_in":
            return self._zoom_in(prev_frame, next_frame, progress)
        if self.transition_type == "zoom_out":
            return self._zoom_out(prev_frame, next_frame, progress)
        if self.transition_type == "scale_up":
            return self._scale_up(prev_frame, next_frame, progress)
        if self.transition_type == "scale_down":
            return self._scale_down(prev_frame, next_frame, progress)

        # Split screen transitions
        if self.transition_type == "split_vertical":
            return self._split_vertical(prev_frame, next_frame, progress)
        if self.transition_type == "split_horizontal":
            return self._split_horizontal(prev_frame, next_frame, progress)
        if self.transition_type == "venetian_blinds":
            return self._venetian_blinds(prev_frame, next_frame, progress)
        if self.transition_type == "vertical_blinds":
            return self._vertical_blinds(prev_frame, next_frame, progress)

        # Circular transitions
        if self.transition_type == "circle_in":
            return self._circle_in(prev_frame, next_frame, progress)
        if self.transition_type == "circle_out":
            return self._circle_out(prev_frame, next_frame, progress)

        # Fade variations
        if self.transition_type == "fade_to_black":
            return self._fade_to_black(prev_frame, next_frame, progress)
        if self.transition_type == "fade_to_white":
            return self._fade_to_white(prev_frame, next_frame, progress)

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

    # New slide transitions
    def _slide_right(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        split_point = int(w * (1 - progress))
        result = prev_frame.copy()
        if split_point < w:
            result[:, split_point:] = next_frame[:, split_point:]
        return result

    def _slide_up(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        split_point = int(h * progress)
        result = prev_frame.copy()
        if split_point > 0:
            result[:split_point, :] = next_frame[:split_point, :]
        return result

    def _slide_down(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        split_point = int(h * (1 - progress))
        result = prev_frame.copy()
        if split_point < h:
            result[split_point:, :] = next_frame[split_point:, :]
        return result

    def _slide_diagonal(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        result = prev_frame.copy()

        # Create diagonal mask
        for y in range(h):
            for x in range(w):
                # Diagonal line from top-left to bottom-right
                diagonal_progress = (x + y) / (w + h - 2)
                if diagonal_progress <= progress:
                    result[y, x] = next_frame[y, x]

        return result

    # Wipe transitions
    def _wipe_left(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        wipe_point = int(w * (1 - progress))
        result = next_frame.copy()
        if wipe_point > 0:
            result[:, :wipe_point] = prev_frame[:, :wipe_point]
        return result

    def _wipe_right(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        wipe_point = int(w * progress)
        result = next_frame.copy()
        if wipe_point < w:
            result[:, wipe_point:] = prev_frame[:, wipe_point:]
        return result

    def _wipe_up(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        wipe_point = int(h * (1 - progress))
        result = next_frame.copy()
        if wipe_point > 0:
            result[:wipe_point, :] = prev_frame[:wipe_point, :]
        return result

    def _wipe_down(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        wipe_point = int(h * progress)
        result = next_frame.copy()
        if wipe_point < h:
            result[wipe_point:, :] = prev_frame[wipe_point:, :]
        return result

    def _wipe_center_out(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        center_x, center_y = w // 2, h // 2
        max_radius = int(math.sqrt(center_x**2 + center_y**2) * progress)

        result = prev_frame.copy()

        # Create circular mask
        y, x = np.ogrid[:h, :w]
        mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= max_radius**2
        result[mask] = next_frame[mask]

        return result

    def _wipe_center_in(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        center_x, center_y = w // 2, h // 2
        max_radius = int(math.sqrt(center_x**2 + center_y**2))
        current_radius = int(max_radius * (1 - progress))

        result = next_frame.copy()

        # Create circular mask
        y, x = np.ogrid[:h, :w]
        mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= current_radius**2
        result[mask] = prev_frame[mask]

        return result

    # Push transitions
    def _push_left(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        offset = int(w * progress)
        result = np.zeros_like(prev_frame)

        # Push previous frame to the left
        if offset < w:
            result[:, : w - offset] = prev_frame[:, offset:]

        # Next frame comes from the right
        if offset > 0:
            result[:, w - offset :] = next_frame[:, :offset]

        return result

    def _push_right(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        offset = int(w * progress)
        result = np.zeros_like(prev_frame)

        # Push previous frame to the right
        if offset < w:
            result[:, offset:] = prev_frame[:, : w - offset]

        # Next frame comes from the left
        if offset > 0:
            result[:, :offset] = next_frame[:, w - offset :]

        return result

    def _push_up(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        offset = int(h * progress)
        result = np.zeros_like(prev_frame)

        # Push previous frame up
        if offset < h:
            result[: h - offset, :] = prev_frame[offset:, :]

        # Next frame comes from the bottom
        if offset > 0:
            result[h - offset :, :] = next_frame[:offset, :]

        return result

    def _push_down(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        offset = int(h * progress)
        result = np.zeros_like(prev_frame)

        # Push previous frame down
        if offset < h:
            result[offset:, :] = prev_frame[: h - offset, :]

        # Next frame comes from the top
        if offset > 0:
            result[:offset, :] = next_frame[h - offset :, :]

        return result

    # Zoom/Scale transitions
    def _zoom_in(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]

        # Scale next frame from small to full size
        scale = progress
        if scale <= 0:
            return prev_frame

        scaled_h = int(h * scale)
        scaled_w = int(w * scale)

        if scaled_h <= 0 or scaled_w <= 0:
            return prev_frame

        scaled_next = cv2.resize(next_frame, (scaled_w, scaled_h))

        # Center the scaled frame
        result = prev_frame.copy()
        start_y = (h - scaled_h) // 2
        start_x = (w - scaled_w) // 2

        if start_y >= 0 and start_x >= 0:
            result[start_y : start_y + scaled_h, start_x : start_x + scaled_w] = (
                scaled_next
            )

        return result

    def _zoom_out(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]

        # Scale previous frame from full size to small
        scale = 1 - progress
        if scale <= 0:
            return next_frame

        scaled_h = int(h * scale)
        scaled_w = int(w * scale)

        if scaled_h <= 0 or scaled_w <= 0:
            return next_frame

        scaled_prev = cv2.resize(prev_frame, (scaled_w, scaled_h))

        # Center the scaled frame over next frame
        result = next_frame.copy()
        start_y = (h - scaled_h) // 2
        start_x = (w - scaled_w) // 2

        if start_y >= 0 and start_x >= 0:
            result[start_y : start_y + scaled_h, start_x : start_x + scaled_w] = (
                scaled_prev
            )

        return result

    def _scale_up(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        # Similar to zoom_in but with different easing
        return self._zoom_in(prev_frame, next_frame, progress**0.5)

    def _scale_down(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        # Similar to zoom_out but with different easing
        return self._zoom_out(prev_frame, next_frame, progress**2)

    # Split screen transitions
    def _split_vertical(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        center = w // 2
        split_distance = int(w * progress * 0.5)

        result = np.zeros_like(prev_frame)

        # Left half moves left
        left_end = max(0, center - split_distance)
        if left_end > 0:
            result[:, :left_end] = prev_frame[
                :, split_distance : center + split_distance
            ]

        # Right half moves right
        right_start = min(w, center + split_distance)
        if right_start < w:
            result[:, right_start:] = prev_frame[
                :, center - split_distance : center - split_distance + w - right_start
            ]

        # Fill the gap with next frame
        if split_distance > 0:
            gap_start = max(0, center - split_distance)
            gap_end = min(w, center + split_distance)
            if gap_end > gap_start:
                result[:, gap_start:gap_end] = next_frame[:, gap_start:gap_end]

        return result

    def _split_horizontal(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        center = h // 2
        split_distance = int(h * progress * 0.5)

        result = np.zeros_like(prev_frame)

        # Top half moves up
        top_end = max(0, center - split_distance)
        if top_end > 0:
            result[:top_end, :] = prev_frame[
                split_distance : center + split_distance, :
            ]

        # Bottom half moves down
        bottom_start = min(h, center + split_distance)
        if bottom_start < h:
            result[bottom_start:, :] = prev_frame[
                center - split_distance : center - split_distance + h - bottom_start, :
            ]

        # Fill the gap with next frame
        if split_distance > 0:
            gap_start = max(0, center - split_distance)
            gap_end = min(h, center + split_distance)
            if gap_end > gap_start:
                result[gap_start:gap_end, :] = next_frame[gap_start:gap_end, :]

        return result

    def _venetian_blinds(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        blind_count = 10  # Number of horizontal blinds
        blind_height = h // blind_count

        result = prev_frame.copy()

        for i in range(blind_count):
            start_row = i * blind_height
            end_row = min((i + 1) * blind_height, h)

            # Each blind opens at slightly different times
            blind_progress = max(0, min(1, (progress - i * 0.05) / 0.7))

            if blind_progress > 0:
                reveal_height = int(blind_height * blind_progress)
                if reveal_height > 0:
                    reveal_end = min(start_row + reveal_height, end_row)
                    result[start_row:reveal_end, :] = next_frame[
                        start_row:reveal_end, :
                    ]

        return result

    def _vertical_blinds(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        blind_count = 10  # Number of vertical blinds
        blind_width = w // blind_count

        result = prev_frame.copy()

        for i in range(blind_count):
            start_col = i * blind_width
            end_col = min((i + 1) * blind_width, w)

            # Each blind opens at slightly different times
            blind_progress = max(0, min(1, (progress - i * 0.05) / 0.7))

            if blind_progress > 0:
                reveal_width = int(blind_width * blind_progress)
                if reveal_width > 0:
                    reveal_end = min(start_col + reveal_width, end_col)
                    result[:, start_col:reveal_end] = next_frame[
                        :, start_col:reveal_end
                    ]

        return result

    # Circular transitions
    def _circle_in(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        center_x, center_y = w // 2, h // 2
        max_radius = math.sqrt(center_x**2 + center_y**2)
        current_radius = max_radius * progress

        result = prev_frame.copy()

        # Create circular mask
        y, x = np.ogrid[:h, :w]
        mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= current_radius**2
        result[mask] = next_frame[mask]

        return result

    def _circle_out(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        h, w = prev_frame.shape[:2]
        center_x, center_y = w // 2, h // 2
        max_radius = math.sqrt(center_x**2 + center_y**2)
        current_radius = max_radius * (1 - progress)

        result = next_frame.copy()

        # Create circular mask
        y, x = np.ogrid[:h, :w]
        mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= current_radius**2
        result[mask] = prev_frame[mask]

        return result

    # Fade variations
    def _fade_to_black(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        if progress < 0.5:
            # Fade to black
            fade_progress = progress * 2
            black_frame = np.zeros_like(prev_frame)
            return self._crossfade(prev_frame, black_frame, fade_progress)
        # Fade from black
        fade_progress = (progress - 0.5) * 2
        black_frame = np.zeros_like(next_frame)
        return self._crossfade(black_frame, next_frame, fade_progress)

    def _fade_to_white(
        self, prev_frame: np.ndarray, next_frame: np.ndarray, progress: float
    ) -> np.ndarray:
        if progress < 0.5:
            # Fade to white
            fade_progress = progress * 2
            white_frame = np.full_like(prev_frame, 255)
            return self._crossfade(prev_frame, white_frame, fade_progress)
        # Fade from white
        fade_progress = (progress - 0.5) * 2
        white_frame = np.full_like(next_frame, 255)
        return self._crossfade(white_frame, next_frame, fade_progress)
