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
