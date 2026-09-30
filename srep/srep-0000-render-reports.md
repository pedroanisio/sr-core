```
SREP:            0
Title:           Make renders report, measure text and pin fonts
Author:          scene-render maintainers
Status:          Draft
Type:            Standards
Created:         2026-09-30
Schema-Version:  1.2
```

# SREP 0 (draft) — Make renders report, measure text and pin fonts

## Abstract

Four engines render the same document, and none of them says what happened to the picture: text that did
not fit, captions too fast to read, attributes that validate and do nothing, fonts the host swapped,
constructs the engine left out. This SREP adds six things, in six parts that the editor can accept
separately:

- **A.** A render report: one JSON format with a registry of finding codes, written by every engine,
  and requested per output with `output/@report`.
- **B.** Legibility checks for video: reading speed, minimum display time and minimum text size.
- **C.** Inert-attribute findings: attributes that are valid but have no effect.
- **D.** A normative definition of where lines of text sit in a text box: CSS half-leading over the
  font's `hhea` metrics, which the Rust and Python engines already draw to the pixel.
- **E.** A pinned-font policy: `project/@fontPolicy="pinned"` forbids faces the document does not pin
  by hash.
- **F.** An engine capability manifest: one format for what each engine implements.

Every addition has a neutral default. Existing documents validate and render as before.

## Motivation

The evidence below comes from the scenes on the maintainers' machines: 460 distinct scene documents, 65 of
them production scenes, plus the four engines' sources.

- **Nothing reports the outcome of a render.**
  - The reference implementation's diagnostics cover the document: XML, structure, the XSD and
    Schematron rules, and assets.
  - `accessibility` has `flashCheck` and `contrastCheck`, but the schema does not say where their
    verdicts go, and no two engines write the same thing.
  - A tool that wants to know whether a render is any good, such as a review sheet or CI, has
    nothing to read.
- **Captions outrun readers.** The production scenes carry 1,315 caption cues:
  - median speed 16.3 characters per second; 90th percentile 19.1;
  - 44 of the 278 Portuguese cues exceed 17 cps, the limit Netflix's Brazilian Portuguese guide sets
    for adult subtitles;
  - 49 of the 1,037 English cues exceed 20 cps, its English (USA) limit;
  - 31 cues are shown for less than the 5/6-second minimum of Netflix's general requirements.

  The format has `requireCaptions` but no way to ask for readable ones.
- **Attributes that validate and do nothing.**
  - 102 shapes set `strokeWidth` with no stroke paint, so no stroke is drawn.
  - 11 nodes start after the composition ends, so they are never drawn.
  - The frameforge-render engine found the same class of defect "in the wild" and reports it as
    `inert_style_key` and `inert-stroke-declaration`. Nothing in scene-render does.
- **One of those is worse: the engines disagree.**
  - 60 shapes put `radius` on `shape="rect"`, among them the stamps and captions of a published
    video.
  - D27 gives corner radius to `rounded-rect` only, and the C engine draws a `rect` exactly.
  - The reference implementation rounds a `rect` too (`"rect" | "rounded-rect"` share one branch).

  The same document has round corners on one engine and square on another, and nothing says so.
  Part C resolves the question as an open issue instead of guessing.
- **Text placement is unwritten.**
  - D1–D27 define strokes, outlines, masks and cameras, but not where a line of text sits in its
    box, and the compatibility kit has no case with text.
  - The engines currently agree. A text asset of 80 px `HHHH`, `lineHeight="1.2"` and
    `verticalAlign="middle"` in a 200 px box inks rows 149–207 on both the Rust and the Python
    engine.
  - That is exactly the prediction of CSS half-leading over the `hhea` ascender and descender of the
    face used (DejaVu Sans): baseline 207.70, cap top 149.38. OS/2 typographic metrics would put it
    7 px higher.
  - It is agreement by accident: an engine that switched to typographic metrics would move every line
    of text, and no test would fail.
- **Fonts come from the host.**
  - 2,243 text assets and text styles name a family with `font` and have no `font` asset of that
    family with a `sha256`.
  - The agreement above held because both engines asked fontconfig for `sans-serif` on the same
    machine.
  - Scene packages bundle font files (SREP 1), but the document cannot require that only those are
    used.
