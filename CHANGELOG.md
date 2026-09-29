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
