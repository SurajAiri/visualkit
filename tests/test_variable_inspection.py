import pytest

from visualkit.models import (
    CodedVisualClip,
    CompoundClip,
    ExposedParameter,
    Timeline,
    Variable,
    VariableType,
)


def test_variable_inspection_methods():
    clip = CodedVisualClip(
        source="template.html",
        variables={
            "headline": Variable(
                name="headline",
                default="Default Title",
                required=True,
                label="Headline",
            ),
            "accent_color": Variable(
                name="accent_color",
                type=VariableType.COLOR,
                required=False,
                default="#3b82f6",
            ),
            "custom_metric": Variable(
                name="custom_metric",
                required=True,
                default=None,  # Required with no default!
            ),
        },
    )

    # 1. Unset variables initially (none have explicit .value)
    unset = clip.get_unset_variables()
    assert len(unset) == 3
    assert "headline" in unset
    assert "custom_metric" in unset

    # 2. Missing required variables (custom_metric has no value and no default)
    missing = clip.get_missing_required_variables()
    assert missing == ["custom_metric"]

    # 3. Explicitly set headline and custom_metric
    clip.set_variable("headline", "New Headline")
    clip.set_variable("custom_metric", "88%")

    assert clip.get_missing_required_variables() == []
    assert clip.get_set_variables() == {
        "headline": "New Headline",
        "custom_metric": "88%",
    }
    assert list(clip.get_unset_variables().keys()) == ["accent_color"]


def test_compound_parameter_inspection():
    inner = Timeline()
    inner.add_clip(CodedVisualClip(id="cv1", source="t.html"))

    compound = CompoundClip(
        id="comp1",
        inner_timeline=inner,
        exposed_parameters=[
            ExposedParameter(
                name="title",
                target_clip_id="cv1",
                target_variable="title",
                default="Intro",
                required=False,
            ),
            ExposedParameter(
                name="api_key_or_logo",
                target_clip_id="cv1",
                target_variable="logo",
                default=None,
                required=True,
            ),
        ],
    )

    assert compound.get_missing_required_parameters() == ["api_key_or_logo"]
    assert len(compound.get_unset_parameters()) == 2

    # Set parameter
    compound.set_parameter("api_key_or_logo", "logo.png")
    assert compound.get_missing_required_parameters() == []
    assert "api_key_or_logo" in compound.get_set_parameters()
    assert len(compound.get_unset_parameters()) == 1
