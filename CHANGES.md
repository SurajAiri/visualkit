# VisualKit — Review Findings & Fixes

This document summarizes every bug found and fixed during a full review of
the codebase, in the order they were made. The library's own git history
(included) has the full diff for each fix, one commit each.

Baseline before any fix: 24 tests passing, 2 failing (both due to no
Chrome/Chromium in the review sandbox — a pre-existing environment gap, not
a code bug).

Final state after all fixes: **48 tests passing**, same 2 pre-existing
environment-only failures (unrelated to any change made here).

---

## fix: enforce extra='forbid' + validate_assignment across all models

Every model previously inherited pydantic.BaseModel directly, which
defaults to extra='ignore' -- unknown/misspelled keyword arguments were
silently dropped instead of raising. This is confirmed by the repo's own
playground/fun.py, which passes an entirely wrong, stale API shape
(Timeline(main_track=Track(visual=[...], audio=[...]))) and silently
'succeeds' while producing an empty, useless Timeline.

Introduces visualkit.utils.base_model.VisualKitModel as the shared base
for all ~12 models in the schema, configured with:
  - extra='forbid': typo'd/unknown fields now raise ValidationError
    immediately at construction instead of vanishing silently.
  - validate_assignment=True: post-construction attribute mutation
    (clip.speed = -1) re-validates instead of bypassing field
    constraints.

No existing test depended on the old silent-drop behavior; full suite
still green (24 passed, 2 pre-existing environment-only failures from
missing Chrome in this sandbox).

---

## fix: Timeline.add_clip track_index + Track ripple-insert bugs

1. Timeline.add_clip(clip, track_index=N): previously, if N was beyond the
   current track count, exactly one new track was appended and the clip
   was placed there -- NOT at index N. Requesting track_index=5 on an
   empty timeline silently placed the clip on track 0. Now tracks are
   provisioned up to and including index N, so the clip always lands
   where the caller asked.

2. Track.add_clip(clip, mode=RIPPLE): previously only shifted existing
   clips whose start was >= the new clip's start. If the new clip's
   insertion point fell *inside* an already-existing clip's span (e.g.
   inserting at t=3 into a clip spanning [0, 5)), nothing shifted and the
   track silently ended up with an overlapping/invalid state -- despite
   the caller explicitly asking for ripple (no-overlap) semantics. This
   case can't be resolved by shifting alone (it would require splitting
   the existing clip, which add_clip does not do), so it now raises
   InvalidTrackOperationError instead of silently corrupting the track.
   Validation happens in a pass separate from mutation so a rejected
   insert never partially ripples the track, regardless of clip order.

Adds tests/test_timeline.py with regression coverage for both. Also
adds .gitignore and removes accidentally-tracked __pycache__ output.

Full suite: 32 passed (8 new), 2 pre-existing environment-only failures
(missing Chrome in this sandbox, unrelated to this change).

---

## fix: sibling/nested CompoundClips no longer collide on flattened audio tracks

TimelinePipeline._flatten_compound_clip previously routed a compound's
inner audio tracks to target_timeline.audio_tracks[inner_a_idx] using
only the *inner* track index -- completely ignoring which compound (or
which outer video track) the audio came from. Two independent
CompoundClips each using their own inner audio track 0 would have their
audio silently merged onto the same destination audio track (A0),
even though they're unrelated and may not even overlap in time.

