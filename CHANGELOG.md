# Changelog — sr-core

The version is `sr_core.__version__`; each release is tagged `vX.Y.Z`. It covers the commands, their options,
exit codes and outputs, and the URL layout of the generated schema reference. It does not cover Python
modules, which are internal; `sr_core.scene` is provisional until its SREP is accepted, and then becomes part of
this contract (that SREP amends SREP 4). The package format has its own version, `formatVersion`, which changes only
through an SREP and is listed here when it does. The schema has its own changelog, [schema/CHANGELOG.md](schema/CHANGELOG.md).

Record every change under **Unreleased** when it lands. `python3 tools/release.py next tools` computes the next
version:

| Class | Bump | For |
|---|---|---|
| Breaking, Removed | MAJOR | a command, option, exit code, output file or reference URL that scripts rely on changes or goes away; a new package-format MAJOR |
| Added, Deprecated | MINOR | new commands or options, new outputs, a new package-format MINOR |
| Changed, Fixed, Security, Docs | PATCH | everything else |

## Unreleased

### Breaking

### Added

### Fixed

- Conformance: `srep-0055-node-shutter-frame0` is no longer pending. It checks the first frame's blur with the default `shutterPhase` (−90°) against SREP 55's sample times, with properties holding their first key before time 0 as the schema defines (blue 180°: cx 320.63; red 360°: cx 322.81; green 0°: sharp at 320.0). The pending note expected a smear on both sides, which would need linear extrapolation before the first key; the schema's default is hold.

## 1.8.0 — 2026-10-20

### Added

- Validates and packs schema 1.7.1 documents: the source release carries schema 1.7.1 and its generated reference under `docs/schema`, and `sr_core.scene` is regenerated from it, so `describe()` and the class documentation carry the attribute documentation of SREP 92 and report schema release 1.7.1. See [schema/CHANGELOG.md](schema/CHANGELOG.md).
- `sr_core.scene`, a Python scene SDK generated from the schema (SREP 91, `srep-0091.md`):
- classes for all 169 complex types, with values checked on assignment;
- reading and writing that keeps comments and lexical forms;
- version gates compiled from the Schematron, with `min_version()` and `version="auto"`;
- checks at four levels (construction, standard library, lxml, engine);
- the `sr-scene` command (`check`, `min-version`, `format`);
- the optional extra `sr-core[validate]` (lxml);
- a valid lexical `str` is accepted for every attribute whose type is not string-valued (numbers, booleans, `xs:dateTime`) and written as given, so a ported builder can write the exact text of the one it replaces;
- `layout="indent"` for `to_bytes` and `write`: libxml2's pretty-print rule (indentation only inside elements that have no text child), equal to `lxml.etree.tostring(..., pretty_print=True)`;
- a class that covers several element names takes the constructor keyword `xml_name`, typed as a `Literal` of those names and refused with `SchemaValueError` otherwise: `Still(xml_name="thumbnail", path=...)` builds a `<thumbnail>` (before, `to_bytes(Still())` could only write `<poster/>`).
- `sr_core.scene` for AI agents and their users (section 3.12, 3.13 and 8 of the SDK SREP draft):
- `UnknownNameError`, a `SchemaValueError` and an `AttributeError`, for a wrong attribute, constructor keyword, `add_<name>` factory, child or `xml_name`, with `suggestions` (another case, `from` for `from_`, close spellings) and the `allowed` names: `<layer> has no attribute 'blendMode'; did you mean 'blend'?`;
- `describe(target)`, `describe_all()` and `element_names()`: documentation, minimum version, content model, children with occurrences, and attributes with type, enumeration, facets, default, required, minimum version and documentation, as a frozen record or JSON of the versioned format `sr-scene-describe/1`;
- `sr-scene describe NAME...`, `sr-scene describe --all --format json`, `sr-scene list` and `sr-scene new`;
- `sr-scene check --format json` carries `"format": "sr-scene-findings/1"`;
- `docs/scene-sdk-guide.md`, whose Python blocks the test suite runs.
- Drift controls:
- `python3 -m sr_core.scene.generate --check`, run by `tools/release.py check`;
- `release schema` regenerates the SDK and needs an Unreleased entry for it.
- `conformance/run.py` gains `--run-pending` (runs the pending cases that have a check: one that now passes is reported as `retire` and fails the run, one that still fails stays pending) and the check form `failure` (`{"code": "PRG12"}`: a non-zero exit, the code in the output, no picture). It prints how many cases were pending.
- `tools/check_hygiene.py` rule R4 also compares `srep/index.md` with the SREP headers (Title, Type, Status, Version, a row for every SREP, ascending order); an intended difference is an `srep/srep-NNNN.md:R4:reason` entry.

