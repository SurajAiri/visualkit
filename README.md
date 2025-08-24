# VisualKit

High‑performance, pure‑Python toolkit for assembling short form videos from images, video clips, transitions and animated subtitles. VisualKit focuses on a clear, scriptable JSON project format and an efficient OpenCV / NumPy based rendering pipeline.

## Key Features

- Image and video clip support (separate handling for stills vs. clips)
- Rich per‑media motion & stylistic effects (zoom, pans, rotation, shake, bounce, float, ken‑burns, elastic, wave, ripple, etc.)
- Extensive transition set: crossfade, slides, wipes, pushes, zoom/scale variants, circle in/out, blinds, fades to black/white, more
- Subtitle system with animation types (typewriter, fade_in, simple) and automatic multi‑line wrapping
- Multiple adaptive resize strategies (smart, adaptive, gradual, aspect_ratio, fill) to minimize distortion
- Deterministic JSON project description (easy to generate programmatically)
- Modular design: add new effects or transitions with minimal wiring
- Pure CPU implementation; optional future hooks for GPU acceleration

## Installation

Stable (once published to PyPI):

```bash
pip install visualkit
```

From source (development):

```bash
git clone https://github.com/SurajAiri/visualkit.git
cd visualkit
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

## Quick Start

```python
from visualkit import SimpleVideoEditor
import json

with open("simple_editor_test.json", "r") as f:
		project_json = json.load(f)

editor = SimpleVideoEditor()
editor.load_from_json(project_json)
editor.render_video("output.mp4")
```

### Minimal Programmatic Project

```python
from visualkit import SimpleVideoEditor, VideoConfig

project = {
		"config": {"width": 1280, "height": 720, "fps": 30, "codec": "H264"},
		"assets": {
				"img1": {"path": "generated_images/image_01.jpg", "type": "image"},
				"clip1": {"path": "data/test1.mp4", "type": "video"}
		},
		"main_layer": [
				{"type": "media", "media": "img1", "duration": 4.0, "effect": "ken_burns"},
				{"type": "transition", "duration": 1.0, "transition_type": "crossfade"},
				{"type": "media", "media": "clip1", "effect": "none", "duration": 5.0}
		],
		"subtitle_layers": [
				{
						"name": "main_subs",
						"elements": [
								{"start_time": 0.5, "end_time": 3.5, "text": "Hello VisualKit", "animation_type": "typewriter", "typewriter_speed": 18},
								{"start_time": 4.2, "end_time": 8.0, "text": "Video & image effects", "animation_type": "fade_in"}
						]
				}
		]
}

editor = SimpleVideoEditor(VideoConfig(width=1280, height=720, fps=30))
editor.load_from_json(project)
editor.render_video("demo.mp4")
```

## JSON Project Schema (Concise)

```jsonc
{
  "config": {
    "width": 1280,
    "height": 720,
    "fps": 30,
    "codec": "H264",
    "resize_method": "adaptive"
  },
  "assets": {
    "img1": { "path": "generated_images/image_01.jpg", "type": "image" },
    "clip1": { "path": "data/test1.mp4", "type": "video" }
  },
  "main_layer": [
    { "type": "media", "media": "img1", "duration": 5.0, "effect": "zoom" },
    { "type": "transition", "duration": 1.0, "transition_type": "slide_left" },
    { "type": "media", "media": "clip1", "duration": 5.0, "effect": "none" }
  ],
  "subtitle_layers": [
    {
      "name": "main_subtitles",
      "elements": [
        {
          "start_time": 1.0,
          "end_time": 5.0,
          "text": "Welcome",
          "animation_type": "typewriter",
          "typewriter_speed": 15.0
        }
      ]
    }
  ]
}
```

Notes:

- `assets.type` is `image` or `video`.
- For video media, if `duration` is omitted the loader can derive clip length; supplying a shorter duration trims playback.
- `effect` must be in `MediaElement.get_available_effects()`.
- `transition_type` must be in `TransitionElement.get_available_transitions()`.

## Available Effects (Selection)

`none`, `zoom`, `zoom_out`, `brightness`, `blur`, `pan_left`, `pan_right`, `pan_up`, `pan_down`, `rotate_clockwise`, `rotate_counterclockwise`, `shake`, `bounce`, `pulse`, `fade_in`, `fade_out`, `spiral`, `swing`, `sway`, `elastic_zoom`, `rubber_band`, `zoom_bounce`, `zoom_elastic`, `ken_burns`, `float`, `drift`, `hover`, `wave`, `ripple`.

## Available Transitions (Selection)

`none`, `crossfade`, `slide_left`, `slide_right`, `slide_up`, `slide_down`, `slide_diagonal`, `wipe_left`, `wipe_right`, `wipe_up`, `wipe_down`, `wipe_center_out`, `wipe_center_in`, `push_left`, `push_right`, `push_up`, `push_down`, `zoom_in`, `zoom_out`, `scale_up`, `scale_down`, `venetian_blinds`, `vertical_blinds`, `circle_in`, `circle_out`, `fade_to_black`, `fade_to_white`.

## Resize Strategies

Configure via `config.resize_method`:

- `adaptive` (default) – balanced crop/stretch
- `smart` – minimizes distortion with smart cropping
- `gradual` – hybrid crop/stretch progression
- `aspect_ratio` – letterbox / center‑crop preserving aspect
- `fill` – direct stretch (may distort)

## Development Workflow

```bash
ruff check .
python -m visualkit --help  # if CLI added later
```

Run a quick render:

```bash
python main.py
```

## Testing

Add tests under `tests/` then run:

```bash
pytest
```

## Project Structure (Simplified)

```
├── src/visualkit/
│   ├── editor.py          # High-level orchestration
│   ├── media_element.py   # Image & video element classes + effects
│   ├── transitions.py     # Transition implementations
│   ├── text_element.py    # Subtitle & text rendering
│   ├── timeline.py        # Timeline management
│   └── config.py          # VideoConfig dataclass
├── simple_editor_test.json
├── generated_images/
├── data/
└── tests/
```

## Extensibility Guide

1. New Effect
   - Add identifier to `MediaElement.get_available_effects()`.
   - Implement `_apply_<name>` returning a `(H,W,3)` uint8 array.
2. New Transition
   - Add name to `TransitionElement.get_available_transitions()`.
   - Implement `_your_transition` and branch inside `apply`.
3. New Subtitle Animation
   - Extend `AnimationType` enum.
   - Add rendering branch in `TextRenderer.render_subtitle`.

## Performance Tips

- Prefer consistent input resolutions to reduce resizing overhead.
- Keep `fps` only as high as necessary (e.g. 24–30 for most social content).
- Limit extremely large source images when memory constrained; internal enlargement is already performed for motion effects.

## Roadmap

- Audio track & mixing
- CLI packager
- GPU (CUDA / OpenCL) optional acceleration
- More typography controls (font selection, stroke, shadow)\
- Effect/transition easing customization

## Contributing

1. Fork repository
2. Create feature branch (`feat/your-topic`)
3. Implement + add tests
4. Run linting / formatting
5. Submit pull request with clear rationale & before/after context

## License

Distributed under the MIT License. See [LICENSE](LICENSE).

## Acknowledgements

Built on top of OpenCV and NumPy.

---

For advanced architecture notes or design discussions, please refer to the `docs/` directory (if present) or open an issue.
