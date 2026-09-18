from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from visualkit.models.timeline import Timeline


class BaseExporter(ABC):
    """Abstract base class for timeline exporters."""

    #: Configured on subclasses in __init__; declared here so the shared
    #: helpers below type-check and so every exporter is guaranteed to have
    #: a consistent attribute name for it.
    asset_resolver: Any = None

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

    def _resolve_source(self, source_str: str) -> str:
        """Resolve an asset reference using asset_resolver if configured.

        Shared by every exporter that accepts an `asset_resolver`
        (a callable, or an object with a `.resolve(str) -> str` method) so
        clip sources like `asset://b_roll` can be mapped to real file paths
        or URLs at export time.
        """
        if not source_str:
            return source_str
        if self.asset_resolver:
            if hasattr(self.asset_resolver, "resolve"):
                return self.asset_resolver.resolve(source_str)
            if callable(self.asset_resolver):
                return self.asset_resolver(source_str)
        return source_str

    def _resolve_source_uri(self, source_str: str) -> str:
        """Resolve a clip source to a `file://` URI (or pass through
        already-qualified URIs / generator references unchanged).

        Shared logic for exporters that emit NLE project files where every
        clip needs a proper source URI: resolves through `asset_resolver`
        first, then converts existing local paths to absolute `file://`
        URIs so the resulting project references files correctly regardless
        of the current working directory.
        """
        resolved = self._resolve_source(source_str)
        if not resolved:
            return "file:///unknown"
        if resolved.startswith(("file://", "generator://")):
            return resolved
        p = Path(resolved)
        return p.resolve().as_uri() if p.exists() else f"file://{resolved}"