- **What each engine leaves out is written four ways.**
  - The C engine keeps a table of 2,105 constructs (elements, attributes, enumeration values): 1,718
    missing, 131 partial, 256 supported.
  - DEFINITIONS.md lists "Reported" items in prose, and the other engines keep no list.
  - Neither a user choosing an engine nor `scenerender-vpkg run` can ask whether an engine draws a
    given scene.

The FrameForge render engine faced each of these and answered with a typed diagnostics channel per
failure mode, legibility measured on the render, inert-key findings, a normative line seat, pinned font
closures in strict mode, and explicit `*_unsupported` findings. This SREP adapts those answers to video.

## Specification

### Syntax

```xml
<!-- outputType gains -->
<xs:attribute name="report" type="xs:anyURI">
  <xs:annotation><xs:documentation>
    Where to write this output's render report (scene-render-report/1, SREP render reports), relative
    to the document.
  </xs:documentation></xs:annotation>
</xs:attribute>

<!-- accessibilityType gains -->
<xs:attribute name="legibilityCheck" default="off">
  <xs:simpleType><xs:restriction base="xs:string">
    <xs:enumeration value="off"/><xs:enumeration value="warn"/><xs:enumeration value="error"/>
  </xs:restriction></xs:simpleType>
</xs:attribute>
<xs:attribute name="readingSpeed" type="positiveDecimal"/>
<xs:attribute name="minDisplayTime" type="nonNegativeDecimal" default="0.8333"/>
<xs:attribute name="minTextSize" type="lengthType"/>

<!-- captionTrackType gains -->
<xs:attribute name="readingSpeed" type="positiveDecimal">
  <xs:annotation><xs:documentation>
    Characters per second this track may reach; overrides accessibility/@readingSpeed.
  </xs:documentation></xs:annotation>
</xs:attribute>

<!-- projectType gains -->
<xs:attribute name="fontPolicy" default="system">
  <xs:simpleType><xs:restriction base="xs:string">
    <xs:enumeration value="system"/><xs:enumeration value="pinned"/>
  </xs:restriction></xs:simpleType>
</xs:attribute>
```

```xml
<sch:pattern id="p67">
  <sch:rule context="/scene[project/@fontPolicy='pinned']">
    <sch:assert id="C70" test="not(//@fontFile)">fontPolicy="pinned": faces come from font assets, not @fontFile.</sch:assert>
    <sch:assert id="C71" test="not(assets/font[not(@sha256)])">fontPolicy="pinned": every font asset carries @sha256.</sch:assert>
    <sch:assert id="C72" test="not(//@font[not(. = /scene/assets/font/@family)])">fontPolicy="pinned": every @font names the family of a font asset.</sch:assert>
    <sch:assert id="C73" test="not(//@fallback[str:tokenize(., ',')[not(normalize-space(.) = current()/assets/font/@family)]])">fontPolicy="pinned": every @fallback family names a font asset.</sch:assert>
  </sch:rule>
</sch:pattern>
```

In C73, `current()` is the `/scene` the rule matched. A bare `/scene` inside the predicate would resolve
against the tokens' own document and reject every fallback.

All additions are attributes with neutral defaults, so they are accepted in every version (SREP 0,
Versioning). No version gate is needed.

### A. The render report

**A1. When.**
1. An engine that renders an output with `report` MUST write the report file there, after rendering,
   whether or not the render succeeded.
2. It MAY also write reports when asked on its command line. How it is asked is not specified.
3. A render that stops on an error still writes the report, with the error among the findings.

**A2. Form.** The report is one UTF-8 JSON object:

```json
{
  "format": "scene-render-report/1",
  "engine": {"name": "rs-scene-render", "version": "0.9.0"},
  "scene": {"sha256": "8e47…9b642", "version": "1.1"},
  "output": {"id": "out-master", "width": 1920, "height": 1080, "start": 0, "end": 292.167},
  "findings": [
    {"code": "LEG-SPEED", "severity": "warning", "path": "/scene/captions/captionTrack[1]/cue[12]",
     "time": [131.2, 132.9], "measured": 21.4, "limit": 17, "unit": "cps",
     "message": "cue reads at 21.4 characters per second"}
  ]
}
```

