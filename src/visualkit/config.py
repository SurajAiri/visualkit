from dataclasses import dataclass


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
