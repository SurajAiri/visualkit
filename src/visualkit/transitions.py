import cv2
import numpy as np

from visualkit.utils import logger


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
