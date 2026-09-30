```
SREP:            0
Title:           Add segments to outputs: cut-downs and speed changes
Author:          rs-scene-render maintainers
Status:          Draft
Type:            Standards
Created:         2026-09-30
Schema-Version:  1.2
```

# SREP 0 — Add segments to outputs: cut-downs and speed changes

## Abstract

An `<output>` can hold `<segment>` children. Each segment takes a span of the composition (by time or by
marker) and plays it at a speed, or through a time-remap curve; the output plays its segments one after
another, joined by cuts or transitions. Picture, audio and captions all follow the same time map, audio keeps
its pitch by default, and each segment may re-aim the layout's reframing focus. One long document then
declares its own short cut-downs (for example three to five vertical Shorts from a long video), reusing the
document's layouts, safe areas and caption tracks, with no editing outside the format.

## Motivation

The usual publishing plan for a long explainer is the long video plus several short vertical cut-downs. Today
an `<output>` can render only one contiguous range (`start`, `end`) at the composition's own speed, so a
cut-down is made outside the format:

- the vertical composition is rendered at unusual frame rates (50/3, 12, 16 fps) so that FFmpeg can re-time
  the pieces into faster sections;
- the pieces are spliced with FFmpeg;
- sound effects are stretched with a separate time-stretching tool;
- the audio is re-mixed in a script;
- captions are burned in afterwards with FFmpeg.

None of it is in the document, none of it is repeatable from the document alone, and the captions and audio
drift unless every step is redone by hand when the long video changes. The pieces the format already has
(layouts with reframing, safe areas, burned captions from transcriptions, pitch-preserving audio speed on
tracks, time remapping on layers, transitions) cover the parts; what is missing is a way to say which spans an
output plays, and how fast.

## Specification

### Syntax

```xml
<!-- outputType: segment joins the choice of children -->
<xs:element name="segment" type="segmentType"/>

<!-- outputType: two new attributes -->
<xs:attribute name="audioTracks" type="xs:IDREFS">
  <xs:annotation><xs:documentation>
    The audioMix tracks this output plays, in composition time and through its segments; all tracks
    when absent.
  </xs:documentation></xs:annotation>
</xs:attribute>
<xs:attribute name="joinFade" type="nonNegativeDecimal" default="0.01">
  <xs:annotation><xs:documentation>
    Seconds of equal-power audio crossfade centred on each cut between segments.
  </xs:documentation></xs:annotation>
</xs:attribute>

<!-- outputType: output-time audio (for example a music bed made for the cut-down) -->
<xs:element name="audioTrack" type="audioTrackType"/>

<xs:complexType name="segmentType">
  <xs:annotation><xs:documentation>
    A span of the composition played by this output. The span is from..to (seconds) or fromMarker..toMarker,
    played at speed; a timeRemap child instead maps segment time (key/@time, from 0) to composition time
    (key/@value), which expresses ramps, freezes and reversals. The output plays its segments in document
    order. transition joins this segment to the next one.
  </xs:documentation></xs:annotation>
  <xs:sequence>
    <xs:element name="timeRemap" type="timeRemapType" minOccurs="0"/>
  </xs:sequence>
  <xs:attribute name="id" type="xs:ID"/>
  <xs:attribute name="from" type="xs:double"/>
  <xs:attribute name="to" type="xs:double"/>
  <xs:attribute name="fromMarker" type="xs:IDREF"/>
  <xs:attribute name="toMarker" type="xs:IDREF"/>
  <xs:attribute name="speed" type="positiveDecimal" default="1"/>
  <xs:attribute name="audio" default="stretch">
    <xs:simpleType><xs:restriction base="xs:string">
      <xs:enumeration value="stretch"/><xs:enumeration value="resample"/><xs:enumeration value="mute"/>
    </xs:restriction></xs:simpleType>
  </xs:attribute>
  <xs:attribute name="focusX" type="unitDecimal"/>
  <xs:attribute name="focusY" type="unitDecimal"/>
  <xs:attribute name="transition" type="transitionKindType"/>
  <xs:attribute name="transitionDuration" type="positiveDecimal" default="0.5"/>
</xs:complexType>
```

`transitionKindType` names the existing enumeration of `transition/@type` (cut, crossfade, wipe, and so on),
factored out so that both elements share it; no value is added or removed.

