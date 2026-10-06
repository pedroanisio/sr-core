# Changelog — scene-render schema

The version is `xs:schema/@version` in `scene-render.xsd`; each release is tagged `schema-X.Y.Z`. Documents
declare only MAJOR.MINOR (`<scene version="1.1">`), so a PATCH release never changes what a document says.

Record every change under **Unreleased** when it lands, in the class that fits, with its SREP (SREPs are in
the `srep/` folder of the sr-core repository). The next version is
computed from those classes by `python3 tools/release.py next schema`:

| Class | Bump | For |
|---|---|---|
| Breaking, Removed | MAJOR | a valid document becomes invalid or renders differently |
| Added, Deprecated | MINOR | new elements, attributes, enumeration values or asset kinds; also add the new MAJOR.MINOR to `scene/@version` |
| Changed, Fixed, Security, Docs | PATCH | documentation, Schematron messages, wording; and corrections that reject only documents whose meaning was undefined (SREP 4) |

## Unreleased

### Breaking

### Added

### Fixed

## 1.4.0 — 2026-10-06

### Added

- Generated marker ids (SREP 57): the five attributes that name a marker (`key/@marker`, the timing `startMarker` and `endMarker`, the audio track's `startMarker`, and `marker` of `poster` and `thumbnail`) are `xs:NCName` instead of `xs:IDREF`; rule R21 accepts a `beat.N` or `bar.N` id (N of one to nineteen digits) when the scene has a `beatGrid`, and does the existence check of explicit markers that the IDREF type did. The validator's warnings W03 (an explicit marker named like a generated id) and W04 (a `poster` or `thumbnail` marker that names no marker) are defined in the SREP, not in the schema. A document that was valid stays valid; a dangling `poster` or `thumbnail` marker, which the IDREF type rejected, is now valid with W04. `scene/@version` accepts `1.4` (no version gate: generated marker ids are accepted in every version).

## 1.3.0 — 2026-10-06

### Added

- Version 1.3: volumetric and large-scale cinematic effects (SREP 40): the `volume` and `meshSequence` asset kinds, the `volume` object3D primitive with `medium`, `pyro`, `crater` and `fracture` children, the `particles3D` and `ocean` nodes (with `burst`, `pyroSource`, `pyroImpulse`, `waterImpulse`, `whitewater` and `oceanWave`), the globe-relief attributes `planetRadius` and `terrainTileSize`, `terrainZoom`, `terrainMissing`, `terrainMemoryMiB`, `physics/@fixInternalEdges`, the version gate V8, the amendment of R5, and the rule families VOL, PYRO, PYC, P3D, OCN, CRT, FRX, MSQ and GEO (SREP 40).

## 1.2.0 — 2026-10-06

### Added

- `<tiles>` asset kind (PMTiles archive or pinned online tile service), `<basemap>` child of `<map>`, `tileZoomType`, rules R27 and C46; asset codes A01, A02, A03 are documented in the SREP only; documents opt in with `version="1.2"` (SREP 9).
- `object3D` primitives `map` (a map asset draped as ground, optionally raised by elevation tiles and with extruded buildings) and `globe`; attributes `map`, `terrain`, `terrainEncoding`, `exaggeration`, `buildings`, `textureSize`; rules C47, R28, R29. The primitives need `version="1.2"`; the attributes are accepted in every version (SREP 10).
- `object3D/rigidBody` (type `rigidBody3DType`) for 3D rigid-body simulation; constraint type `ball` and attributes `z`, `axisX`, `axisY`, `axisZ`; force-field attributes `z` and `forceZ`; physics attribute `gravityZ`; rule C48. The 3D `rigidBody` element needs `version="1.2"`; the new attributes are accepted in every version and do nothing without 3D bodies (SREP 11).
- `output` children `segment`, `audioTrack` and `captionTrack`; `output` attributes `audioTracks`, `audioRoles`, `audioBuses`, `overlay`, `joinFade`; `segmentType`; `audioRoleType` and `audioRoleListType` (the `audioTrack/@role` enumeration factored out, no value changes); rules C54 to C59 and R38 to R41; rules C20, C33 and R14 amended so segment transitions, output caption tracks and output-owned caption tracks validate. The new elements need `version="1.2"` (SREP 13).
- `markerStart`, `markerEnd` and `markerSize` on `shape` (closed set of arrowheads, dots, squares, diamonds and bars sized in stroke widths, riding on trim paths); rule C65 requires an open outline (`shape="path"` or `"line"`) (SREP 15).
- `connector` node (`connectorType`, `connectorAnchorType`, `pointListType`) that joins two nodes or fixed points and is recomputed every frame; `nodeAttributes` is split into `nodeCoreAttributes` plus the placement attributes (no change to what any element accepts); rules C60 to C64, R48-from, R48-to, R49, R50 and the version gate V11 (SREP 16).
- `pdf` asset kind (one PDF page as a resolved, hash-pinned cache image, with text-anchored `region` children) and `shape/@region`, `@regionLayer`, `@regionPadding`; `shape/@width` and `@height` move from the XSD (`use="required"`) to rule C69 with the same effect on every document; rules V9, C66, C67, C68, C69, R51, R52 (SREP 17).
- `output/@report` (where an output's render report, scene-render-report/1, is written). No validation rule changes; the report format and the INERT-I1 to I8 findings are defined in the SREP and not part of the schema (SREP 18).
- `accessibility` gains `legibilityCheck` (off, warn, error), `readingSpeed`, `minDisplayTime` (default 0.8333) and `minTextSize`; `captionTrack` gains `readingSpeed`. Findings LEG-SPEED, LEG-SHORT and LEG-SIZE are reported through the render report of SREP 18 (SREP 19).
- `project/@fontPolicy` (`system` default, `pinned`); with `pinned`, Schematron rules C70 to C73 require every face to come from a `font` asset carrying `sha256`. Findings FONT-SUB and FONT-GLYPH are reported through the render report of SREP 18 (SREP 21).
- `useForceFields` (boolean, default true) on `particleEmitter`, `flock` and `fluid`; false means no force field acts on the simulation. `forceFields` gains its annotation (absent: every force field of the scene). Rule R34 is unchanged (SREP 24).
- `repeat` gains an optional `points` child (types grid, along-path, scatter, vertices, list) that places copy i on generated point i; expression names `pointX`, `pointY`, `pointAngle`, `pointU`, `pointRandom`; rules C17 (amended), V10, C74 to C80. New types `pointsType` and `pointListType` (SREP 26).
- `generator/@lineWidth` (grid only, `nonNegativeDecimal`, no default): the grid line width in asset pixels, independent of `@scale`; Schematron rule R47 (pattern p65) rejects `@lineWidth` on a generator whose `@kind` is not `grid` (SREP 30).
- `key/@overshoot` (`nonNegativeDecimal`, the constant of `back-in`, `back-out`, `back-in-out`; default 1.70158) and `key/@period` (`positiveDecimal`, the ringing period of `elastic-in`, `elastic-out`, `elastic-in-out` as a fraction of the segment; default 0.3, 0.45 for `elastic-in-out`), both read from the key the segment leaves (SREP 31).
- `layer/@resample` (`linear` default, `bicubic`, `mitchell`): the filter used where a layer is drawn larger than its source (Catmull-Rom or Mitchell-Netravali B = C = 1/3, clamped to the range of the four nearest texels); minified layers keep trilinear filtering whatever it says (SREP 32).
- `safeAreaForce` (`xs:boolean`, default `false`) on every node (`nodeAttributes`) and on `symbol`: exempts the node, what it contains and (for a symbol) every instance of it from the safe-area enforce check; the SREP defines the checks `SA01` (finding) and `SA02` (information line listing every force). No Schematron rules (SREP 33).
- amends SREP 18's report with the inert-attribute rules I9 to I13 (`group/@collapse`, selective-color `@channel`, an effect `@source` at opacity 0, a key `overshoot` or `period` on a curve that does not read it, an effect attribute its type does not read) and the warning `MASK-MISS`; the documentation of `group/@collapse` now says the attribute has no effect. No validity change (SREP 34).
- `textAnimator/@presetEase`, an optional curve for a preset (`linear`, `quad-in`, `quad-out`, `cubic-out`, `expo-out`, `back-out`, `bounce-out`); `@presetStart` is documented as a time on the parent timeline (SREP 35).
- `object3D/@tracking` for `primitive="text"` (extra space after every glyph, thousandths of the text size), and rule TXT2 requiring `primitive="text"` (SREP 37).
- `object3D/@node` (draw one node of an imported model, its origin at the object's origin) and `object3D/@materialOverride` (a list of imported-material-name:document-material-id pairs); rules MOV1 (pair syntax) and MOV2 (each id names a document material) (SREP 38).
- `material/@unevenness`, `@unevennessScale` and `@unevennessSeed`, a procedural surface unevenness for a hand-made (clay) look (SREP 39).
- `object3D/@shadowCatcher`, a surface that draws only the share of light the shadow casters take away (SREP 41).
- `object3D/@animationClipTo`, `@animationBlend` and `@animationOffsetTo`, to blend two clips of an imported model (SREP 42).
- `parentJoint` on `object3D` (and `particles3D`, see below) and `targetJoint` on `transformConstraint` name a node of an imported model as the frame a 3D element is attached to; no Schematron rule, no default, accepted in every version (SREP 43).
- an engine reports key parameters that the key's curve does not read (code E19, information) and a default `cubic-bezier` curve whose key has no handles (code E21, warning). No schema or Schematron change; C40 keeps its context `key[@interpolation='cubic-bezier']` (SREP 44).
- `link` gains the follower attributes `follow` (none, exponential, spring; default none), `timeConstant` (0.1), `stiffness` (100), `damping` (10) and `mass` (1); no Schematron rule (SREP 45).
- element `morph` (type `morphType`: required `name`, `weight` default 0, animation children) in `object3D` sets the weight of a morph target of an imported model by name; version-gated by V5 (needs version 1.2) (SREP 46).
- element `joint` (type `jointType`: required `name`; `rotationX`, `rotationY`, `rotation`; `lookAt` IDREF; `lookAxis` x, minus-x, y, minus-y, z, minus-z (default z); `influence` 0..1 (default 1); `maxAngle` (default 180); animation children) in `object3D` poses or aims a joint of an imported model; version-gated by V5 (needs version 1.2). Requires SREPs 42 and 43 (SREP 47).
- the expression built-ins `penner("curve", u)` and `propAtTime("id.property", t)`; the `expressionType` documentation lists them. No attribute, element or Schematron change (SREP 48).
- `motionPath` gains `additive` (boolean, default false): the path is an offset added to the node's own position (P(p) - P(0)); no Schematron rule (SREP 49).
- `key/@carry` (xs:boolean, default false): a spring key starts with the velocity the segment before it arrives with, so chained springs keep their momentum (SREP 50).
- `captionTrack/@lineBreaks` (`greedy` default, `source`): `source` ends a caption line at each newline written in a cue; the limits still apply (SREP 52).
- `transformConstraint/@pole` (IDREF) and `@softness` (unitDecimal, default 0) for two-bone IK: a pole that sets the bend side, and a soft reach that eases the chain toward full extension (SREP 54).
- `shutterAngle` on every node (`nodeAttributes`, xs:double, 0 to 720, no default): the node's own shutter angle for motion blur, inherited from the nearest ancestor that sets it, else the project's (SREP 55).
- asset kind `strokeFont` (single-line font, `format="jhf"`); `shape/@shape` value `stroke-text` with `@text`, `@strokeFont` and `@fontSize` (default 48); rules PEN1 (stroke-text needs @text and @strokeFont) and PEN2 (@strokeFont must name a strokeFont asset) (SREP 56).

### Changed

- the position of lines of text in a text box is now normative (CSS 2.1 half-leading over the `hhea` ascender and descender of the primary face, line pitch `lineHeight` x `size`, block placed by `verticalAlign`, lines by `align`). No schema change and no change to what the reference implementation draws. (Class chosen by me: clarification of semantics; the SREP gives no class line.) (SREP 20).
- a `rect` shape with `radius` or `cornerRadii` greater than 0 is drawn with the `rounded-rect` outline of D27; a rect with all radii 0 is drawn exactly. D26 and D27 are amended. No schema change. (Class chosen by me: ruling on a silent construct.) (SREP 23).
- the annotations of `colorType`, `expressionType`, `radialGradientType/@aspect`, `textAnimatorType/@presetStart`, `camera/@fov` and the `transformAttributes` attribute group now say what the baseline engine does. No declaration, default or rule changes (SREP 27).
- the documentation of `geoLayer` says that `@progress` also draws polygon outlines on (each ring from its first vertex, the fill stays whole) (SREP 36).
- `shapeModifier/@mode` documents `wiggle-path` with `corner|smooth`; `smooth` joins the wiggled points with a Catmull-Rom spline (SREP 51). Class per the SREP: an added value of an existing attribute, MINOR; the coordinator may prefer "Added" for the changelog since an accepted value is added. The XSD declaration is unchanged.
- the `expression` built-in list documents `wiggle(freq, amp[, octaves, ampMult, t, hold])`; a hold greater than 0 quantises the time the noise is read at (SREP 53). Class per the SREP: Added argument, MINOR.

### Fixed

- Schematron rules R42, R43 and R44 check the kind of asset a reference names: a `pattern` paint's `@asset` and an `@emitterAsset` must name an `image` asset, and the `@source` of a `displacement-map`, `difference-key` or `shader` effect must name a node of `composition` or `symbols` (SREP 28).
- the `effectType` documentation defines `selective-color` and `halftone` (halftone `@angle` default 0, ink `@color` default black, ground `@paint` default white; selective-color window, `@amount`, `@channel` not read). Semantics: `gradient-map` keeps the alpha of its stops, `matte-choke` grown by a negative amount takes the colour of the edge it grows from, `halftone` never paints outside the edge of its source. Visible change: a `halftone` with no `@angle` renders at 0 degrees, not 45 (SREP 29).

## 1.1.4 — 2026-09-30

### Docs

- The header no longer lists the engines by name; which engines are active is a process decision (SREP 25).

## 1.1.3 — 2026-09-29

### Fixed

- The version gate rejects every 1.1 element and `object3D` primitive under `version="1.0"`. Nineteen elements and seven primitives had been missing (SREP 8).
- Paint (`url(#…)`) and token (`var(--…)`) references are checked on every colour and paint attribute (SREP 8).
- New checks: `shape="sprite"` needs a sprite; `sprite`, `heightmap`, `forceFields` and `textStyle` must name the right kind of element; clay needs blobs; a `fluidSource` must end after it starts; a map domain must increase. R10 (self-parenting) applies to every node (SREP 8).
- Latitudes and longitudes are bounded, `route/@points` must be `lon,lat` pairs, and `palette` must be colours (SREP 8).
- The geo reference checks are renumbered R36 and R37. They had shared R24 and R25 with the paint and token checks (SREP 8).

## 1.1.2 — 2026-09-29

### Docs

- Comments and documentation describe the resolve step, 2D simulations, screen-space lighting and contact shadows without naming an engine or its commands; no declaration changes (SREP 5).

## 1.1.1 — 2026-09-29

### Docs

- The header names every engine as the schema's users and sr-core as its canonical home (SREP 2).
- The canonical files are `scene-render.xsd` and `scene-render.sch`; the header names its companion by that
  name, and the release version moves into `xs:schema/@version` (SREP 3, SREP 4).

## 1.1.0 — 2026-09-29

Baseline: `schema/scene-render-1.1.xsd` and `.sch` of rs-scene-render at commit `5e8ff6e`, imported unchanged
(SREP 0).
