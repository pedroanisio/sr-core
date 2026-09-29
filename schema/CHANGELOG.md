# Changelog — scene-render schema

The version is `xs:schema/@version` in `scene-render.xsd`; each release is tagged `schema-X.Y.Z`. Documents
declare only MAJOR.MINOR (`<scene version="1.1">`), so a PATCH release never changes what a document says.

Record every change under **Unreleased** when it lands, in the class that fits, with its SREP. The next version is
computed from those classes by `python3 tools/release.py next schema`:

| Class | Bump | For |
|---|---|---|
| Breaking, Removed | MAJOR | a valid document becomes invalid or renders differently |
| Added, Deprecated | MINOR | new elements, attributes, enumeration values or asset kinds; also add the new MAJOR.MINOR to `scene/@version` |
| Changed, Fixed, Security, Docs | PATCH | documentation, Schematron messages, stricter wording with no change in validity or rendering |

## Unreleased

### Breaking

### Added

### Fixed

## 1.1.1 — 2026-09-29

### Docs

- The header names every engine as the schema's users and sr-core as its canonical home ([SREP 2](../srep/srep-0002.md)).
- The canonical files are `scene-render.xsd` and `scene-render.sch`; the header names its companion by that
  name, and the release version moves into `xs:schema/@version` ([SREP 3](../srep/srep-0003.md), [SREP 4](../srep/srep-0004.md)).

## 1.1.0 — 2026-09-29

Baseline: `rs-scene-render` `schema/scene-render-1.1.xsd` and `.sch` at `5e8ff6e`, imported unchanged
([SREP 0](../srep/srep-0000.md)).
