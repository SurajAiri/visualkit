# features
## Refiner
**Refining main track with either cutting, trimming and refining the main track with audio/video by removing silences, bad takes, etc or generating audio from script with TTS**
- Script: Edit, Append, Comments, etc.
- Audio/Video files
    - add/remove media
    - reorder media
    - hide/show media: whether to include the media in final main track timeline
- process: (specific, all, unprocessed [default]) [option to force process]
    - script: TTS to generate audio
    - audio/video: process with agent flow
- compile: process unprocessed + cutting based on the audio wave + compiled refine timeline file

## Assets or Store
**Manages the assets that agent will ask assets through, by maintaining an index with virtual file system allowing directory system with cloning original files again**
- AI generated content: Image, Video, Audio
- Online Search content: with plugins for multiple third-party sites
- CodedVisual: LLM for writing codes that is rendered as visual; plugin based [html,js,css (for now), later option to add: manim (python), npm package installed in js, etc]
    - Infographic: with option to reuse the visual changing the variable values
    - Custom Clip: One time clip, for custom clip requirements
- Local Asset Index [third-party plugin extendable]: agent could search for images, audio, video, etc with name or semantic or other options based on requirement for assets (phase-2)

## Editor
**Actual editing commands handler that will be processed by engine to let agent edit the video**
- **timeline**
    - create, remove, duplicate
    - versioning and checkpoint (v2)
    - copy paste clips, scenes (v2)
    - Note: on main track `MainTrack` can be linked that will be a Compound Clip so that can be flatten or trimmed/cut

### Clips 
**Various editing option based on the clip type**
These will be all supported features by these clips.
All: keyframe, asset_path, cut/split, speed
- Compound Clip: the combination of multiple clips 
    - editable: will have option for each input variable or property variable to edit the clip and re-use [mainly used for templates]
    - uneditable: no parameter to change. (e.g. refined main track)
- Audio Clip: in/out animation, volume
- Visual Clip: zoom/pan, (chroma key), position (center), masking
    - Video Clip: linked_audio, transition
    - Text Clip: value, animation, font, 
    - Overlay Clip: animation
    - CodedVisual Clip: will act like normal visual but with one extra step on rendering based on the quality it will render the UI (obviously cache is done)

## Exporter
**Finally export video or timeline that can be imported in professional Video Editor softwares**

**Timeline options**: 
* refined main track export
* edited timeline

**Export Options**: out dir, name
- final video: resolution
- Professional Video Softwares like `Davinci Resolve`.