| Field | Rule |
|---|---|
| `format` | exactly `scene-render-report/1`; MINOR additions add fields, never change them |
| `scene.sha256` | SHA-256 of the document's bytes as read |
| `output` | the output as rendered: its id, pixel size and time range |
| `code` | a code from table A3, or `X-<engine>-<code>` for an engine-specific finding |
| `severity` | `error`, `warning` or `info` |
| `path` | an XPath of the element concerned (`/scene/composition/layer[2]`), with 1-based positions among same-name siblings; `/scene` when nothing narrower applies |
| `node` | the element's `id`, when it has one |
| `time` | `[start, end]` in composition seconds of the output's timeline, when the finding concerns a time |
| `measured`, `limit`, `unit` | the quantity found, the threshold it was compared with, and its unit, when a check measured one |
| `message` | for people; its wording is not part of the contract |

**A3. Determinism.** The report MUST NOT contain timestamps, host names or paths outside the document's
folder. Findings are sorted by (`time[0]`, with no time first), then `code`, then `path`. The same
document, engine version and output produce the same bytes.

**A4. Codes.**

| Code | Severity | Finding | Part |
|---|---|---|---|
| `XSD` | error | the document fails the XSD | |
| `SCH-<id>` | error | a Schematron assert fails, e.g. `SCH-C3` | |
| `ASSET-MISSING` | error | an asset file is missing or fails its `sha256`/`cacheSha256` | |
| `TXT-FIT` | warning | text does not fit its box at the size drawn (after `autoFit`); `measured` is the overflow in pixels | D |
| `TXT-CUT` | warning | characters were dropped by `maxLines` or `overflow="clip"`/`"ellipsis"`; `measured` is how many | D |
| `LEG-SPEED`, `LEG-SHORT`, `LEG-SIZE` | per `legibilityCheck` | see B | B |
| `LEG-CONTRAST` | per `contrastCheck` | the existing contrast check | B |
| `ACC-FLASH` | per `flashCheck` | the existing photosensitivity check | |
| `ACC-CAPTIONS` | error | `requireCaptions="true"` and an output without captions | |
| `SAFE-AREA` | per `safeArea/@enforce` | the existing safe-area check | |
| `INERT-I1` … `INERT-I8` | info | see C | C |
| `FONT-SUB` | warning | the face drawn differs from the face the document asked for (family, weight, style) | E |
| `FONT-GLYPH` | warning, error when pinned | a character no permitted face has; `measured` is the code point | E |
| `SUP-REPORTED`, `SUP-APPROX` | warning | the document uses a construct the engine does not draw, or draws approximately (F) | F |

### B. Legibility

When `legibilityCheck` is `warn` or `error`, the engine checks every burned-in caption cue and every text
layer drawn in the output, and reports at that severity.

1. **Visible time.** Let V be the part of the output's time range in which the text is drawn with
   nonzero opacity. For a caption cue, that is the cue's [start, end); for a text layer, its window
   with its ancestors' windows and clocks applied.
2. **Characters.** Let N be the number of Unicode code points of its text after NFC, not counting line
   breaks.
3. **`LEG-SPEED`:** N / |V| > the limit, in characters per second. For a cue, the limit is its track's
   `readingSpeed`, else `accessibility/@readingSpeed`; for a text layer, `accessibility/@readingSpeed`.
   Without a limit there is no check.
4. **`LEG-SHORT`:** |V| < `minDisplayTime` (seconds).
5. **`LEG-SIZE`**, when `minTextSize` is set:
   - the drawn size is the text's `size` (after `autoFit`) times the layer's world scale √|det| of its
     2D world matrix, converted to output pixels;
   - it is reported when that size is below `minTextSize`, resolved against the output frame (`vh`,
     `vmin`, …, or pixels);
   - one finding per layer, with the time range in which the size was below.
6. Text revealed progressively by a `textAnimator` is measured over its whole visible time.
7. Burned-in captions are measured as laid out. Sidecar captions are measured from their cues.

### C. Inert attributes

An **inert** attribute is valid and has no effect on the picture. Validators and engines report each with
`INERT-<rule>` at `info` severity. They are never errors, because the document means what it says, only
less than its author thought.

| Rule | Condition |
|---|---|
| I1 | `stroke` is not transparent and `strokeWidth` is 0 or absent |
| I2 | `strokeWidth` > 0 and `stroke` is transparent or absent |
| I3 | `dash`, `dashOffset`, `strokeCap`, `strokeJoin` or `miterLimit` on an element that draws no stroke (I1, I2) |
| I4 | `points`, `innerRadius`, `outerRadius`, `innerRoundness` or `outerRoundness` on a `shape` other than `polygon` or `star` |
| I5 | `path` on a `shape` other than `path` |
| I6 | `matteMode` or `matteVisible` without `matte` (not on `transition`) |
| I7 | `volume`, `mute` or `audioBus` on a layer whose asset has no sound (image, text, vector, code, formula, chart, generator, audiogram) |
| I8 | a node whose window lies wholly outside [0, project `duration`), so it is never drawn |

