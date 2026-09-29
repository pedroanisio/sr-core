# Canonical scene-render schema

These files are the one canonical copy of the scene-render format. Engines vendor them unchanged and check
the hashes in [SHA256SUMS](SHA256SUMS).

| File | What |
|---|---|
| `scene-render.xsd` | structure, types and defaults (XML Schema 1.0) |
| `scene-render.sch` | cross-field rules, checked after the XSD (ISO Schematron, XPath 1.0 + EXSLT strings) |

The file names carry no version. The format version is the XSD's `xs:schema/@version` (now `1.1`), and each
released version is a tag in this repository ([SREP 3](../srep/srep-0003.md)).

**Baseline.** Imported unchanged from `rs-scene-render` `origin/main` `5e8ff6e` on 2026-09-29 ([SREP 0](../srep/srep-0000.md)).

**Changes since the baseline:** [SREP 2](../srep/srep-0002.md) (XSD header wording), [SREP 3](../srep/srep-0003.md) (unversioned file names).

**Changing them.** Only through an accepted SREP. In the same change:

```bash
sha256sum scene-render.xsd scene-render.sch > SHA256SUMS
python3 -m sr_core.schemadoc          # regenerate ../docs/schema/ (the tests fail if it is stale)
```

The HTML reference is [docs/schema/index.html](../docs/schema/index.html).