```xml
<sch:pattern id="p61">
  <sch:rule context="output[segment]">
    <sch:assert id="C54" test="not(@start or @end)">an output with segments cannot also set start or end.</sch:assert>
  </sch:rule>
  <sch:rule context="segment">
    <sch:assert id="C55" test="timeRemap or ((@from or @fromMarker) and (@to or @toMarker))">a segment needs from (or fromMarker) and to (or toMarker), or a timeRemap.</sch:assert>
    <sch:assert id="C56" test="not(@from and @to) or number(@to) &gt; number(@from)">segment to must be after from.</sch:assert>
    <sch:assert id="R38" test="(not(@fromMarker) or /scene/markers/marker[@id=current()/@fromMarker]) and (not(@toMarker) or /scene/markers/marker[@id=current()/@toMarker])">segment markers must name markers.</sch:assert>
  </sch:rule>
</sch:pattern>
```

`segment` and an `audioTrack` inside `output` are new elements: documents using them declare the version this
SREP lands in, and the version gate lists `output/segment` and `output/audioTrack` beside the other elements of
that version.

### Semantics

**The time map.** Let an output have segments S₁ … Sₙ in document order. For a segment with a span, a = `from`
(or the time of `fromMarker`), b = `to` (or the time of `toMarker`), s = `speed`; its output duration is
dᵢ = (b − a)/s and its map is

    c(u) = a + s·u,  0 ≤ u < dᵢ

where u is time since the segment's start in the output. For a segment with a `timeRemap`, c(u) is the remap
curve evaluated at u (keys, interpolation and `defaultInterpolation` as for layers), dᵢ is its last key's time,
and `speed`, `from`, `to` and the markers are ignored. Segment i starts at output time Tᵢ = d₁ + … + dᵢ₋₁, and
the output lasts T = d₁ + … + dₙ. An output without segments behaves as today.

**Picture.** The frame at output time t, with Tᵢ ≤ t < Tᵢ₊₁, is the composition evaluated at composition time
c(t − Tᵢ), laid out through the output's layout and variant exactly as today. Every sub-frame sample (motion
blur, frame blending) is taken at its own output time and mapped the same way, so blur spans the composition
time the shutter actually covers at that speed. Spans may repeat, overlap, run backwards (through
`timeRemap`) or skip; the composition is evaluated at whatever times the map gives.

**Reframing.** When the output's layout reframes (`reframe` with `focusX`, `focusY`), a segment's `focusX` and
`focusY` replace the layout's focus for that segment's frames.

**Joins.** Without `transition` (or with `cut`), segment i ends and segment i+1 begins at Tᵢ₊₁. With a
transition of duration δ = min(`transitionDuration`, dᵢ, dᵢ₊₁), the join covers output time
[Tᵢ₊₁ − δ/2, Tᵢ₊₁ + δ/2]: the outgoing segment's map continues past its end and the incoming segment's map
starts before its beginning (both extended linearly with their end speeds), and the two pictures are combined
by the transition as `transition` elements combine their nodes, with `curve` ease-in-out. The output duration is
unchanged.

**Audio.** For each segment, the audio is the composition's mix over the composition-time span the segment
plays (the selected `audioTracks`, with their effects, ducking and buses, as the composition mixes them),
brought to the segment's output duration:

- `stretch` keeps pitch: a pitch-preserving time-stretch whose output length is exact to the sample; a
  440 Hz tone stays at 440 Hz;
- `resample` changes pitch with speed (varispeed): pitch scales by s;
- `mute` gives silence.

For a `timeRemap` segment the rate follows the curve's slope sample by sample; reversed spans play reversed.
Consecutive segments are joined by an equal-power crossfade of `joinFade` seconds centred on the cut, or over
the transition's interval where there is one. `audioTrack` children of the output are then mixed in output
time (their `start` is output time), as a music bed or sound made for this output; their ducking may name
composition tracks, which duck in output time.

**Captions.** Caption tracks stay in composition time, including transcriptions made by the resolve step.
Each cue and each word, with composition interval [p, q], appears in the output once for every segment whose
span meets it, at the output interval given by mapping max(p, a) and min(q, b) through that segment (swapped
when the map runs backwards). A cue cut by a segment boundary keeps only its words inside the span; a cue with
no word left is dropped. Burned captions and sidecar files both use the mapped cues. Posters and thumbnails
(`time`) are in output time.