Fix: thread a base_a_track_idx through _flatten_compound_clip (mirroring
the existing base_v_track_idx convention already used for video), sourced
from whichever audio track the compound's own CompoundAudioClip companion
actually occupies -- i.e. its reserved 'seat' on the audio lane, found via
the new _companion_audio_track_index() helper. Falls back to the video
track index if no companion exists (e.g. compound added directly to a
track rather than through Timeline.add_clip's auto-companion routing).
Nested compounds resolve their own base the same way, scoped to their
parent's inner_timeline.

Verified: two sibling compounds' audio now lands on separate flattened
tracks instead of colliding; nested-compound audio stays isolated from
sibling audio clips at the same level. The pre-existing single-compound
test (test_flatten_compound_timeline) still passes with its exact
original assertions -- this fix is purely additive for the
multi-compound case.

Adds 2 new regression tests to test_timeline_pipeline.py. Full suite:
34 passed, 2 pre-existing environment-only failures (missing Chrome).

---

## fix: CompoundClip.speed now correctly retimes (compresses) inner content

Previously, setting compound.speed=2.0 only multiplied each inner leaf
clip's own .speed field -- telling the renderer to play that clip's
underlying media twice as fast -- but left timeline_start and duration
completely unscaled. A 4-second compound at 2x speed still occupied a
full 4 seconds of outer-timeline span with its children at their
original, uncompressed positions, which contradicts what 'speed' should
mean for a container clip: a 2x-speed compound's 4s of inner content
should occupy 2s of outer timeline.

Fix (in TimelinePipeline._flatten_compound_clip):
  - Leaf clip timeline_start/duration are now divided by the accumulated
    effective_speed before being placed on the outer timeline, in
    addition to the existing effective_speed multiplication of the
    leaf's own .speed field.
  - A nested compound's *own* position within its parent's local time
    (compound.timeline_start) is now divided by parent_speed before
    being folded into the accumulated offset -- otherwise a nested
    compound sitting at local t=4s inside a 2x-speed ancestor would
    incorrectly appear at t=4s on the root timeline instead of t=2s.
  - Audio children get the identical treatment for consistency with
    video.

speed=1.0 (the default, and what every existing test/example uses)
divides by 1.0 and is a pure no-op, so this is purely additive:
verified via the existing test_flatten_compound_timeline (unchanged
assertions) plus every example/playground script producing identical
output to before.

Adds 5 new regression tests (TestCompoundSpeedRetiming) covering:
single-level 2x speed, the 1x no-op guard, a nested compound's own
position being compressed by an ancestor's speed, multiplicative
speed compounding across two nesting levels (2x * 3x = 6x), and audio
children receiving the same treatment as video.

Full suite: 39 passed, 2 pre-existing environment-only failures.

---

## fix: FFmpegVideoExporter HTML injection, broken no-Chrome fallback, silent skips

Three issues in FFmpegVideoExporter._render_text_to_image / export():

1. clip.text (and font_color) were interpolated into an HTML page
   completely unescaped. Text containing <, >, or & would corrupt the
   layout or be interpreted as markup rather than displayed literally.
   Now escaped via html.escape().

2. When no Chrome/Chromium was found, the method silently returned the
   intermediate .html file as if it were a rendered image. Back in
   export(), the .html suffix doesn't match the recognized image
   extensions, so it was passed to ffmpeg as a *video* input -- producing
   a non-obvious, hard-to-diagnose ffmpeg failure instead of a clear
   error. Now raises RuntimeError immediately with an actionable message,
   consistent with how CodedVisualCompiler already handles missing Chrome.

3. Long text had no wrapping/max-width, so it could render off-canvas.
   Now soft-wrapped via textwrap before being escaped and inserted.

Also: the rendered-text cache directory was a hardcoded relative path
(.visualkit_cache/rendered_text), meaning its location depended on the
caller's current working directory -- surprising for a library. It's now
a  constructor parameter, consistent with how
CodedVisualCompiler already exposes one. Added logger.warning() calls
where video/audio clips were previously skipped silently on a missing
source file.

Adds TestRenderTextToImageEscaping (4 tests) using a monkeypatched
_find_chrome_executable so behavior is deterministic regardless of
whether Chrome is actually installed in the environment running the
tests.

Full suite: 43 passed, 2 pre-existing environment-only failures.

---

## fix: FCPXML export dropped all audio; DRY out duplicated exporter helpers

generate_fcpxml() previously only ever emitted <asset>/<clip> elements for
video tracks -- audio tracks were never iterated at all, so exporting to
.fcpxml silently produced a video-only project with no audio, while the
legacy generate_xmeml() (FCP7 XML) path did include audio. This asymmetry
between the two supported DaVinci Resolve export formats was undocumented
and untested.

Fix: generate_fcpxml() now also emits an <asset hasAudio="1"> resource
and a lane-connected <clip><audio ref=...></clip> spine entry for every
clip on every audio track, mirroring the existing video-track handling.
Audio tracks are placed on negative spine lanes (video occupies lane 0+)
to keep them out of the video compositing stack while preserving each
track's relative order. Added an honest docstring caveat: the overall
FCPXML spine/lane layout used here hasn't been verified against a real
DaVinci Resolve import, and generate_xmeml is the more established path
for that specific target if FCPXML import doesn't behave as expected.

Also: _resolve_source() was duplicated verbatim across
FFmpegVideoExporter and DaVinciResolveExporter. Moved it (plus a new
_resolve_source_uri() helper that resolves a source AND converts it to a
file:// URI) onto BaseExporter, and simplified both generate_xmeml's
video/audio pathurl construction and generate_fcpxml's asset src
construction to use the shared helper instead of repeating the
exists-check-then-as_uri-or-file-prefix logic inline.

Adds 2 new tests: FCPXML audio presence/asset-flagging, and multiple
audio tracks landing on distinct negative lanes. Full suite: 44 passed,
2 pre-existing environment-only failures.

---

## cleanup: remove dead scaffold, fix stale playground script, write real README

- Delete main.py: leftover project-template boilerplate (a bare
  print-and-exit main()) that duplicated __main__.py and had no relation
  to the library.

- Fix playground/fun.py: it constructed Timeline(main_track=Track(
  visual=[...], audio=[...])), a nonexistent/stale API shape from an
  earlier design. Before the extra=forbid fix, this silently 'succeeded'
  while producing an empty, useless Timeline -- it's exactly the
  real-world case that motivated that fix. Updated it to use the current
  Timeline.add_clip(clip, track_index=N) API; it now actually runs and
  produces a correct, non-empty timeline.

- Replace README.md: it was an unfilled project-template stub (placeholder
  'Add installation commands' sections, a broken/malformed code fence, and
  a link to a docs/architecture.md file that doesn't exist in this repo).
  Replaced with real documentation: requirements (ffmpeg + Chrome, and why
  each is needed), install/quick-start, an examples table, a description
  of each core concept (Timeline/Track, clip types, CompoundClip,
  CodedVisualClip, flattening) grounded in the actual current API, and
  export guidance -- including an honest note that FCPXML's spine/lane
  layout hasn't been verified against a real DaVinci Resolve import,
  pointing to XMEML as the more established path for that target.

---

## fix: missing top-level exports; widen Transform.rotation bound

1. Track, VideoTrack, AudioTrack, TrackKind (already exported from
   visualkit.models) and DictAssetResolver (already exported from
   visualkit.engine) were never re-exported from the top-level visualkit
   package, so e.g. visualkit.Track raised AttributeError despite being a
   documented, commonly-needed public type. Added them to
   visualkit/__init__.py's imports and __all__.

2. Transform.rotation was bounded to [0, 360], which rejected valid,
   ordinary values: -45 (counter-clockwise rotation) and anything past a
   single turn (e.g. 720 for a two-spin animation -- explicitly relevant
   given the keyframe/animation work noted as planned in notes/clips.md).
   Widened to [-3600, 3600] (10 turns either direction) -- generous enough
   for realistic use, still rejecting obviously-wrong input (e.g. a
   radians value passed by mistake).

Verified via ruff (clean across src/ and tests/) plus new tests:
tests/test_package_exports.py (top-level export coverage, including a
'every name in __all__ is actually importable' guard against future
drift) and a rotation-bound test in test_variables_and_clips.py.

Full suite: 48 passed, 2 pre-existing environment-only failures.

---

## feat: split, trim_in/trim_out, ripple_delete, duplicate_clip, get_clip_at

The schema could already represent a trim or split correctly --
Source.start plus duration is enough information -- but nothing exercised
that arithmetic, and it's exactly the kind of thing that's easy to get
subtly wrong (three fields -- timeline_start, duration, source.start --
that all have to move together, correctly scaled by speed). Adds the
missing primitives to Track and Timeline:

1. Track.split_clip(clip_id, at_time) / Timeline.split_clip(...): mutates
   the original clip into the first half (keeps its id) and appends a new
   second half. For any clip with a `source` field, the second half's
   source.start is advanced by delta * speed, not delta -- at speed=2.0,
   one timeline second consumes two source seconds, so copying the raw
   offset would export wrong even though it looks right in an editor that
   doesn't account for speed. Cross-links linked_clip_id both ways for
   clip types that carry it. Raises InvalidSplitError for CompoundClip
   (and its CompoundAudioClip companion): splitting one would require
   deep-copying inner_timeline and re-deriving in/out points for every
   clip it contains, including any that themselves straddle the split
   point, which isn't attempted here. If the original clip is a
   CodedVisualClip that had already compiled, both halves have their
   compiled media_source cleared and compile_status reset to PENDING --
   the compiler bakes `duration` into both its cache key and its ffmpeg
   -t argument, so reusing the pre-split render for either half would
   silently ship stale output at export time.

2. Track.trim_in / Track.trim_out / Timeline.trim_in / Timeline.trim_out:
   same speed-scaled source.start math as split for trim_in (trim_out
   never touches source.start, since shortening or lengthening the tail
   doesn't change what point in the source the clip starts from). Both
   directions are supported -- trimming a handle later/shorter or
   earlier/longer, not just shrinking. trim_in raises
   InvalidTrackOperationError for CompoundClip: it has no field recording
   "this much of inner_timeline already consumed," so advancing
   timeline_start would delay its content rather than skip into it, which
   is the wrong result for a head trim. trim_out has no such problem and
   works uniformly across every clip type. Both raise
   InvalidTrackOperationError if the result would leave a clip with
   non-positive duration, or (trim_in only) would need source.start below
   zero. Timeline.trim_out additionally trims a CompoundClip's linked
   CompoundAudioClip companion to the same absolute new_out, so the two
   lanes stay in sync.

3. Track.ripple_delete / Timeline.ripple_delete: the exact inverse of
   add_clip(mode=RIPPLE) -- every clip whose start is at or after the
   removed clip's end is shifted left by the removed clip's duration.
   Timeline.ripple_delete also ripple-deletes a CompoundClip's linked
   CompoundAudioClip companion from its own track, so deleting a compound
   doesn't leave a dangling orphan on the audio lane with the two lanes
   now misaligned relative to each other.

4. Track.duplicate_clip / Timeline.duplicate_clip: deep-copies a clip with
   a fresh id, clearing linked_clip_id (a duplicate is a new, independent
   clip, not the other half of whatever the original was linked to from a
   prior split). Defaults to placing the copy immediately after the
   original so the common case doesn't land on top of it under OVERLAP
   mode. Timeline.duplicate_clip also duplicates and cross-links a
   CompoundClip's CompoundAudioClip companion, mirroring how add_clip
   auto-creates and routes one for a freshly-added CompoundClip.

5. Track.get_clip_at(time) / Timeline.get_clips_at(time): "what's under
   the playhead" previously required scanning a track's clips by hand,
   since only ID-based lookup existed. Split into two names on purpose --
   a single track can have at most one clip active at a given instant,
   but a timeline composites multiple tracks simultaneously, so the
   cross-timeline version returns every (track, clip) match rather than
   just the first.

Also, since validate_clips()/validate_tracks() existed but were never
wired into any mutating call, so nothing stopped e.g. add_clip(mode=
OVERLAP) from silently producing an invalid, overlapping track: every new
method above defaults to validate=True, checking for overlaps *before*
mutating (mirroring the existing ripple-insert convention of validating
in a pass separate from mutation, so a rejected call never partially
applies) and raising the previously-unused TimelineValidationError. Also
adds an opt-in validate: bool = False parameter to the existing
Track.add_clip / Timeline.add_clip, so OVERLAP-mode inserts can now ask
for the same check -- default stays False so no existing call site's
behavior changes.

Also fixes move_clip_track(clip_id, new_track_id): it previously always
called add_clip with OVERLAP regardless of what the caller wanted, so
requesting a rippling move silently fell back to overlap semantics. Now
takes mode: InsertMode = InsertMode.OVERLAP (plus the same validate
passthrough) and actually uses it.

slip/slide are intentionally not included -- each touches enough
additional state (slide in particular affects three clips' worth of
timing at once) to warrant its own review rather than being folded in
here.

Adds tests/test_clip_editing.py (54 new tests) covering the speed-scaled
source math in both directions for split and trim_in, the CompoundClip/
CompoundAudioClip disallow-or-cascade decisions for every new method, the
CodedVisualClip stale-compile reset for split/trim_in/trim_out, the
overlap-rejection-before-mutation guarantee, and the move_clip_track mode
fix.

Full suite: 101 passed, same 3 pre-existing environment-only failures
(missing Chrome in this sandbox, unrelated to this change).

---