### Changed

- `sr_core.scene`: the documentation of an attribute is its `xs:documentation`, or else that of its simple type; it reaches `Attr.doc`, the descriptor's `__doc__`, a docstring after each declaration and the docstrings of the checker stubs (before, the descriptors carried only the declaration's own text, and the stubs none).
- `sr_core.scene`: a refused enumeration value carries `suggestions` and says `did you mean 'multiply'?` for `layer.blend = "mutliply"` (also inside list types and unions); a mistyped class name, `sr_core.scene.Layr` or `sr_core.scene.textanimator`, raises `UnknownNameError` with `kind="class"` and `did you mean 'Layer'?` (still an `AttributeError`; `from sr_core.scene import Layr` is still an `ImportError`). `SchemaValueError` now pickles.
- `sr_core.scene`: an unknown attribute, factory or child now raises `UnknownNameError` (still an `AttributeError`, or a `SchemaValueError` for a child) instead of a bare `AttributeError`.

### Fixed

- `scenerender-vpkg run`: a render step that names an `output` and a `to` renders that output by its id on py, rs and js, then copies its file to `to`, so the output keeps the settings it declares (size, codec, quality, colour, audio, report). Before, py and rs got `-o TO`, which wrote an ad-hoc output with the engine's defaults. A scene, or the engine variant of one, that lacks the named output id now fails the step instead of rendering something else. On c, which cannot select an output, `run` prints a warning that the output's settings are not applied.
- `sr_core.scene` (second review, 2026-10-12):
- `add` and direct changes of `.nodes` refuse the element itself or one of its ancestors; before, the tree became a cycle and `iter`, `check`, `xml_path` and writing never returned;
- white space is XML white space only (space, tab, CR, LF): a no-break space or U+2003 in element-only content is `xsd:occurs` at level 1 as it is for lxml, `layout="pretty"` keeps it instead of deleting it, and `new_id`, the program `mode` test and the gate compiler no longer trim Unicode spaces;
- `new_id` keeps an index of the document's ids, so building a document with one `new_id` per element is linear (8,000 ids: quadratic before);
- the generator checks the XSD against the XML Schema vocabulary it implements (D3): `xs:unique`, `xs:key`, `xs:keyref`, `xs:any`, `xs:import`, `nillable`, `targetNamespace` and the like fail the generation instead of being ignored, which made the SDK pass documents lxml refuses;
- `read` ignores comments and processing instructions inside a DOCTYPE's internal subset; it moved them into the prolog, and the written document's C14N 2.0 form differed from the original's;
- `sr-scene check` reports a clean document as `ok (level 1)`, `ok (levels 1, 2)` ..., and its JSON output has `levels`: a bare `ok` after level 1, which runs only the Schematron's version gates, overstated the check;
- the SREP draft (4.3) no longer says NaN and the infinities are refused outright: a Python NaN or infinity is, while the `xs:double` lexical forms `NaN`, `INF`, `-INF` are accepted as a `str` unless a facet refuses them;
- the D4 test of the generated gates takes its expectation from the `.sch` through ElementTree and two regular expressions instead of `compile_gates`, which the generator itself uses, so a fault there cannot pass unseen;
- `conformance/run.py` no longer reports `pass` for a case that checks nothing: an `expected.json` entry with an unknown key, an empty check or no check at all is an `error`, and so is a form whose checks did not run.
- `conformance/make_cases.py` reads the implicit camera's field of view and the default sensor width from the constants block in `conformance/CONVENTIONS.md` (2.8) instead of restating them; a test fails when the block and the prose disagree. The generated cases are unchanged.
- The case generators of `conformance/tools/` are re-run by `tests/test_conformance_generators.py`, which fails when the committed `srep_cases/` differ from what they write; the README's SDK example is executed from the README.
- `srep/index.md` row 83 carries the header's title.
- `docs/vpkg-howto.md` names every option of `scenerender-vpkg` (`pack --date`, `--with-archive`, `unpack`/`run --no-fetch`, `verify --shallow`, `info --json` were missing) and says that only the Rust engine is active; `tests/test_docs_cli.py` fails when an option is missing and runs every `python3 -m` command of the README.
- `srep/srep-0000-generated-marker-ids.md`, the unnumbered draft of SREP 57, is removed; hygiene rule R4 now fails a `srep-0000-*.md` file whose title a numbered SREP carries.
- Docstrings for every public symbol of `vpkg/pack.py`, `review/{scene,pdf,cli}.py` and `schemadoc/html.py`; `tests/test_docstring_coverage.py` keeps the coverage from falling.
- `srep/index.md` says that engine-repository paths cited in SREPs are not files of this repository.
- The corpus differentials of the SDK (D5, D6, the gates and the name tests) run by default; `SR_SCENE_CORPUS=0` switches them off. CI no longer sets a variable to enable them.
- The tests of SREPs 76 to 85 no longer skip when the `schema-1.5.0` tag is missing: the two 1.5.0 files are kept, with their hashes checked against the inventory, in `conformance/tools/baseline-1.5.0/`.
- `tests/test_conformance.py` regenerates `conformance/cases/` and `assets/` from nothing, so a file nobody generates fails it; the three hand-kept case files moved to `tests/fixtures/kit/`.
- `tests/test_drift_p2.py` pins the capability-manifest schema to the code and the validator that read it, the counts quoted in SREP 0000 and here to the schema, the engine-gap inventory to the SREP diff blocks, and the packages `ci.yml` installs to the extras and to what the tests import (including what they skip when absent).