**Output range and frame rate.** The output's `fps` is the delivery rate; nothing in the composition needs to
be rendered at another rate for a speed change.

### Defaults and the neutral case

An output without `segment` children, `audioTracks` or `audioTrack` renders exactly as before. `joinFade` only
applies between segments.

## Rationale

- **On the output, not the composition.** The long video stays the one source; each cut-down is a delivery
  choice, like `layout` and `variant` already are. Changing the long video updates every cut-down.
- **Reuse.** Speed ramps, freezes and reversals reuse `timeRemap` (keys in segment time to composition time),
  joins reuse the transition kinds, reframing reuses the layout's `focusX`/`focusY`, captions reuse the
  existing tracks and burn-in, pitch-preserving speed reuses the behaviour of `audioTrack/@speed` with
  `preservePitch`.
- **Mapping every sample.** Evaluating the composition at the mapped time for every frame and sub-frame
  sample is what makes a speed change look right (motion blur follows the real motion) and is exact, because
  a frame is a function of time alone.
- **Captions by mapping, not re-transcription.** The words and their times already exist; mapping them keeps
  captions in step with picture and sound without another resolve run.
- **Precedent.** Edit decision lists (CMX 3600), OpenTimelineIO clips with `source_range` and linear time
  warps, and FCPXML clips with `timeMap` describe cut-downs the same way: source spans, a rate per span, and
  transitions between them.

## Rejected alternatives

- **`<clip>` as the element name.** `clipIn` and `clipOut` already mean trimming a source on audio tracks, and
  "clip" names media assets in documents; `segment` avoids the collision.
- **A speed attribute on the whole output.** It covers only one case; cut-downs mix normal-speed and faster
  spans.
- **A separate short document that includes the long one.** `include` brings in the composition but not its
  audio mix, and has no time remapping; it would duplicate the mix and captions by hand.
- **Rendering at another frame rate and re-timing afterwards.** That is today's workaround; it cannot ramp,
  loses motion blur fidelity, and leaves audio and captions to separate tools.
- **Platform limits in the schema** (for example a 60-second maximum). Platforms change them; a delivery
  warning is enough.

## Backwards compatibility

Every valid document stays valid and renders the same. The new elements require the version this SREP targets
(1.2, alongside the other 1.2 drafts, or the next minor version if it lands separately).

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | time map in the encode loop; per-segment audio from the existing mixer and WSOLA stretch; caption mapping; transition joins from the existing transition compositor | |
| C (`c-scene-render`) | pending | same | |
| Python (`py-render`) | pending | same | |
| JavaScript (`js-render-engine`) | pending | same | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `conformance/cases/srep-0000-segment-map.xml` | a composition whose background holds red on [0, 1), green on [1, 2) and blue on [2, 3); an output with segments from 2 to 3 at speed 1, then 0 to 1 at speed 2. Frames at output times 0.5 and 1.25 show blue and red | region colour, 3 levels |
| `conformance/cases/srep-0000-segment-remap.xml` | a segment whose `timeRemap` runs backwards: the frame at segment time 0.25 shows the composition at the mapped time | region colour, 3 levels |
| engine test: audio | a 440 Hz tone through a speed-2 segment keeps 440 Hz with `stretch` and plays 880 Hz with `resample`; segment audio lengths are exact to the sample | ± 1 Hz |
| engine test: captions | a word spanning a segment boundary appears only for its inside part; words from skipped spans are absent | exact times |

## Open issues

- The compatibility kit renders frame 0 of the document's composition. These cases need the runner to render a
  named output at a given output time; that is a small extension to `run.py`.
- Whether `fromMarker` and `toMarker` should also accept marker ranges (`marker/@duration`) as one attribute.
- Rule ids C54–C56, R38 and pattern p61 are provisional until the editor assigns them.

## References

- CMX 3600 edit decision list format.
- OpenTimelineIO: `Clip.source_range`, `LinearTimeWarp` (https://opentimelineio.readthedocs.io/).
- FCPXML: `timeMap` and `conform-rate` (Apple Final Cut Pro XML reference).
- Verhelst and Roelands 1993, "An overlap-add technique based on waveform similarity (WSOLA) for high quality
  time-scale modification of speech", ICASSP.

## History

- 2026-09-30: first draft.
