# Roadmap / not built yet

The `notes/` folder (`notes/editor.md`, `notes/clips.md`) describes a
larger vision: an agent-facing "editor" layer on top of the model this
codebase already implements — script/take refinement, an asset store with
AI-generated and searched content, versioning/checkpoints, copy-paste of
clips and scenes, and more. **None of that layer exists in code today.**
This page exists so you don't write code assuming it does, or read
`notes/` as a spec for the current API.

What's actually implemented, versus what `notes/` describes:

| `notes/` concept | Status |
|---|---|
| Timeline, Track, Clip hierarchy | ✅ Implemented — this is `visualkit.models` |
| `CompoundClip` as reusable template with exposed parameters | ✅ Implemented |
| `CodedVisualClip` for AI/hand-written HTML/CSS/JS visuals | ✅ Implemented (HTML/CSS/JS only — `notes/editor.md` mentions Manim/npm-package visuals "for now"/"later"; only the HTML/CSS/JS compiler exists) |
| Keyframes, chroma key, masking, animation presets | ✅ Implemented (FFmpeg exporter only — see [07-exporting.md](07-exporting.md)) |
| Extended text styling (outline, shadow, gradient, spacing) | ✅ Implemented |
| Video/DaVinci Resolve export | ✅ Implemented |
| Asset resolvers (`asset://` URIs) | ✅ Implemented |
| **Transitions** (`Track` item `Transition: type, duration`) | ❌ Not built |
| **Per-character / typewriter text animation** | ❌ Not built — measured to fail with real ffmpeg during the last review pass and considered out of scope; the `animation` preset system (fade/slide/pop/wipe) is what exists instead |
| **"Overall" animation phase** (as opposed to just in/out) | ❌ Not requested/built — `ClipAnimation` only has `in_preset`/`out_preset` |
| **Compound-level keyframes / chroma_key / masking / animation** | ❌ `CompoundClip` doesn't carry these fields itself, only `transform`. A child clip inside a compound keeps its own keyframes/effects when flattened — see the composition caveat in [04-templates-and-compounds.md](04-templates-and-compounds.md) |
| **Refiner** (cut/trim main track by removing silences/bad takes, script-to-TTS) | ❌ Not built |
| **Assets / Store** (virtual asset filesystem, AI-generated content, searchable local asset index) | ❌ Not built — `AssetResolver` is the only asset-indirection mechanism that exists, and it's a simple path-mapping callable, not an index/store |
| **Versioning / checkpoints, copy-paste of clips/scenes** | ❌ Not built |
| `RefinedScriptClip` | ❌ Explicitly marked "doesn't exist, ignore this" in `notes/clips.md` itself |

If you're building an agent-facing editing layer *on top of* this
library, treat `notes/` as background/inspiration for that layer's design,
not as documentation of an existing API — and treat this `docs/` folder,
not `notes/`, as the source of truth for what you can call today.