### Docs

- The schema documents its attributes (schema CHANGELOG, SREP 92, `srep-0092.md`): `tests/test_schema_attribute_docs.py` fails for an attribute with neither documentation nor an entry in `tests/undocumented-attributes.txt`. The bundled schema copy and generated reference carry the sentences.
- 746 attribute docs corrected after an adversarial review against the engine code.
- `docs/scene-sdk-guide.md` section 10 explains the cost of a path-traced camera, width × height × `pathSamples` × `maxBounces` per frame, and how to choose the two values. Its Python block, run by `tests/test_scene_guide.py`, reads the defaults and maxima from the schema.

## 1.7.0 — 2026-10-12

### Added

- Validates and packs schema 1.7.0 documents: the source release carries schema 1.7.0 and its generated reference under `docs/schema` (SREP 87, with the exception of SREP 90; document version 1.7). See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has the 15 cases of SREP 87 (`conformance/srep_cases/srep-0087.json`, written by `conformance/tools/srep87_cases.py`, with the modules `srep87-*.wasm`), and SREP 66's `srep-0066-program-id-collision` is amended by SREP 87. The reference implementation of SREP 87 is on rs-scene-render main (6602b81d) and passes all 16; 10 of them run (no longer pending), and the 3 failure cases of SREP 87, the amended SREP 66 case and the 2 render-comparison cases of `seed-local` stay pending in `conformance/tools/kit_pending.py` with the result of the check by hand, because `run.py` cannot express their check. `srep-0072-precision-3d-note` is no longer pending: the reference reports PREC1 since main 285a6931. See [schema/CHANGELOG.md](schema/CHANGELOG.md).

