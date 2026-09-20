import pytest

from visualkit.models import (
    CodedVisualClip,
    CompoundClip,
    ExposedParameter,
    Size,
    Source,
    TextClip,
    Timeline,
    Variable,
    VariableType,
)
from visualkit.utils.time import Time


def test_variable_model():
    # Variable with label, AI description, and default
    v = Variable(
        name="bg_color",
        type=VariableType.COLOR,
        default="#ffffff",
        label="Background Color",
        description="Hex color code for the background banner",
    )
    assert v.resolve_value() == "#ffffff"

    # Assigned value overrides default
    v.value = "#000000"
    assert v.resolve_value() == "#000000"


def test_variable_type_coercion():
    v_num = Variable(name="count", type=VariableType.NUMBER, value="42")
    assert v_num.value == 42.0

    v_bool = Variable(name="show_logo", type=VariableType.BOOLEAN, value="true")
    assert v_bool.value is True


def test_coded_visual_clip_source_and_aspect_ratio():
    clip = CodedVisualClip(
        id="cv1",
        source="templates/infographic.html",
        aspect_ratio="9:16",
        canvas_size=Size(width=1080, height=1920),
        auto_scale=True,
        variables={
            "name": {
                "type": "string",
                "default": "World",
                "label": "User Name",
                "description": "The name shown in the welcome animation",
            }
        },
    )
    assert clip.source.source == "templates/infographic.html"
    assert clip.aspect_ratio == "9:16"
    assert clip.canvas_size.width == 1080
    assert clip.canvas_size.height == 1920
    assert clip.auto_scale is True
    assert clip.get_resolved_variables() == {"name": "World"}

    # Update variable
    clip.set_variable("name", "Alice")
    assert clip.get_resolved_variables() == {"name": "Alice"}


def test_coded_visual_clip_bundle_and_helpers():
    clip = CodedVisualClip(
        id="cv_bundle",
        source=Source(source="/templates/charts/bar_chart"),
        duration=Time.from_seconds(5),
    )
    assert clip.source.source == "/templates/charts/bar_chart"

    clip.define_variable(
        name="chart_data",
        type=VariableType.JSON,
        default="[10, 20, 30]",
        label="Chart Series",
        description="JSON array of numeric data points for the bar chart",
    )
    assert "chart_data" in clip.variables
    assert clip.variables["chart_data"].description.startswith("JSON array")


def test_compound_clip_parameter_exposure_and_grouping():
    # 1. Inner timeline with a text clip and a coded visual clip
    inner = Timeline()
    txt = TextClip(id="txt_title", text="Initial Title", duration=Time.from_seconds(5))
    cv = CodedVisualClip(
        id="cv_stat",
        source="templates/stat.html",
        duration=Time.from_seconds(5),
        variables={
            "stat": Variable(
                name="stat",
                default="100k",
                label="Statistic",
                description="Headline statistic number with unit",
            )
        },
    )
    inner.add_clip(txt)
    inner.add_clip(cv)

    # 2. Compound clip wrapping inner timeline
    compound = CompoundClip(
        id="compound_infographic",
        duration=Time.from_seconds(5),
        inner_timeline=inner,
    )

    # Check child variables grouped by clip ID
    grouped = compound.get_child_variables()
    assert "cv_stat" in grouped
    assert "stat" in grouped["cv_stat"]
    assert grouped["cv_stat"]["stat"].resolve_value() == "100k"

    # 3. Expose parameters with descriptions for AI agents
    compound.expose_parameter(
        name="headline",
        target_clip_id="txt_title",
        target_variable="text",
        label="Headline Text",
        description="Main headline for this section",
    )
    compound.expose_parameter(
        name="metric_value",
        target_clip_id="cv_stat",
        target_variable="stat",
        label="Metric Number",
        description="Value displayed in the animated counter",
    )

    assert len(compound.exposed_parameters) == 2

    # 4. Set parameter via compound clip and verify propagation to inner clips
    compound.set_parameter("headline", "New Headline!")
    compound.set_parameter("metric_value", "500k")

    _, updated_txt = inner.get_clip("txt_title")
    assert updated_txt.text == "New Headline!"

    _, updated_cv = inner.get_clip("cv_stat")
    assert updated_cv.get_resolved_variables()["stat"] == "500k"


def test_compound_clip_direct_namespaced_parameter():
    inner = Timeline()
    cv = CodedVisualClip(
        id="cv_card",
        source="templates/card.html",
        duration=Time.from_seconds(3),
        variables={"theme": "light"},
    )
    inner.add_clip(cv)

    compound = CompoundClip(inner_timeline=inner)
    compound.set_parameter("cv_card.theme", "dark")

    _, updated_cv = inner.get_clip("cv_card")
    assert updated_cv.get_resolved_variables()["theme"] == "dark"


def test_json_roundtrip_serialization():
    inner = Timeline()
    inner.add_clip(
        CodedVisualClip(
            id="cv1",
            source="templates/card.html",
            variables={"title": Variable(name="title", value="Sample", default="Default")},
        )
    )
    compound = CompoundClip(
        id="comp1",
        inner_timeline=inner,
        exposed_parameters=[
            ExposedParameter(
                name="card_title",
                target_clip_id="cv1",
                target_variable="title",
                label="Card Title",
                description="Title of the card",
            )
        ],
        parameters={"card_title": "Sample"},
    )

    root = Timeline()
    root.add_clip(compound)

    json_data = root.model_dump_json(indent=2)
    restored = Timeline.model_validate_json(json_data)

    restored_compound = restored.video_tracks[0].clips[0]
    assert isinstance(restored_compound, CompoundClip)
    assert len(restored_compound.exposed_parameters) == 1
    assert restored_compound.exposed_parameters[0].name == "card_title"
    assert restored_compound.exposed_parameters[0].description == "Title of the card"


def test_string_source_coercion_and_track_index():
    from visualkit.models import AudioClip, MediaClip, Source, Timeline

    # 1. Test passing string directly to MediaClip and AudioClip
    v_clip = MediaClip(source="/path/to/video.mp4")
    assert isinstance(v_clip.source, Source)
    assert v_clip.source.source == "/path/to/video.mp4"

    a_clip = AudioClip(source="/path/to/audio.mp3")
    assert isinstance(a_clip.source, Source)
    assert a_clip.source.source == "/path/to/audio.mp3"

    # 2. Test adding to empty timeline auto-provisions track
    timeline = Timeline()
    timeline.add_clip(v_clip)
    assert len(timeline.video_tracks) == 1
    assert timeline.video_tracks[0].clips[0].id == v_clip.id


def test_transform_rotation_allows_negative_and_multi_turn_values():
    """rotation was previously bounded to [0, 360], which rejected valid
    values like -45 (counter-clockwise) or 720 (two full turns, useful for
    spin animations). It should accept a generous range around a single
    turn in either direction rather than clamping to exactly one turn.
    """
    from visualkit.models.clips.visual import Transform

    assert Transform(rotation=-45.0).rotation == -45.0
    assert Transform(rotation=720.0).rotation == 720.0
    assert Transform(rotation=0.0).rotation == 0.0

    with pytest.raises(Exception):
        Transform(rotation=99999.0)
