from dataclasses import dataclass


@dataclass
class VideoConfig:
    """Video configuration for the video editor.
    Attributes:
        width (int): Width of the video in pixels.
        height (int): Height of the video in pixels.
        fps (int): Frames per second for the video.
        codec (str): Codec to use for video encoding.
        resize_method (str): Method to use for resizing images. [adaptive (default)] Options: smart, adaptive, gradual, aspect_ratio.
    """  # noqa: E501

    width: int = 1280
    height: int = 720
    fps: int = 30
    codec: str = "avc1"
    resize_method: str = "adaptive"  # Options: smart, adaptive, gradual, aspect_ratio

    def __post_init__(self):
        """Validate configuration parameters"""
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Width and height must be positive")
        if self.fps <= 0:
            raise ValueError("FPS must be positive")