## 1.6.0 — 2026-10-11

### Added

- Validates and packs schema 1.6.0 documents: the source release carries schema 1.6.0 and its generated reference under `docs/schema`, with pages for the new types (SREPs 66 to 85 and 89; document version 1.6). See [schema/CHANGELOG.md](schema/CHANGELOG.md).
- `conformance/run.py` gains the check form `audio`: it delivers the document's audio-only WAV output (`encode --output`) and measures the gain of each test tone at given times (SREP 82).

### Tooling

- The compatibility kit has the 377 cases of SREPs 66 to 80, 82 to 85 and 89 (`conformance/srep_cases/srep-0066.json` to `srep-0089.json`, written by the generators in `conformance/tools/`); `conformance/tools/kit_pending.py` lists the 12 that stay pending, with the reason for each: 11 whose check `run.py` cannot express yet (failed renders of SREPs 66 and 69, render comparisons of SREP 71), each checked by hand on the reference, and SREP 72's `srep-0072-precision-3d-note`, which the reference fails.
- `conformance/tools/engine_gap.py` measures the gap between sr-core's schema and a reference engine's vendored copy (SREPs 76 to 81; `conformance/tools/engine-gap-1.5.0.json`).
- CI checks out the tags, which the tests of SREPs 76 to 83 read.

## 1.5.0 — 2026-10-06

### Added

- Validates and packs schema 1.5.0 documents: the packaged schema, the generated reference under `docs/schema` and the files `pack` and the lints read are schema 1.5.0 (SREP 59: rules R53 and R54; document version 1.5), and the schema folder carries `capabilities-1.schema.json` (SREPs 22 and 63). See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has the cases of SREPs 58 (`srep-0058-jump`, `-vertex`), 59 (`srep-0059-identity`, `-empty-idrefs`, `-audiogram-source`) and 63 (`srep-0063-when-raster`, `-pathtrace`), and `srep-0016-group-box` of the SREP 16 erratum; those the Rust reference does not pass yet are pending. `tests/test_srep_0059.py` and `tests/test_capabilities.py` check the schema side; a case invalid only by an XSD identity check that libxml2 skips is skipped by the generic case test.
- The 11 `srep-0052-caption-lines-*` cases are pending until the Rust reference has the `captions` command (gap/srep-52-captions-dump); the kit keeps their captions check form.

## 1.4.0 — 2026-10-06

### Added

- Validates and packs schema 1.4.0 documents: the packaged schema, the generated reference under `docs/schema` and the files `pack` and the lints read are schema 1.4.0 (SREP 57: a `beat.N` or `bar.N` marker id is accepted where a marker is named, when the scene has a `beatGrid`; document version 1.4). See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has the 19 cases of SREP 57 (`conformance/srep_cases/srep-0057.json`), pending until the Rust reference implements it, and `tests/test_srep_0057.py` checks the schema side.

## 1.3.0 — 2026-10-06

### Added

