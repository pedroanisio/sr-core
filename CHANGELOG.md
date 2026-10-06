# Changelog — sr-core

The version is `sr_core.__version__`; each release is tagged `vX.Y.Z`. It covers the commands, their options,
exit codes and outputs, and the URL layout of the generated schema reference. It does not cover Python
modules, which are internal. The package format has its own version, `formatVersion`, which changes only
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
