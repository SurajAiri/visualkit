"""Guards against public names being reachable from submodules but not from
the top-level `visualkit` package -- e.g. `Track`/`TrackKind` were exported
from `visualkit.models` and `DictAssetResolver` from `visualkit.engine`, but
neither was re-exported from `visualkit` itself, so `visualkit.Track` raised
`AttributeError` despite being a documented, commonly-needed type.
"""

import visualkit as vk


def test_track_types_are_exported_at_top_level():
    assert vk.Track is not None
    assert vk.VideoTrack is not None
    assert vk.AudioTrack is not None
    assert vk.TrackKind is not None


def test_dict_asset_resolver_is_exported_at_top_level():
    resolver = vk.DictAssetResolver({"asset://foo": "/tmp/foo.mp4"})
    assert resolver.resolve("asset://foo") == "/tmp/foo.mp4"


def test_all_declared_exports_are_actually_importable():
    """Every name in __all__ should be a real attribute on the package --
    catches the class of bug where __all__ is edited without updating the
    corresponding import (or vice versa)."""
    for name in vk.__all__:
        assert hasattr(vk, name), f"{name!r} is in visualkit.__all__ but not importable from visualkit"
