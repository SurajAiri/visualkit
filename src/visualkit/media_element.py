import math
import os

import cv2
import numpy as np

from visualkit.config import VideoConfig


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
        except Exception:
            # logger.error(f"Error getting frame from {self.asset_path}: {e}")
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

        except Exception:
            # logger.error(f"Error loading media {self.asset_path}: {e}")
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
        # elif self.effect_type == "pulse":
        #     return self._apply_pulse(frame, timestamp, config)
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
        return frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

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
        return frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

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
        return frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

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
        return frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

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
        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

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
        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

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
        return cv2.addWeighted(result, 1 - alpha, frame_cropped, alpha, 0)

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
        return cv2.addWeighted(result, 1 - alpha, frame_cropped, alpha, 0)

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
        return cv2.warpAffine(frame, rotation_matrix, (w, h))

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
