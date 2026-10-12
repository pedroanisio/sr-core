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

### Docs

- Documentation for 1831 of the 1900 attributes that had none (SREP draft `srep-0000-schema-attribute-docs.md`): unit, range, default and dependency, each read in the reference implementation, the schema or an accepted SREP. Annotation-only: no declaration, default, type, facet or rule changes, and the same documents are accepted and rejected. The 69 attributes whose meaning no source establishes are listed in `tests/undocumented-attributes.txt`. `tools/release.py next schema` gives 1.7.1 for this alone.

## 1.7.0 — 2026-10-12

### Added

- Document version 1.7: `scene/@version` accepts `1.7`. SREP 87 has no version gate, so documents of every version get its scoping; `1.7` marks documents written for it (SREP 87, by the exception SREP 90 records).
- Ids emitted by a program are scoped by the program's id (SREP 87, amends SREP 66): an id `E` that the program `P` emits is `P.E` in the document (an NCName); inside the output, the tokens of `xs:IDREF` and `xs:IDREFS` attributes, the ids of `prop` and `propAtTime` and the node id of `link/@source` resolve to the program's own ids first; a bare reference from outside (at those positions, or `override/@target` of a layout, a variant, an instance or an include) resolves when exactly one program emitted the id, with the warning W13, and fails with the new error PRG17 when several did; the bone names of the skin weights of an emitted skeleton are its local ids; PRG14 covers a repeated id within one output and a namespaced id equal to another id; values derived from an emitted element's id use its local id. No declaration, default or rule changes, and there is no version gate. Documents that 1.6.0 refuses with PRG14 because two programs, or a program and the document, use the same id become valid. Two kinds of documents that 1.6.0 accepts are refused with PRG14: one that writes an id equal to a namespaced id (`<shape id="p.g1">` beside a program `p` that emits `g1`), and two programs whose namespaced ids compose to one value (`a` emitting `b.c` beside `a.b` emitting `c`). Known documents affected: none outside the kit cases written for the rule. A third kind recorded at acceptance, a `link` whose `link/@source` names an emitted node, keeps its element: SREP 87's erratum of 2026-10-11 makes `link/@source`, the overrides of an instance or an include and the bone names of skin weights positions of its rules 3 and 4, as the reference implements them (SREP 87, Open issues, item 6). The kit case `srep-0066-program-id-collision` is amended to write `p.g1`. Class: Added (SREP 4), by the exception to SREP 0 (Versioning) that SREP 90 (Process) records for exactly the two refused kinds, as SREP 86 records its exception; the schema editor chose it on 2026-10-11 over a version gate on document version 1.7 and over Breaking (2.0.0) (SREP 87, Open issues, item 7). `tools/release.py next schema` gives 1.7.0, and the release adds `1.7` to `scene/@version`.

## 1.6.0 — 2026-10-11

### Added

