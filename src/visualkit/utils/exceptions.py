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


class CodedVisualError(VisualKitError):
    """Base class for coded-visual problems."""


class CodedVisualCompileError(CodedVisualError):
    """Raised when a coded visual cannot be compiled/rendered into media."""


class BrowserNotFoundError(CodedVisualCompileError):
    """Raised when no usable Chrome/Chromium executable can be located."""


class MissingSourceError(VisualKitError):
    """Raised when a clip's source file cannot be found at export time."""


class TemplateParameterError(VisualKitError):
    """Raised when an exposed template parameter points at something that does not exist."""


class ExportError(VisualKitError):
    """Raised when an external encoder (ffmpeg) fails while exporting.

    `returncode` and `stderr` carry the raw process details; `str(error)` is a
    readable summary ending with the last lines of the tool's own output, which
    is where ffmpeg actually says what went wrong.
    """

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
        command: list[str] | None = None,
    ):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.command = command or []
