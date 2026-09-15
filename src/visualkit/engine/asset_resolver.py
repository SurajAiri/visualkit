from collections.abc import Callable


class AssetResolver:
    """Resolves asset references to actual media sources, handling caching and retrieval of assets.
    <br> Used by Export layer to resolve asset references to actual media sources, handling caching and retrieval of assets."""  # noqa: E501

    def __init__(self, resolver: Callable[[str], str]):
        """
        Initializes the AssetResolver with a resolver function.

        Args:
            resolver (callable): A function that takes an asset reference (str) and returns the actual media source (str).
        """  # noqa: E501
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

    def clear_cache(self) -> None:
        """Clears the cached asset resolutions."""
        self.cache.clear()
