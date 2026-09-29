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

- `scenerender-vpkg run` reports a missing engine command with the alias it expected and how to provide it
  (a symlink, `VPKG_ENGINE_<ID>` or `engines.json`), instead of a Python traceback.

### Docs

- The vpkg how-to and SREP 1 explain why the default engine commands are aliases (`scene-render-rs`, `-c`, `-js`) and
  how to create them.

### Tooling

- `.github/workflows/ci.yml`: tests on Python 3.10 and 3.12, `release.py check` and `check_hygiene.py --artifacts` on every push and pull request.
- `conformance/`: the compatibility kit (normative conventions, cases, runner) now lives in this repository. The
  runner finds engines through environment variables or the `scene-render-*` aliases, not machine paths.

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
