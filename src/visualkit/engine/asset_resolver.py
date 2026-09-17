from collections.abc import Callable, Mapping
from typing import Union


class AssetResolver:
    """Resolves asset references to actual media sources.

    Handles caching and retrieval of assets for the export and rendering layers.
    """

    def __init__(self, resolver: Union[Callable[[str], str], Mapping[str, str]]):
        """Initializes the AssetResolver with a resolver function or a dictionary mapping.

        Args:
            resolver: A callable returning the actual media source path for an asset reference,
                      or a Mapping (dict) of asset references to file paths.
        """

        if isinstance(resolver, Mapping):
            self.resolver = lambda ref: resolver.get(ref, ref)
        else:
            self.resolver = resolver
        self.cache: dict[str, str] = {}

    def resolve(self, asset_reference: str) -> str:
        """
        Resolves an asset reference to its actual media source.

        Args:
            asset_reference (str): The asset reference to resolve.

        Returns:
            str: The resolved media source.
        """
        if asset_reference in self.cache:
            return self.cache[asset_reference]

        media_source = self.resolver(asset_reference)
        self.cache[asset_reference] = media_source
        return media_source

    def __call__(self, asset_reference: str) -> str:
        return self.resolve(asset_reference)

    def clear_cache(self) -> None:
        """Clears the cached asset resolutions."""
        self.cache.clear()


class DictAssetResolver(AssetResolver):
    """Convenience AssetResolver initialized from a dictionary mapping."""

    def __init__(self, mapping: Mapping[str, str]):
        super().__init__(mapping)
