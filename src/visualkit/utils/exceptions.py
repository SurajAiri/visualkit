"""Custom exceptions for VisualKit."""


class VisualKitError(Exception):
    """Base exception for all VisualKit errors."""


class ClipNotFoundError(VisualKitError):
    """Raised when a requested clip cannot be found in the timeline."""


class TrackNotFoundError(VisualKitError):
    """Raised when a requested track cannot be found in the timeline."""


class InvalidTimeError(VisualKitError):
    """Raised when an invalid time or duration is specified."""


class InvalidSplitError(VisualKitError):
    """Raised when a split operation cannot be performed at the requested point."""


class InvalidTrackOperationError(VisualKitError):
    """Raised when an illegal operation is performed on a track."""


class TimelineValidationError(VisualKitError):
    """Raised when timeline integrity checks fail."""