- Document version 1.6: `scene/@version` accepts `1.6`. The additions below follow three version policies:
- the version gates V12 to V16 (SREPs 66, 67, 70, 74 and 75) refuse their elements, asset kind and enumeration values in versions 1.0 to 1.5;
- BH1 (SREP 76) and VOX1 (SREP 80) refuse black holes, accretion disks, geodesic cameras, voxel assets and objects of cells only in versions 1.0 to 1.2, and `pyroBlast` (SREP 78) has no gate but V8, which refuses 1.0 to 1.2 (SREP 83). These new elements and asset kinds are therefore valid in documents of version 1.3 to 1.5, where SREP 0 (Versioning) requires the new version. SREP 76 chose 1.3 so that documents of 1.3 that have a black hole, the engine's corpus among them, stay valid (its Open issues, item 2); SREP 86 (Process) records this as an exception to SREP 0 for exactly these constructs;
- the other additions are attributes and rules, accepted in every version that admits their parent element (SREPs 68, 71, 72, 73, 77 and 79, and the attributes of SREP 67 on `effect`).
- Element `program` (`programNodeType` in `nodeChoice`, `programDataType` in `parameters`) with the attribute group `programAttributes` (`src`, `sha256`, `seed`, `fuel`, `memoryLimit`, `outputSha256`): a deterministic WebAssembly module run once when the document is built, whose output is nodes drawn as a group or JSON rows for `repeat/@over`; rule C18 amended to accept a data program; version gate V12 and rules PRG1 and PRG2, pattern p-srep66 (SREP 66).
- Elements `compute` (`computeType`, with `tonemap` of `densityTonemapType`) and `iterate` (`iterateType`) in `nodeChoice`; effect types `error-diffusion` and `segmented-sort` with the `effectType` attributes `kernel`, `palette`, `serpentine`, `direction`, `order`, `sortKey`, `low` and `high`; version gate V13 and rules ITR1, ITR2, CMP13 and SRT1, pattern p-srep67 (SREP 67).
- `effectType/@stepsPerFrame` (default 1) and `@prewarm` (default 0) for shader effects with persistent passes; rule STP1, pattern p-srep68; no version gate (SREP 68).
- `program/@mode` (`build` default, `step`), `@width`, `@height`, `@stepsPerFrame` and `@prewarm`: a program that keeps state and draws a picture each frame; rule PRG3, pattern p-srep69; STP1 covers programs in build mode (SREP 69).
- `shape="parametric"` with the child `parametricPath` (`parametricPathType`), and `object3D` primitives `parametric` and `heightfield` with the children `parametricSurface` (`parametricSurfaceType`) and `heightfield` (`heightfieldType`), sized by `surfaceSamplesType`; rule C69 amended to exempt `shape="parametric"`; version gate V14 and rules PAR1 and PAR2, pattern p-srep70 (SREP 70).
- `materialType` gains `subsurface`, `subsurfaceColor`, `subsurfaceRadius` and `subsurfaceRadiusScale` (`unitTripleType`); `lightType` gains the procedural sky of a dome, `sky` (`none` default, `gradient`), `skyZenith`, `skyHorizon`, `skyGround`, `skyExponent`, `sunAzimuth`, `sunElevation`, `sunSize`, `sunColor` and `sunIntensity`; a material map that begins with `#` names a generator or image asset of the document; rules SKY1, SKY2 (pattern p-srep71) and MTX1-*map* (one pattern per map attribute); no version gate (SREP 71).
- `project/@precision` (`f16` default, `f32`), `@supersample` (1 to 4, default 1) and `@supersampleFilter` (`box` default, `lanczos3`); `edgeBlend` (`inherit` default, `linear`, `encoded`) on every node (`nodeCoreAttributes`); the `shader` effect documents its tile and the inputs `sr_ContentRect` and `sr_PixelCoord`; no Schematron rule, no version gate (SREP 72).
- `flock/@orientToVelocity` (xs:boolean, default true); with false an agent's disc or sprite keeps rotation 0 (SREP 73).
- Element `viewport3D` (`viewport3DType`) in `nodeChoice`: a 3D scene with its own camera and lights, drawn as a node; version gate V15 and rules VP1 and VP3, pattern p-srep74 (SREP 74).
- Asset kind `fractal` (`fractalAssetType`): an escape-time Mandelbrot or Julia image whose centre is an exact `xs:decimal`; version gate V16 and rule FRC1, pattern p-srep75 (SREP 75).
- Elements `blackHole` (`blackHoleType`) and `accretionDisk` (`accretionDiskType`) in `nodeChoice`, and `camera/@geodesics`: a Schwarzschild black hole drawn by tracing null geodesics; rules BH1 to BH8 (patterns cinematic-black-hole-version and cinematic-black-hole), BH1 admitting version 1.3 and later, BH5 to BH8 scoped to the camera's `viewport3D` (SREP 74) and reading every xs:boolean form of `geodesics`; the warnings W11 and W12 are defined in the SREP (SREP 76).
- `crater/@mantle`, `@bulking` and `@repose`; `fracture/@source`, `@minImpulse` and `@energyFraction`; `ocean/@density`; rules CRT10 to CRT12 (reading every xs:boolean form of `mantle`) and FRX5 to FRX7; CRT4 amended, which makes valid some documents that 1.5.0 refused (SREP 77).
- `pyro/@follow`, `@followMargin` and `@followLoss`, and the `pyro` child `pyroBlast` (`pyroBlastType`); rules PYRO9 to PYRO11, PYC5 and PYC6 (SREP 78).
- `medium/@scatterBounces`; `whitewater/@foamMode` (`particles`, `albedo`), `@foamRadius`, `@foamAlbedo` and `@foamRoughness`; rule OCN14 (SREP 79).
- Asset kind `voxelAsset` (`voxelAssetType`); `object3D` primitive `voxels` with `voxels`, `cellSize`, `palette`, `surface` and `surfaceMemoryMiB`; `rigidBody` shape `voxels` with `density`, `maxFragments`, `fragmentMinCells`, `fragmentOverflow` and `anchor`; `fracture/@partition`, `@planes`, `@labels`, `@mode` and `@strength`; rules VOX1 (version 1.3 and later) to VOX15, CRT13 to CRT17 and FRX8 to FRX15; CRT5, FRX3, FRX4 and `burst3D/@count` amended (SREP 80).
- The version gates of SREP 40 (V8, MSQ1, P3D1, OCN1, CRT1, FRX1, GEO1) refuse versions 1.0 to 1.2 only: documents of 1.4 and later that use volumes, media, pyro, mesh sequences, `particles3D`, `ocean`, craters, fractures or globe elevation, refused by 1.5.0 for their version alone, are valid; no document of 1.0 to 1.3 changes verdict; the messages say "1.3 or later" (SREP 83).
- `project/@supersample`: the filtered result is clamped per channel to [0, max(1, M)], M the largest value of that channel among the samples of non-zero weight, instead of SREP 72's [0, 1], so that working values above 1 reach colour finishing and output as they do at `supersample="1"`; Lanczos overshoot above the samples and below 0 is still removed, and a document whose samples all lie in [0, 1] renders the same bytes. Only the documentation of `supersample` changes; no declaration, default or rule. Class: Added (SREP 4). SREP 89 amends SREP 72, which enters in this release: `supersample` does not exist in 1.5.0, so no document valid under a released schema becomes invalid or renders differently (not Breaking), and what changes is the rendering of an attribute 1.6.0 adds, not wording (not a PATCH class). The release stays 1.6.0 either way (SREP 89, amends SREP 72).