The set is closed. A later SREP adds a rule only with a condition that is inert under the conventions,
the definitions and every accepted SREP.

### D. Where text sits (Semantics)

For a text asset of box w × h, `size` s and `lineHeight` k, drawn as n lines after wrapping:
- let A = hhea.ascender / unitsPerEm and D = −hhea.descender / unitsPerEm of the primary face, the face
  its own style selects;
- when `hhea` is absent, or its ascender and descender are both 0, OS/2 `usWinAscent` and `usWinDescent`
  are used.

1. **Line pitch** L = k · s. **Block height** B = n · L.
2. **Block top**, in the box (+y down):
   - `verticalAlign="top"`: t = 0;
   - `middle`: t = (h − B) / 2;
   - `bottom`: t = h − B.

   The block may extend outside the box; that is `TXT-FIT`.
3. **Baseline of line i**, counted from 0: yᵢ = t + i · L + (L − (A + D) · s) / 2 + A · s. This is CSS 2.1
   §10.8.1 half-leading, with the content area given by the font's ascent and descent.
4. **Horizontal placement.** Line i, of advance width aᵢ (shaped advances, `letterSpacing` and `tracking`
   included), starts at:
   - x = 0 for `start` and x = w − aᵢ for `end`, in the inline direction; with `direction="rtl"`,
     start and end swap;
   - x = (w − aᵢ) / 2 for `center`;
   - `justify` widens the word gaps of every line but the last until aᵢ = w, and never the letter
     spacing.
5. `autoFit` chooses s before steps 1–4. `maxLines` and `overflow` then drop lines (`TXT-CUT`).
6. These rules state the behaviour of the reference implementation. The measurement in Motivation is
   exactly this computation.

### E. Pinned fonts

1. With `fontPolicy="system"` (the default), faces resolve as they do today. The engine reports
   `FONT-SUB` whenever the face drawn differs from the family, weight or style requested.
2. With `fontPolicy="pinned"`:
   - C70–C73 require every face to come from a `font` asset carrying `sha256`;
   - the engine MUST draw only from those assets, and MUST NOT consult the host's fonts, fontconfig
     included;
   - `font` and `fallback` name families of `font` assets; `fallback` is tried in order;
   - a character none of them has is drawn as the primary face's `.notdef` glyph and reported
     `FONT-GLYPH` at error severity.

### F. Capability manifests

An engine publishes a manifest at a stable place in its release, for example `capabilities.json` at the
root of its repository and in its distribution:

```json
{
  "format": "scene-render-capabilities/1",
  "engine": {"name": "c-scene-render", "version": "1.4.0"},
  "schema": "1.1.3",
  "entries": [
    {"construct": "particleEmitter", "status": "unsupported"},
    {"construct": "layer/@frameBlend=optical-flow", "status": "reported", "definition": "D20"},
    {"construct": "effect/@type=glow", "status": "approximate", "note": "bloom radius capped at 64 px"}
  ]
}
```

1. **`construct`** is one of:
   - an element name;
   - `element/@attribute`;
   - `element/@attribute=value`, for an enumeration value.
2. **`status`:**
   - `exact`: passes the kit's cases for it;
   - `approximate`: drawn, measurably different;
   - `reported`: recognised, not drawn, reported as `SUP-REPORTED`;
   - `unsupported`: not recognised.
3. A construct the manifest does not list is claimed `exact`. The manifest lists every other one.
4. When rendering, an engine reports each `approximate` or `reported` construct the document uses, once,
   as `SUP-APPROX` or `SUP-REPORTED` with the construct in `message`.

### Defaults and the neutral case

- `report` absent: no file is written.
- `legibilityCheck="off"`: nothing is measured.
- `fontPolicy="system"`: faces resolve as before.

Findings never change pixels. Part D states existing behaviour. Part C and the capability manifests
add no syntax to documents. A document that uses none of the new attributes renders byte for byte as
before.

## Rationale

- **Report the outcome in one format.**
  - A review sheet, CI or a packaging tool should not parse four engines' logs.
  - The codes are few and stable, and engine-specific findings have a namespace (`X-<engine>-`), so
    engines can report more without breaking readers.
  - The existing checks (`flashCheck`, `contrastCheck`, `safeArea/@enforce`) gain a place to report.
