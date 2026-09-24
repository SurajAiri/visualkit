"""Tests for `Position.from_anchor()` / `Transform.at_anchor()`."""

from __future__ import annotations

import pytest

from visualkit.models.clips.base import Position
from visualkit.models.clips.visual import Transform


class TestPositionFromAnchor:
    def test_center_is_the_identity_offset(self):
        p = Position.from_anchor("center")
        assert (p.x, p.y) == (0.0, 0.0)

    @pytest.mark.parametrize(
        "anchor,margin,expected",
        [
            ("top", 0, (0.0, -540.0)),
            ("bottom", 0, (0.0, 540.0)),
            ("left", 0, (-960.0, 0.0)),
            ("right", 0, (960.0, 0.0)),
            ("bottom", 80, (0.0, 460.0)),  # 80px in from the bottom edge
            ("top-left", 20, (-940.0, -520.0)),
            ("bottom-right", 20, (940.0, 520.0)),
        ],
    )
    def test_standard_anchors_on_the_default_1080p_canvas(self, anchor, margin, expected):
        p = Position.from_anchor(anchor, margin)
        assert (p.x, p.y) == expected

    def test_anchor_lookup_is_case_and_whitespace_insensitive(self):
        assert Position.from_anchor("  Bottom-Left ") == Position.from_anchor("bottom-left")

    def test_custom_canvas_size_is_respected(self):
        p = Position.from_anchor("right", canvas_size=(3840.0, 2160.0))
        assert (p.x, p.y) == (1920.0, 0.0)

    def test_unrecognized_anchor_raises_with_the_valid_list(self):
        with pytest.raises(ValueError, match="bottom-left"):
            Position.from_anchor("botom")

    def test_matches_the_manual_arithmetic_it_replaces(self):
        """Pins the exact motivating case from the TODO: 80px above the
        bottom edge of a standard 1080p canvas."""
        manual = Position(x=0, y=1080 / 2 - 80)
        assert Position.from_anchor("bottom", margin=80) == manual


class TestTransformAtAnchor:
    def test_builds_a_transform_with_the_anchored_position(self):
        t = Transform.at_anchor("bottom", margin=80)
        assert t.position == Position.from_anchor("bottom", margin=80)
        assert t.is_identity is False

    def test_passes_through_other_transform_fields(self):
        t = Transform.at_anchor("top-right", margin=40, scale=0.9, opacity=80)
        assert t.scale == 0.9
        assert t.opacity == 80
        assert t.position == Position.from_anchor("top-right", margin=40)

    def test_default_canvas_size_matches_position(self):
        t = Transform.at_anchor("left")
        assert t.position == Position.from_anchor("left")