### Changed

- `transition/@audio` is documented: the transition mixes the sound of the video layers on its sides at its eased progress (`crossfade` 1 - p and p, `equal-power`, `cut` at p = 1/2, `none`), multiplying their volume, and a sequence junction cuts its sound when its type is `cut`. No declaration changes; DEFINITIONS D19 gains its Sound item and no longer reports `audio` as having no effect. Sound changes for documents with a transition between sound-carrying video layers, against reference engines up to v0.3.1, which ignored `audio`. SREP 82 states no class. It is recorded as Changed after SREP 36, whose Resolution records a change to the rendered output of valid documents as Changed, carried by the MINOR release 1.2.0. Under the letter of SREP 4 a valid document that renders differently is Breaking, which would make this release 2.0.0 and need a Process SREP and a migration tool. The schema editor approved schema 1.6.0 on 2026-10-10 with this entry as Changed and no version gate, so the release is MINOR (SREP 82, Open issues 2 and 3).

### Fixed

- Rules MTX1-baseColorMap, MTX1-normalMap, MTX1-metallicRoughnessMap, MTX1-occlusionMap, MTX1-emissiveMap and MTX1-displacementMap refuse a material map that begins with `#` and names no generator or image asset of the document. 1.5.0 accepted any such value as a file reference. The reference engine resolved it as a file named `#id` beside the document and refused the document with A01 when no such file existed (rs-scene-render 755beb7, which predates SREP 71), so such documents had no defined result. A document whose map named a file literally called `#id` changes meaning. Known documents affected: none in use; the reference engine's own corpus documents `invalid/mtx1-*`, written for these rules, and the kit case `srep-0071-map-not-an-image-source` (SREP 71, Backwards compatibility).
- Rules C15, C43, R15, R48-from, R48-to, C80, VOL5 and GEO2, and SREP 78's PYRO9 to PYRO11, read `xs:boolean` and integer attributes by value, in every lexical form the XSD accepts (`true` or `1`, `false` or `0`, whitespace collapsed; an optional sign, so `+0` and `-0` are 0, and leading zeros), not by one spelling; the XSD and the messages do not change. Verdicts change in both directions, only for documents that write one of these attributes in another form. Now valid: `layer/@reverse="0"` or `" false "` and `@loop="00"`, `"+0"`, `"-0"` or `" 0 "` beside a `timeRemap` (C15; `reverse="0"` was refused), a video with `hasAudio=" true "` or `" 1 "` as an audio track (R15), `repeat/@from="+0"` and `@step="+1"` with `points` (C80), `terrainTileSize="+64"` (GEO2), `pyro/@follow=" 1 "` with `followMargin`, and `followMargin="+2"` (PYRO10, PYRO11). Now invalid: `output/@alpha="1"` or `" true "` with a codec that carries no alpha (C43), a connector end on a node that is, or is inside, a node with `threeD="1"` or `" true "` (R48-from, R48-to), `medium/@blackbody=" true "` or `" 1 "` without a temperature grid (VOL5), and `follow=" true "` with a closed boundary (PYRO9). Class: Fixed (SREP 4), the class SREP 84's Backwards compatibility gives. Each document it now refuses is a combination its rule's own text forbids and did not check (the fourth kind of correction in SREP 4), made through an SREP. SREP 4 also asks the SREP to show that no engine gave such documents a defined result; SREP 84's accepted text does not, and the evidence gathered at acceptance (rs-scene-render main a8310ca7, 2026-10-10) shows it for part of them only. For VOL5, and for C43 with `h264`, `h265`, `av1`, `dnxhr` or `jpeg-sequence`, no engine gave such documents a defined result: the reference fails to render a blackbody medium without a temperature grid and refuses to encode alpha with those codecs (VOL5 and H.264 checked on the kit cases; the other codecs by reading `crates/sr-media/src/encode.rs`). PYRO9 enters in this release with SREP 78, so no released document is affected. Two parts do have a defined result in the reference: for R48 it draws the connector, joined at the node's 2D placement, a picture SREP 16 gives no meaning (it left 2.5D targets out); for C43 with `codec="audio-only"` it writes the audio and ignores `alpha` (by reading `crates/sr-deliver/src/pipeline.rs` and `encode.rs`, not rendered). Under the letter of SREP 4 those two parts are Breaking, which would make this release 2.0.0 and need a Process SREP and a migration tool (SREP 0, Versioning); `tools/release.py next schema` gives 1.6.0 only because this entry keeps the class of the accepted text. The schema editor approved schema 1.6.0 on 2026-10-10 with this entry as Fixed, so the release is MINOR (SREP 84, Open issues). Known documents affected: none of the 576 other kit cases changes verdict; in the reference engine's corpus one document, `c15-reverse-literal` (`reverse="0"`, refused by C15), becomes valid. The documents now accepted only widen what validates (SREP 84).
- Rules C13, C14, C15 (its `speed`), C37, C38, C44, C52, C53, C54, C56, PYRO1, PYRO2, PYRO4, VOL4, P3D3, P3D10, OCN3 and OCN5, SREP 78's PYRO11 and PYC6, SREP 80's FRX11 and SREP 67's ITR1 and SRT1 read their `xs:double`, `xs:decimal` and `xs:positiveInteger` attributes by value, with an optional leading `+` and whitespace collapsed, in the form SREP 84 uses for integers; for exponent forms (`1e0`), which a strict XPath 1.0 `number()` does not read, the verdict of a native validator that reads the value is normative. The XSD and the messages do not change. Verdicts change in both directions, only for documents that write one of these attributes with a leading `+`. Now valid (the rule misfired on them): for example `layer/@speed="+1"` beside a `timeRemap` (C15), `text/@minSize="+0.5"` (C13), `output/@start="+0"` beside segments (C54), `segment/@to="+1"` (C56), `pyro/@voxelSize="+1"` (PYRO1, PYRO11), `particles3D/@lifetime="+1"` (P3D3), `fracture/@planes="+1 0 0 2"` (FRX11), `iterate/@checkEvery="+1"` (ITR1) and `effect/@low="+0.5"` (SRT1). Now invalid (the rule was bypassed): gradient stops at `+1` then `+0.5` (C37), keys at `+1` then `+0.5` (C38), `geoLayer/@domain="0 +1 +0.5"` (C53), `pyroSource/@scaleZ="+0"` (PYRO4), a wave of wavelength `+0.5` under two cells (OCN3) and a whitewater window whose `end` comes before its `start`, written with `+` (OCN5). Class: Fixed (SREP 4), the class SREP 85's Backwards compatibility gives. Each document it now refuses is a combination its rule's own text forbids and did not check (the fourth kind of correction in SREP 4), made through an SREP. SREP 4 also asks the SREP to show that no engine gave such documents a defined result; SREP 85's accepted text does not, and the evidence gathered at acceptance (rs-scene-render v0.3.2, a6f158e2, 2026-10-10, on the kit cases) shows it for part of them only: the reference refuses the PYRO4, OCN3 and OCN5 documents with those rules and the C38 document with E04. Two parts do have a defined result in the reference: it accepts and renders the C37 document and the C53 document. Under the letter of SREP 4 those two parts are Breaking, which would make this release 2.0.0 and need a Process SREP and a migration tool (SREP 0, Versioning); `tools/release.py next schema` gives 1.6.0 only because this entry keeps the class of the accepted text. The class is SREP 85's open issue for the schema editor. Known documents affected: none of the 608 other kit cases changes verdict; in the reference engine's corpus no document written before SREP 85 changes verdict, and two that already wrote exponents, `c13-exponent` and `c38-exponent`, keep the verdict of their value (SREP 85).

### Docs

- The documentation of `pyroCrater`, `particles3D/@gas`, `burst3D/@angle` and `@angleSpread` and `ocean/@bodyDrag`, and the message of P3D10, take the reference engine's wording; no declaration, default or rule test changes (SREP 81).

## 1.5.0 — 2026-10-06

### Added

- The capability manifest format as a file beside the schema, `capabilities-1.schema.json` (SREP 22), with the optional `when` conditions of SREP 63: an entry applies to a document that uses its construct and every construct listed (format 1, a MINOR addition; readers that ignore `when` over-warn and never under-warn). `scene/@version` accepts `1.5` (no version gate: nothing in documents changes).

### Fixed

- Rules R53 (an `xs:IDREFS` list names at least one id) and R54 (an `audiogram`'s `source` names an `audioTrack` of `audioMix`), pattern p77, so that Schematron validators make the checks XSD processors that skip the identity constraints miss (SREP 59). Both reject only documents whose meaning was undefined: an empty list the XSD already forbids, and an audiogram with no track to draw.

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
