import logging
import math
import os

import cv2
import numpy as np

from visualkit.config import VideoConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            # New effects
            "swing",
            "sway",
            "elastic_zoom",
            "rubber_band",
            "zoom_bounce",
            "zoom_elastic",
            "ken_burns",
            "float",
            "drift",
            "hover",
            "wave",
            "ripple",
        ]

    @staticmethod
    def get_moving_effects():
        """Return a list of effects that involve movement"""
        return [
            "none",
            "zoom",
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
            "swing",
            "sway",
            "elastic_zoom",
            "rubber_band",
            "zoom_bounce",
            "zoom_elastic",
            "ken_burns",
            "float",
            "drift",
            "hover",
            "wave",
            "ripple",
        ]

    def _scale_and_crop_internal(self, frame: np.ndarray, scale: float) -> np.ndarray:
        """Internal method to scale frame without cropping to target dimensions"""
        if scale <= 0:
            scale = 1.0

        h, w = frame.shape[:2]
        new_h, new_w = int(h * scale), int(w * scale)

        if new_h <= 0 or new_w <= 0:
            return frame

        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def get_frame(self, timestamp: float, config: VideoConfig) -> np.ndarray:
        try:
            if self._cached_frame is None:
                self._load_and_resize(config)
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

    def _load_and_resize(self, config: VideoConfig):
        option = config.resize_method.lower()
        if option == "smart":
            self._load_and_resize_fill_smart(config)
        elif option == "adaptive":
            self._load_and_resize_fill_adaptive(config)
        elif option == "gradual":
            self._load_and_resize_fill_gradual(config)
        elif option == "aspect_ratio":
            self._load_and_resize_with_aspect_ratio(config)
        elif option == "fill":
            self._load_and_resize_fill_direct(config)
        else:
            self._load_and_resize_with_aspect_ratio(config)

    def _load_and_resize_fill_direct(self, config: VideoConfig):
        """
        Load and resize media to fill entire screen without preserving aspect ratio.
        This is the most direct approach - simply stretch to fit target dimensions.
        """
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

            # Create enlarged frame for movement effects (2.5x size)
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)

            # Simply resize to fill entire enlarged dimensions (may change aspect ratio)
            self._cached_frame = cv2.resize(
                original_frame, (enlarged_w, enlarged_h), interpolation=cv2.INTER_AREA
            )

        except Exception as e:
            logger.error(f"Error loading media {self.asset_path}: {e}")
            # Create enlarged black frame as fallback
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)
            self._cached_frame = np.zeros((enlarged_h, enlarged_w, 3), dtype=np.uint8)

    def _load_and_resize_fill_smart(self, config: VideoConfig):
        """
        Load and resize image/video to fill the target dimensions with minimal stretching.
        Uses smart cropping to remove less important areas before stretching.
        """
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

            # Create enlarged frame for movement effects (2.5x size)
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)

            # Calculate aspect ratios
            original_aspect = original_w / original_h
            target_aspect = enlarged_w / enlarged_h

            # Maximum allowed stretch factor to avoid extreme distortion
            max_stretch_factor = 1.4

            # Calculate what the dimensions would be if we just stretched
            stretch_factor_w = enlarged_w / original_w
            stretch_factor_h = enlarged_h / original_h
            max_stretch = max(stretch_factor_w, stretch_factor_h)

            if max_stretch <= max_stretch_factor:
                # Stretching is acceptable, just resize directly
                resized = cv2.resize(
                    original_frame,
                    (enlarged_w, enlarged_h),
                    interpolation=cv2.INTER_AREA,
                )
                self._cached_frame = resized
            else:
                # Need to crop first to reduce stretching
                if original_aspect > target_aspect:
                    # Image is wider than target, crop width
                    # Calculate how much width we can afford to crop
                    ideal_crop_w = int(original_h * target_aspect)
                    min_crop_w = int(original_h * target_aspect / max_stretch_factor)

                    # Use smart cropping - prefer center crop but can adjust
                    crop_w = max(min_crop_w, min(ideal_crop_w, original_w))
                    crop_x = (original_w - crop_w) // 2

                    # Apply crop
                    cropped = original_frame[:, crop_x : crop_x + crop_w]
                else:
                    # Image is taller than target, crop height
                    ideal_crop_h = int(original_w / target_aspect)
                    min_crop_h = int(original_w / target_aspect / max_stretch_factor)

                    # Use smart cropping - prefer center crop but can adjust
                    crop_h = max(min_crop_h, min(ideal_crop_h, original_h))
                    crop_y = (original_h - crop_h) // 2

                    # Apply crop
                    cropped = original_frame[crop_y : crop_y + crop_h, :]

                # Now resize the cropped image
                resized = cv2.resize(
                    cropped, (enlarged_w, enlarged_h), interpolation=cv2.INTER_AREA
                )
                self._cached_frame = resized

        except Exception as e:
            logger.error(f"Error loading media {self.asset_path}: {e}")
            # Create enlarged black frame as fallback
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)
            self._cached_frame = np.zeros((enlarged_h, enlarged_w, 3), dtype=np.uint8)

    def _load_and_resize_fill_adaptive(self, config: VideoConfig):
        """
        Load and resize with adaptive stretching - more stretching for minor differences,
        less stretching for major aspect ratio differences.
        """
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

            original_h, original_w = original_frame.shape[:2]

            # Create enlarged frame for movement effects
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)

            # Calculate aspect ratios
            original_aspect = original_w / original_h
            target_aspect = enlarged_w / enlarged_h
            aspect_ratio_diff = abs(original_aspect - target_aspect) / target_aspect

            # Adaptive approach based on aspect ratio difference
            if aspect_ratio_diff < 0.1:
                # Very similar aspect ratios - just stretch
                resized = cv2.resize(
                    original_frame,
                    (enlarged_w, enlarged_h),
                    interpolation=cv2.INTER_AREA,
                )
                self._cached_frame = resized

            elif aspect_ratio_diff < 0.3:
                # Moderate difference - slight crop + stretch
                if original_aspect > target_aspect:
                    # Crop 15% from width
                    crop_w = int(original_w * 0.85)
                    crop_x = (original_w - crop_w) // 2
                    cropped = original_frame[:, crop_x : crop_x + crop_w]
                else:
                    # Crop 15% from height
                    crop_h = int(original_h * 0.85)
                    crop_y = (original_h - crop_h) // 2
                    cropped = original_frame[crop_y : crop_y + crop_h, :]

                resized = cv2.resize(
                    cropped, (enlarged_w, enlarged_h), interpolation=cv2.INTER_AREA
                )
                self._cached_frame = resized

            else:
                # Large difference - more aggressive cropping
                if original_aspect > target_aspect:
                    # Crop to target aspect ratio + 20% margin
                    target_w = int(original_h * target_aspect * 1.2)
                    crop_w = min(target_w, original_w)
                    crop_x = (original_w - crop_w) // 2
                    cropped = original_frame[:, crop_x : crop_x + crop_w]
                else:
                    # Crop to target aspect ratio + 20% margin
                    target_h = int(original_w / target_aspect * 1.2)
                    crop_h = min(target_h, original_h)
                    crop_y = (original_h - crop_h) // 2
                    cropped = original_frame[crop_y : crop_y + crop_h, :]

                resized = cv2.resize(
                    cropped, (enlarged_w, enlarged_h), interpolation=cv2.INTER_AREA
                )
                self._cached_frame = resized

        except Exception as e:
            logger.error(f"Error loading media {self.asset_path}: {e}")
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)
            self._cached_frame = np.zeros((enlarged_h, enlarged_w, 3), dtype=np.uint8)

    def _load_and_resize_fill_gradual(self, config: VideoConfig):
        """
        Load and resize with gradual stretching - combines cropping and stretching
        in a balanced way to minimize visual distortion.
        """
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

            original_h, original_w = original_frame.shape[:2]

            # Create enlarged frame for movement effects
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)

            original_aspect = original_w / original_h
            target_aspect = enlarged_w / enlarged_h

            # Calculate intermediate dimensions that balance cropping and stretching
            if original_aspect > target_aspect:
                # Image is wider - crop some width and stretch the rest
                crop_factor = 0.7  # Keep 70% of width difference
                ideal_w = int(original_h * target_aspect)
                crop_w = int(ideal_w + (original_w - ideal_w) * crop_factor)
                crop_x = (original_w - crop_w) // 2

                intermediate_frame = original_frame[:, crop_x : crop_x + crop_w]
            else:
                # Image is taller - crop some height and stretch the rest
                crop_factor = 0.7  # Keep 70% of height difference
                ideal_h = int(original_w / target_aspect)
                crop_h = int(ideal_h + (original_h - ideal_h) * crop_factor)
                crop_y = (original_h - crop_h) // 2

                intermediate_frame = original_frame[crop_y : crop_y + crop_h, :]

            # Resize the intermediate frame to final dimensions
            resized = cv2.resize(
                intermediate_frame,
                (enlarged_w, enlarged_h),
                interpolation=cv2.INTER_AREA,
            )
            self._cached_frame = resized

        except Exception as e:
            logger.error(f"Error loading media {self.asset_path}: {e}")
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)
            self._cached_frame = np.zeros((enlarged_h, enlarged_w, 3), dtype=np.uint8)

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

            # Create a much larger frame for movement effects (2.5x size for better movement space) # noqa: E501
            enlarged_w = int(target_w * 2.5)
            enlarged_h = int(target_h * 2.5)

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
            enlarged_w = int(config.width * 2.5)
            enlarged_h = int(config.height * 2.5)
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
        # New effects
        if self.effect_type == "swing":
            return self._apply_swing(frame, timestamp, config)
        if self.effect_type == "sway":
            return self._apply_sway(frame, timestamp, config)
        if self.effect_type == "elastic_zoom":
            return self._apply_elastic_zoom(frame, timestamp, config)
        if self.effect_type == "rubber_band":
            return self._apply_rubber_band(frame, timestamp, config)
        if self.effect_type == "zoom_bounce":
            return self._apply_zoom_bounce(frame, timestamp, config)
        if self.effect_type == "zoom_elastic":
            return self._apply_zoom_elastic(frame, timestamp, config)
        if self.effect_type == "ken_burns":
            return self._apply_ken_burns(frame, timestamp, config)
        if self.effect_type == "float":
            return self._apply_float(frame, timestamp, config)
        if self.effect_type == "drift":
            return self._apply_drift(frame, timestamp, config)
        if self.effect_type == "hover":
            return self._apply_hover(frame, timestamp, config)
        if self.effect_type == "wave":
            return self._apply_wave(frame, timestamp, config)
        if self.effect_type == "ripple":
            return self._apply_ripple(frame, timestamp, config)
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

    def _apply_pulse(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply pulsing effect using sine wave scaling"""
        # Create pulsing effect using sine wave
        pulse_frequency = 2.0  # pulses per second
        pulse_amplitude = 0.2  # how much to scale (20% variation)

        # Calculate scale factor using sine wave
        scale_variation = pulse_amplitude * math.sin(
            timestamp * pulse_frequency * 2 * math.pi
        )
        scale = 1.0 + scale_variation

        # Ensure scale doesn't go below a minimum value
        scale = max(0.8, scale)

        return self._scale_and_crop(frame, scale, config)

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

        # Check if we have enough space for pan effect
        if (
            max_x_movement < config.width * 0.3
        ):  # Need at least 30% of width for smooth pan
            # Apply zoom to create more space
            zoom_factor = 1.5
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

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

        # Check if we have enough space for pan effect
        if (
            max_x_movement < config.width * 0.3
        ):  # Need at least 30% of width for smooth pan
            # Apply zoom to create more space
            zoom_factor = 1.5
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

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

        # Check if we have enough space for pan effect
        if (
            max_y_movement < config.height * 0.3
        ):  # Need at least 30% of height for smooth pan
            # Apply zoom to create more space
            zoom_factor = 1.5
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

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

        # Check if we have enough space for pan effect
        if (
            max_y_movement < config.height * 0.3
        ):  # Need at least 30% of height for smooth pan
            # Apply zoom to create more space
            zoom_factor = 1.5
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

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
        shake_intensity = 40  # Increased intensity for more visible shake
        frequency = 25  # Shake frequency

        # Use different frequencies for x and y to create more realistic shake
        x_offset = int(shake_intensity * math.sin(timestamp * frequency))
        y_offset = int(shake_intensity * math.cos(timestamp * frequency * 1.3))

        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for shake effect
        if max_x_movement < shake_intensity * 2 or max_y_movement < shake_intensity * 2:
            # Apply zoom to create more space
            zoom_factor = 1.3
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

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
        bounce_height = 80  # Increased bounce height
        bounce_frequency = 1.2  # bounces per second

        # Use timestamp directly for continuous bouncing
        bounce_offset = int(
            bounce_height * abs(math.sin(timestamp * bounce_frequency * math.pi))
        )

        h, w = frame.shape[:2]

        # Calculate available movement space
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for bounce effect
        if max_y_movement < bounce_height * 2:
            # Apply zoom to create more space
            zoom_factor = 1.4
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

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

    # Swing/Pendulum Effects
    def _apply_swing(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply pendulum swing effect"""
        swing_frequency = 0.8  # swings per second
        swing_amplitude = 60  # maximum swing angle in pixels

        # Calculate swing offset using sine wave
        swing_offset = int(
            swing_amplitude * math.sin(timestamp * swing_frequency * 2 * math.pi)
        )

        h, w = frame.shape[:2]
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for swing effect
        if max_x_movement < swing_amplitude * 2:
            zoom_factor = 1.4
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

        # Calculate center position and apply swing
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        start_x = center_x + swing_offset
        start_y = center_y

        # Ensure we don't go out of bounds
        start_x = max(0, min(start_x, max_x_movement))
        start_y = max(0, min(start_y, max_y_movement))

        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

    def _apply_sway(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply gentle side-to-side sway effect"""
        sway_frequency = 0.3  # slower, more gentle movement
        sway_amplitude = 30  # gentler amplitude

        # Calculate sway offset using sine wave
        sway_offset = int(
            sway_amplitude * math.sin(timestamp * sway_frequency * 2 * math.pi)
        )

        h, w = frame.shape[:2]
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for sway effect
        if max_x_movement < sway_amplitude * 2:
            zoom_factor = 1.3
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

        # Calculate center position and apply sway
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        start_x = center_x + sway_offset
        start_y = center_y

        # Ensure we don't go out of bounds
        start_x = max(0, min(start_x, max_x_movement))
        start_y = max(0, min(start_y, max_y_movement))

        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

    # Elastic/Spring Effects
    def _apply_elastic_zoom(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply elastic zoom with overshoot and bounce"""
        progress = min(1.0, timestamp / self.duration)

        if progress < 0.7:
            # Main zoom phase
            scale = 1.0 + (0.4 * progress / 0.7)
        else:
            # Elastic bounce phase
            elastic_progress = (progress - 0.7) / 0.3
            bounce = (
                0.1
                * math.sin(elastic_progress * 4 * math.pi)
                * math.exp(-elastic_progress * 3)
            )
            scale = 1.4 + bounce

        return self._scale_and_crop(frame, scale, config)

    def _apply_rubber_band(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply rubber band stretching and snapping effect"""
        progress = min(1.0, timestamp / self.duration)

        if progress < 0.5:
            # Stretch phase
            stretch_factor = progress * 2
            scale_x = 1.0 + (0.3 * stretch_factor)
            scale_y = 1.0 - (
                0.15 * stretch_factor
            )  # Compress vertically while stretching horizontally
        else:
            # Snap back phase with overshoot
            snap_progress = (progress - 0.5) * 2
            overshoot = (
                0.2
                * math.sin(snap_progress * 3 * math.pi)
                * math.exp(-snap_progress * 2)
            )
            scale_x = 1.3 - (0.3 * snap_progress) + overshoot
            scale_y = 0.85 + (0.15 * snap_progress) - overshoot * 0.5

        # Apply non-uniform scaling
        h, w = frame.shape[:2]
        new_h = int(h * scale_y)
        new_w = int(w * scale_x)

        if new_h > 0 and new_w > 0:
            scaled = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            return self._crop_to_target(scaled, config)

        return self._crop_to_target(frame, config)

    # Advanced Zoom Effects
    def _apply_zoom_bounce(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply zoom with bounce at the end"""
        progress = min(1.0, timestamp / self.duration)

        if progress < 0.8:
            # Main zoom phase
            scale = 1.0 + (0.3 * progress / 0.8)
        else:
            # Bounce phase
            bounce_progress = (progress - 0.8) / 0.2
            bounce = (
                0.1 * math.sin(bounce_progress * 2 * math.pi) * (1 - bounce_progress)
            )
            scale = 1.3 + bounce

        return self._scale_and_crop(frame, scale, config)

    def _apply_zoom_elastic(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply zoom with elastic overshoot"""
        progress = min(1.0, timestamp / self.duration)

        # Elastic easing function
        if progress < 0.7:
            scale = 1.0 + (0.4 * progress / 0.7)
        else:
            elastic_progress = (progress - 0.7) / 0.3
            overshoot = (
                0.15
                * math.sin(elastic_progress * 6 * math.pi)
                * math.exp(-elastic_progress * 4)
            )
            scale = 1.4 + overshoot

        return self._scale_and_crop(frame, scale, config)

    def _apply_ken_burns(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply classic Ken Burns effect (slow zoom + pan)"""
        progress = min(1.0, timestamp / self.duration)

        # Slow zoom
        scale = 1.0 + (0.2 * progress)

        # Slow pan (diagonal movement)
        h, w = frame.shape[:2]

        # Apply scale first
        scaled = self._scale_and_crop_internal(frame, scale)
        sh, sw = scaled.shape[:2]

        max_x_movement = sw - config.width
        max_y_movement = sh - config.height

        # Pan diagonally from bottom-left to top-right
        x_offset = int(max_x_movement * progress * 0.3)  # 30% of available movement
        y_offset = int(max_y_movement * (1 - progress * 0.3))  # Start from bottom

        # Ensure we don't go out of bounds
        x_offset = max(0, min(x_offset, max_x_movement))
        y_offset = max(0, min(y_offset, max_y_movement))

        return scaled[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

    # Floating/Hovering Effects
    def _apply_float(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply gentle floating movement"""
        float_frequency = 0.5  # slow floating
        float_amplitude = 25  # gentle movement

        # Calculate float offset using sine wave
        float_offset = int(
            float_amplitude * math.sin(timestamp * float_frequency * 2 * math.pi)
        )

        h, w = frame.shape[:2]
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for float effect
        if max_y_movement < float_amplitude * 2:
            zoom_factor = 1.3
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

        # Calculate center position and apply float
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        start_x = center_x
        start_y = center_y + float_offset

        # Ensure we don't go out of bounds
        start_x = max(0, min(start_x, max_x_movement))
        start_y = max(0, min(start_y, max_y_movement))

        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

    def _apply_drift(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply slow diagonal drift movement"""
        progress = min(1.0, timestamp / self.duration)

        h, w = frame.shape[:2]
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for drift effect
        if max_x_movement < config.width * 0.2 or max_y_movement < config.height * 0.2:
            zoom_factor = 1.4
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

        # Drift diagonally from top-left to bottom-right
        x_offset = int(max_x_movement * progress * 0.6)
        y_offset = int(max_y_movement * progress * 0.6)

        # Ensure we don't go out of bounds
        x_offset = max(0, min(x_offset, max_x_movement))
        y_offset = max(0, min(y_offset, max_y_movement))

        return frame[
            y_offset : y_offset + config.height, x_offset : x_offset + config.width
        ]

    def _apply_hover(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply small random hovering movements"""
        # Multiple sine waves for more organic movement
        hover_x = int(15 * math.sin(timestamp * 2.3) + 8 * math.sin(timestamp * 3.7))
        hover_y = int(12 * math.sin(timestamp * 1.8) + 6 * math.sin(timestamp * 4.2))

        h, w = frame.shape[:2]
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for hover effect
        if max_x_movement < 50 or max_y_movement < 50:
            zoom_factor = 1.3
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

        # Calculate center position and apply hover
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        start_x = center_x + hover_x
        start_y = center_y + hover_y

        # Ensure we don't go out of bounds
        start_x = max(0, min(start_x, max_x_movement))
        start_y = max(0, min(start_y, max_y_movement))

        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

    # Wave/Ripple Effects
    def _apply_wave(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply wavy sinusoidal movement pattern"""
        wave_frequency = 1.2  # waves per second
        wave_amplitude_x = 40  # horizontal wave amplitude
        wave_amplitude_y = 25  # vertical wave amplitude

        # Calculate wave offsets using different frequencies for x and y
        wave_x = int(
            wave_amplitude_x * math.sin(timestamp * wave_frequency * 2 * math.pi)
        )
        wave_y = int(
            wave_amplitude_y * math.sin(timestamp * wave_frequency * 1.5 * 2 * math.pi)
        )

        h, w = frame.shape[:2]
        max_x_movement = w - config.width
        max_y_movement = h - config.height

        # Check if we have enough space for wave effect
        if (
            max_x_movement < wave_amplitude_x * 2
            or max_y_movement < wave_amplitude_y * 2
        ):
            zoom_factor = 1.4
            scaled_frame = self._scale_and_crop_internal(frame, zoom_factor)
            h, w = scaled_frame.shape[:2]
            max_x_movement = w - config.width
            max_y_movement = h - config.height
            frame = scaled_frame

        # Calculate center position and apply wave
        center_x = max_x_movement // 2
        center_y = max_y_movement // 2

        start_x = center_x + wave_x
        start_y = center_y + wave_y

        # Ensure we don't go out of bounds
        start_x = max(0, min(start_x, max_x_movement))
        start_y = max(0, min(start_y, max_y_movement))

        return frame[
            start_y : start_y + config.height, start_x : start_x + config.width
        ]

    def _apply_ripple(
        self, frame: np.ndarray, timestamp: float, config: VideoConfig
    ) -> np.ndarray:
        """Apply ripple-like expansion effect"""
        progress = min(1.0, timestamp / self.duration)

        # Create ripple effect with oscillating scale
        ripple_frequency = 3.0  # ripples per duration
        ripple_amplitude = 0.1  # scale variation

        # Base expansion
        base_scale = 1.0 + (0.2 * progress)

        # Ripple oscillation
        ripple_offset = ripple_amplitude * math.sin(
            timestamp * ripple_frequency * 2 * math.pi
        )

        # Fade out ripples over time
        ripple_fade = 1.0 - (progress * 0.5)
        ripple_offset *= ripple_fade

        final_scale = base_scale + ripple_offset

        # Ensure minimum scale
        final_scale = max(0.8, final_scale)

        return self._scale_and_crop(frame, final_scale, config)

    def cleanup(self):
        self._cached_frame = None
        self._last_effect_frame = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