- Validates and packs schema 1.3.0 documents (every accepted SREP up to 56, and SREP 40), which the 1.2.0 package rejects: the packaged schema, the generated reference under `docs/schema` and the files `pack` and the lints read are now schema 1.3.0. See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has cases for SREPs 15 to 56 (`conformance/srep_cases/*.json`, with their assets under `srep_cases/assets/`); `make_cases.py` writes them into `cases/` and `expected.json`.
- `conformance/run.py` gains the check form `findings`: it runs `validate --format json` (or the render, with `via: render`, for a report that exists only at frame evaluation) and compares the finding codes, their count, message fragments, the codes that must be absent and the document's validity. A case with `pending` is skipped and listed with its reason, never counted as a pass. numpy and Pillow are needed only by pixel cases.
- An `output` entry of `expected.json` may select the range and frame to render (`id`, `time`, `start`, `end`, `frame`), for SREP 13's overlay case.
- `conformance/make_test_font.py` generates the pinned font of SREP 20 and 21's cases, and `make_model_assets.py` the models of the model cases (`materials.glb`, `joints.glb`, `morphs.glb`).
- A test per SREP (`tests/test_srep_00NN.py`) checks its schema rules and its case documents, `tests/test_schema_rules.py` holds the shared helpers, and a pending-case test keeps the `pending` entries honest.
- `conformance/DEFINITIONS.md` D11 states the lighting convention the engine implements (no factor π for punctual lights), with a history paragraph; SREP 25 makes the engine's behaviour the reference.

### Fixed

- `pack` lint: paths relative to the user's home (`"~/..."`, `expanduser("~")`, `$HOME/...`, `Path.home()`) are now an error, `home-path`, as `/home/...` already was. A script that read a brand kit through `expanduser("~/...")` passed the lint and packed a build step that could not run anywhere else. `docs/vpkg-howto.md` §3.4 describes vendoring shared code and kits into the project with a lock.

## 1.2.0 — 2026-09-30

### Added

- `sr-review` (also `python -m sr_core.review`) writes a PDF review sheet of a scene: a cover with its facts and outputs, one page per section (`section` markers inside `chapter` markers, else chapters, else top-level groups) with a frame, its captions and its markers, then the open to-dos, sources and credits, and metadata. `--engine` renders the frames with the engine's still command, the same commands `scenerender-vpkg run` uses; `--frames` reads and keeps them. Exit 0 written, 1 written with missing frames, 2 nothing written. Standard library only; frames are smaller (JPEG) when Pillow is installed.

### Tooling

- The compatibility kit gains cases for SREP 9 (tile zoom, raster warp, vector tiles), SREP 10 (globe orientation), SREP 11 (substeps, damping, velocity) and SREP 13 (clamping, crossfade, alignment, focus, overlay without segments); `run.py` rewrites every `../assets/` path of a case, not only `src`.
- `conformance/run.py` renders a case's named output at a given output time when its entry in `expected.json` has `output` (`{"id", "time"}`), for SREP 13's cases; an engine that cannot is reported, not crashed.
- The schema-rule tests skip conformance cases of SREPs that are not yet accepted (unnumbered drafts, Draft or Review): their cases use syntax the canonical schema gains only on acceptance.

## 1.1.0 — 2026-09-29

### Added

- Package format 1.1 (SREP 6): `packed.metaSha256` covers `README.md` and `vpkg.schema.json`, and `pack` writes 1.1 manifests. 1.0 packages still read, with a warning that their metadata is not hash-covered. The format schema is `vpkg-1.schema.json`, with `$id` `urn:scene-render:vpkg:1`.

### Security

- `verify` and `unpack` never write from a package once any check fails, and never write outside the extraction folder. Before, a hostile manifest path could write anywhere, even during a plain `verify`.
- Paths with control characters are rejected. A newline could hide a `..` from the path check.
- `fetch` validates the manifest and keeps every download inside the project.
- `pack` refuses symbolic links that leave the project. It had bundled the files they pointed at.

### Fixed

- References to files outside the project are rewritten in `<include>`d documents too. Such packages used to fail their own `verify`.
- Font files anywhere in the project (for example `assets/`) are found when resolving font families.
- Render steps are out of date when their scene or any file it references changes.
- Media types come from a fixed table, so a project packs to the same bytes on every machine.
- The README no longer states version numbers that go stale. The reference's marker file no longer embeds the tools version, which had made a tools-only release fail `release.py check`.
- The sdist includes `conformance/`.
- `scenerender-vpkg run` reports a missing engine command with the alias it expected and how to provide it (a symlink, `VPKG_ENGINE_<ID>` or `engines.json`), instead of a Python traceback.

