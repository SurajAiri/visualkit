from abc import ABC, abstractmethod
from pathlib import Path

from visualkit.models.timeline import Timeline


class BaseExporter(ABC):
    """Abstract base class for timeline exporters."""

    @abstractmethod
    def export(self, timeline: Timeline, output_path: str | Path, **kwargs) -> Path:
        """Export a Timeline to the specified output file path.

        Args:
            timeline: The Timeline to export.
            output_path: Target file path.
            **kwargs: Format-specific export options.

        Returns:
            Path: Path to the generated export file.
        """
        pass