- **Reading speed and display time come from subtitle practice.**
  - Netflix's general requirements set a minimum event duration of 5/6 of a second, the default here.
  - Its reading-speed limits depend on language and audience: 17 cps for adult Brazilian Portuguese
    subtitles (13 for children, 20 for SDH), 20 for adult English (USA) subtitles (17 for children).
  - `readingSpeed` therefore has no default and can be set per caption track.
  - `minTextSize` has no default: the production scenes set text at a median of 2.78% of the frame's
    short side and a tenth of it below 1.67%. That is a choice of the brief (phone, television), not
    a fact the format can assume.
- **Inert findings, never errors.** The FrameForge engine separates keys no consumer reads from keys that
  are wrong. A scene-render XSD already rejects unknown attributes, so the remaining class is valid
  attributes without effect, whose value is in telling the author.
  - The table lists only conditions that are inert by the definitions.
  - `radius` on `rect` is left out, because it is inert by D27 and drawn by the reference
    implementation. That contradiction needs a ruling, not a warning (Open issues).
- **Half-leading on `hhea`.**
  - It is what the engines already do, measured.
  - It is CSS's model, so the same text in a browser preview sits in the same place.
  - It needs no special case for a single line, which FrameForge had to add because its multi-line
    model top-anchored on a baseline grid.
- **Pinned fonts** make text layout a function of the document. The FrameForge closure is the precedent:
  measuring with the host's fonts is exact but not reproducible, and it fails silently. Font assets
  already carry `sha256`, so the format needed only the policy and the rules.
- **Capability manifests.** The C engine's table shows the list exists and is large. Publishing it in one
  format lets tools choose an engine for a scene and tell the author what will be missing, before a
  render rather than after.

## Rejected alternatives

- **Reports inside the video container** (metadata tracks, sidecar XML). JSON beside the output is read
  by every tool and needs no demuxer.
- **Legibility as errors by default.** 93 production cues (7%) would fail at their language's limit, and a
  new default must not break renders.
- **A fixed `minTextSize` or `readingSpeed`.** Both depend on the brief: the delivery target, the language
  and the audience.
- **Typographic (OS/2 `sTypo*`) metrics for D.** They are the better-designed metrics, but choosing them
  would move every line of existing text by several pixels; D codifies what renders today.
- **Inert findings as Schematron warnings.** Schematron can express most of them, but the canonical rules
  are asserts that fail validation. Inert findings are information, and they belong to the report.
- **A capability flag per element in the XSD** (`xs:appinfo`). Capabilities belong to engines and change
  with their releases; the schema changes only through SREPs.

## Backwards compatibility

- **Class: Added, MINOR (1.2).**
  - New attributes with neutral defaults, accepted in every version.
  - One Semantics clarification (D) that states existing behaviour.
- The inert table C and the capability format F add nothing to documents.
- No valid document becomes invalid, and none renders differently.
- **Evidence.** The XSD and Schematron above were applied to a copy of the canonical schema, and the 2,600
  local scene documents that declare 1.0 or 1.1 were validated with both copies. No verdict changed.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | Write the report from its existing diagnostics plus text fit, legibility, font substitution and support findings. Honour `fontPolicy` in font resolution. Publish `capabilities.json`. Part D: none (verify with the new cases). Settle `rect` radius (Open issues). | |
| C (`c-scene-render`) | pending | Report writer. Convert `docs/gaps-1.1.csv` (2,105 entries) into `capabilities.json`. Text seating per D, verified by the cases. | |
| Python (`py-render`) | pending | Report writer; capabilities. Part D: none (measured equal to Rust). | |
| JavaScript (`js-render-engine`) | pending | Report writer; capabilities; text seating per D. | |

sr-core carries the reference implementation of the formats, as SREP 1 does for packages:
- the JSON Schemas `report-1.schema.json` and `capabilities-1.schema.json`;
- `sr-lint`, which writes a report with the static findings (`XSD`, `SCH-*`, `INERT-*`, and C70–C73 under
  `pinned`);
- `sr-review`, which shows a report's findings on the section pages they fall in;
- `scenerender-vpkg run --engine auto`, which picks the engine whose manifest covers the scene best.

## Conformance