### Docs

- SREP 4: a correction that rejects only documents whose meaning was undefined is Fixed, not Breaking.
- SREP 8: the version gate and the Schematron checks for the 1.1 additions.
- SREP 7 adopts `conformance/CONVENTIONS.md` and the new `conformance/DEFINITIONS.md` (definitions D1–D27 and preset tables P1–P2, copied in so the specification is complete). It states the precedence, the rotation handedness of layers and 3D objects, and the explicit-camera default.
- SREP 0 describes the compatibility kit as it works: geometric measurements, no reference renders.
- The vpkg how-to and SREP 1 explain why the default engine commands are aliases (`scene-render-rs`, `-c`, `-js`) and how to create them.

### Tooling

- CI covers Linux and macOS on Python 3.10, 3.12 and 3.13, runs the schema-rule and conformance-runner tests, and runs the installed commands from outside the checkout. A test runs the vpkg how-to's walkthrough with the finished `vpkg.json` taken from the how-to itself.
- `conformance/run.py` exits non-zero when any case fails, reports a missing engine, timeout or failing engine as that case's error instead of crashing or passing, and always writes its report.
- Conformance cases that can detect what they test:
- a2 has an off-centre anchor, so the rotation sign shows;
- the glTF marker in b5 is asymmetric and single-sided, with a back-facing quad that must not appear;
- new cases: b7 (combined yaw and pitch), b8 (`focalLength`), d1 (object3D rotation order), d2 (2.5D layer rotationY) and d3 (object3D rotationY).
- The conformance runner is tested: failing and missing engines, wrong pictures, and exact regeneration of the cases.
- `.github/workflows/ci.yml`: tests on Python 3.10 and 3.12, `release.py check` and `check_hygiene.py --artifacts` on every push and pull request.
- `conformance/`: the compatibility kit (normative conventions, cases, runner) now lives in this repository. The runner finds engines through environment variables or the `scene-render-*` aliases, not machine paths.

## 1.0.1 — 2026-09-29

### Fixed

- The sdist is a complete source release. It ships `schema/`, `docs/`, `srep/`, `tools/` and `tests/`, and the tests pass from it; before, they failed at collection.
- Installation instructions and examples use neutral paths and projects: the README (and so the package metadata), the vpkg how-to and the `run` module documentation.

### Tooling

- `tools/release.py archive schema` builds the schema release tarball from a tag: the XSD, the Schematron, their hashes, README, CHANGELOG, LICENSE and the HTML reference. The same tag gives the same bytes.
- `tools/check_hygiene.py` checks that tracked files and release artifacts carry only releasable material: no working material, private paths or unpublished references, SREP records complete, artifacts complete.

### Docs

- SREP 0 is Active, and states when documentation-only and process SREPs are Final or Active.
- SREP decision records state the decision and date only.
- The SREPs name the conformance suite, not a local folder.
- SREP 5: engine-neutral wording in the schema.

## 1.0.0 — 2026-09-29

### Added

- `scenerender-vpkg`, moved from py-render (`33caa35`). It writes and reads package format 1.0 ([SREP 1](srep/srep-0001.md)).
- Package-format compatibility: a 1.N reader reads later 1.M packages, reporting what it doesn't know as warnings; other
  majors get a clear refusal; `pack` never writes a version newer than its own.
- The package format's identifier is `urn:scene-render:vpkg:1.0` (JSON Schema `$id`, and `$schema` in new
  manifests), replacing a py-render URL; older manifests remain valid.
- `sr-schemadoc`: the static HTML reference of the canonical schema, reproducible byte for byte, with `--check`.
- `schema/`: the canonical scene-render XSD and Schematron (its versions are in `schema/CHANGELOG.md`).
- `tools/release.py`: computes and applies version bumps from the changelogs.
- The SREP process ([SREP 0](srep/srep-0000.md)) and SREPs 1–4.
