# VisualKit Documentation

VisualKit is a Python engine for building video timelines in code — media
clips, text, audio, reusable "compound" templates, and code-rendered
(HTML/CSS/JS) visuals — and exporting them to a standalone video or to a
DaVinci Resolve project.

This `docs/` folder is the full guide. The
[top-level `README.md`](https://github.com/SurajAiri/visualkit/blob/main/README.md)
(the repo root one, one level up from here — linked via GitHub rather than a
relative path so this page also builds cleanly as an MkDocs site; update the
repo slug here together with `mkdocs.yml`'s `repo_url` if it changes)
stays as the short pitch + quick start; everything below goes deeper, is kept
in sync with the actual source (`src/visualkit/`) rather than aspirational,
and is written for two readers at once:

- **Humans** building or maintaining a video pipeline with VisualKit.
- **Agents** (LLM coding agents, or an LLM driving VisualKit at runtime to
  assemble videos) that need an accurate, load-bearing mental model before
  writing code against this library — not just a features list.

Where something differs for an agent (a decision an agent has to make that a
human would do by feel, a footgun worth flagging up front), it's called out
in a callout block like this:

> **Agent note:** ...

## Reading order

| # | Doc | What it's for |
|---|-----|----------------|
| 1 | [Getting started](01-getting-started.md) | Install, requirements, your first timeline and export |
| 2 | [Core concepts](02-concepts.md) | Timeline / Track / Clip model, `Time`, `flatten()`, immutability, atomicity |
| 3 | [Clips reference](03-clips-reference.md) | Every clip type, its fields, and its methods, in one place |
| 4 | [Templates & compound clips](04-templates-and-compounds.md) | Building reusable, parameterized scenes with `CompoundClip` |
| 5 | [Coded visuals](05-coded-visuals.md) | Authoring HTML/CSS/JS infographics/animations that render to media |
| 6 | [Keyframes & effects](06-keyframes-and-effects.md) | Keyframed transforms, chroma key, masks, animation presets (FFmpeg-only) |
| 7 | [Exporting](07-exporting.md) | `export_to_video`, `export_to_resolve`, asset resolvers |
| 8 | [Errors & validation](08-errors-and-validation.md) | The exception hierarchy, what's validated and when, atomic edits |
| 9 | [Agent guide](09-agent-guide.md) | Decision tree, ready-made recipes, and a pre-flight checklist for code-generating agents |
| 10 | [Pitfalls](10-pitfalls.md) | Non-obvious behavior worth knowing before you hit it |
| 11 | [Roadmap / not built yet](11-roadmap.md) | What the `notes/` design docs describe that doesn't exist in code yet |

If you only read one page, make it **[Core concepts](02-concepts.md)** — the
rest builds directly on it — and if you're an agent generating VisualKit
code without a human in the loop, read **[Agent guide](09-agent-guide.md)**
before your first script.

## Where things live in the repo

```
src/visualkit/
├── models/            # The data model: Timeline, Track, Clip subclasses,
│                       #   Transform, keyframes, effects, animation, Variable
│   └── clips/          # BaseClip, VisualClip, MediaClip, TextClip, AudioClip,
│                       #   CompoundClip, CodedVisualClip
├── engine/             # TimelinePipeline (resolve -> compile -> flatten),
│                       #   AssetResolver
├── coded_visual/       # Browser discovery, HTML prep, screenshot/video capture,
│                       #   CodedVisualCompiler, manifest loading
└── exporters/          # FFmpegVideoExporter, DaVinciResolveExporter,
                        #   single-clip preview helpers

examples/               # Runnable, narrated scripts — one per feature area
tests/                  # The actual source of truth for exact behavior
notes/                  # Design notes for an agent-facing "editor" layer
                        #   that is NOT built yet — see 11-roadmap.md
```

When this documentation and the source disagree, the source (and its tests)
win — please open an issue/PR rather than trust the docs blindly for
anything load-bearing.