| Case | Checks | Expected |
|---|---|---|
| `srep-NNNN-text-top`, `-middle`, `-bottom` | a pinned test font generated by `make_cases.py`: unitsPerEm 1000, hhea ascender 800 and descender −200, every glyph a rectangle from x 50 to 550 and from the baseline up to 700 units, advance 600. Text `HH`, size 100 px, `lineHeight="1.5"`, one line in a 400 × 300 box placed at (100, 30) | ink rows: `top` 65–135; `middle` 140–210; `bottom` 215–285 |
| `srep-NNNN-text-lines` | three lines, `verticalAlign="top"`, box 400 × 450 | baselines at y = 135, 285 and 435 |
| `srep-NNNN-text-align` | the one-line case with `align` `start`, `center`, `end` | ink columns 105–215, 245–355, 385–495 |
| `srep-NNNN-report` | a scene with one inert attribute (I2), one 30-cps caption cue on a track with `readingSpeed="20"`, `legibilityCheck="warn"`, and `output/@report` | the report validates against `report-1.schema.json` and lists exactly `INERT-I2` and `LEG-SPEED` with `measured` 30 ± 0.1 |
| `srep-NNNN-pinned-font` | `fontPolicy="pinned"` and a character outside the test font | `FONT-GLYPH` at error severity; no host face drawn (the ink matches `.notdef`) |
| `tests/test_schema_rules.py` | C70–C73 each reject a document built to break them; every existing case and document keeps its verdict | exact |
| `tests/test_lint.py` (sr-core) | I1–I8 each found in a document built to have it, and nowhere else in the kit | exact |

The values follow from D with the test font:
- A = 0.8 and D = 0.2, so at s = 100 the content area is 100 px, the pitch L is 150 and the half-leading 25.
- With `top`, the baseline is at 30 + 0 + 25 + 80 = 135, and the ink rises 70 px above it.
- A line of two glyphs advances 120 px, and each glyph inks 5–55 px of its 60.

`make_cases.py` computes every expected value from D.

## Open issues

- **`radius` on `rect`.** D27 (adopted by SREP 7) makes it inert; the reference implementation rounds.
  60 local shapes, one published video among them, rely on the rounding. Either:
  - amend D27 so that `rect` honours `radius` (the scenes keep their look, and C changes); or
  - keep D27 (Rust changes, and those scenes lose their round corners).

  A Semantics decision is needed before C and Rust can agree.
- **Mixed-size spans.** D takes the line pitch from the asset's `size`. Whether a larger span grows its
  line, as CSS does, is not yet measured on the engines.
- **Counting characters.** Code points after NFC over-count scripts with combining marks relative to
  grapheme clusters (Unicode UAX #29). Whether Netflix's counts include spaces is not stated in the
  guides consulted; this SREP counts them.
- **Report for multi-output renders.** One file per output, as specified, or one per render with an
  output array.
- **Scope.** The editor may split A–F into separate SREPs; each part stands alone except that B, C, E and
  F report through A.

## References

- [SREP 0](srep-0000.md), [SREP 1](srep-0001.md), [SREP 4](srep-0004.md), [SREP 7](srep-0007.md).
- [CONVENTIONS.md](../conformance/CONVENTIONS.md); [DEFINITIONS.md](../conformance/DEFINITIONS.md) D20, D26, D27
  and the "Reported" lists.
- CSS 2.1, §10.8.1 Leading and half-leading. <https://www.w3.org/TR/CSS21/visudet.html#leading>
- OpenType specification, `hhea` and `OS/2` tables. <https://learn.microsoft.com/typography/opentype/spec/>
- WCAG 2.1, Success Criteria 1.4.3 (Contrast) and 2.3.1 (Three Flashes).
- Netflix Timed Text Style Guide: General Requirements (minimum duration 5/6 s).
  <https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements>
- Netflix Portuguese (Brazil) Timed Text Style Guide (reading speed).
  <https://partnerhelp.netflixstudios.com/hc/en-us/articles/215600497-Portuguese-Brazil-Timed-Text-Style-Guide>
- Netflix English (USA) Timed Text Style Guide (reading speed).
  <https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide>
- Unicode Standard Annex #15 (normalization) and #29 (text segmentation).
- frameforge-render: diagnostics channels (`overflow`, `legibility`, `paint_intent`), `inert_style_key`,
  font closures in strict mode, `*_unsupported` findings. <https://github.com/pedroanisio/frameforge-render>

## History

- 2026-09-30: first draft.
