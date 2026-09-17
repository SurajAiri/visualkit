"""Demonstration of Variables, Coded Visual Clips, and Compound Clip parameter mapping."""

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

print("=== 1. Coded Visual Clip with Canvas and AI Variable Descriptions ===")
infographic = CodedVisualClip(
    id="chart_clip",
    code="""
    <div style="width: 100%; height: 100%; background: {{ bg_color }};">
        <h1>{{ title }}</h1>
        <div class="stat">{{ metric_val }}</div>
    </div>
    """,
    canvas_size=Size(width=1920, height=1080),
    auto_scale=True,
    variables={
        "title": {
            "type": "string",
            "default": "Quarterly Performance",
            "label": "Chart Headline",
            "description": "Short headline (max 5 words) describing the graphic metric.",
        },
        "bg_color": Variable(
            name="bg_color",
            type=VariableType.COLOR,
            default="#1a1a2e",
            label="Background Color",
            description="Hex color code for the background container.",
        ),
        "metric_val": Variable(
            name="metric_val",
            type=VariableType.STRING,
            default="+142%",
            label="Key Metric",
            description="Stat string with sign/unit, e.g. +45%, $2.4M.",
        ),
    },
)

print(f"Canvas: {infographic.canvas_size.width}x{infographic.canvas_size.height}")
print(f"Auto-scale: {infographic.auto_scale}")
print("Default resolved variables:", infographic.get_resolved_variables())

print("\n=== 2. Compound Clip with Parameter Mappings for AI Agents ===")
inner_timeline = Timeline()
inner_timeline.add_clip(
    TextClip(id="intro_subtitle", text="Monthly Report", duration=Time.from_seconds(5))
)
inner_timeline.add_clip(infographic)

template_clip = CompoundClip(
    id="template_infographic_slide",
    duration=Time.from_seconds(5),
    inner_timeline=inner_timeline,
    exposed_parameters=[
        ExposedParameter(
            name="headline",
            target_clip_id="chart_clip",
            target_variable="title",
            label="Headline Text",
            description="Main headline displayed at the top of the chart.",
        ),
        ExposedParameter(
            name="statistic",
            target_clip_id="chart_clip",
            target_variable="metric_val",
            label="Metric Statistic",
            description="Key percentage or dollar amount to highlight.",
        ),
        ExposedParameter(
            name="subtitle",
            target_clip_id="intro_subtitle",
            target_variable="text",
            label="Subtitle",
            description="Small contextual label below the title.",
        ),
    ],
)

print("\n--- Inspect Child Variables Grouped by Child Clip ID ---")
for clip_id, vars_dict in template_clip.get_child_variables().items():
    print(f"Clip [{clip_id}]:")
    for var_name, var_obj in vars_dict.items():
        print(f"   • {var_name} ({var_obj.type}): {var_obj.label} -> '{var_obj.resolve_value()}'")
        print(f"     AI Hint: {var_obj.description}")

print("\n--- AI Agent setting parameters on the Compound Clip ---")
template_clip.set_parameter("headline", "AI Revolution in Video")
template_clip.set_parameter("statistic", "10x Speedup")
template_clip.set_parameter("subtitle", "Annual Impact Analysis")

# Verify inner clips updated
print("\n--- Updated Inner Values ---")
_, updated_text = inner_timeline.get_clip("intro_subtitle")
print(f"TextClip text: '{updated_text.text}'")

_, updated_chart = inner_timeline.get_clip("chart_clip")
print(f"Chart variables: {updated_chart.get_resolved_variables()}")

print("\n--- Round-trip JSON Serialization ---")
serialized = template_clip.model_dump_json(indent=2)
restored = CompoundClip.model_validate_json(serialized)
print(f"Successfully serialized and restored CompoundClip '{restored.id}' with {len(restored.exposed_parameters)} exposed parameters.")
