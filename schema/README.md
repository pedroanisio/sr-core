# Canonical scene-render schema

These files are the one canonical copy of the scene-render format. Engines vendor them unchanged and check
the hashes in [SHA256SUMS](SHA256SUMS).

| File | What |
|---|---|
| `scene-render.xsd` | structure, types and defaults (XML Schema 1.0) |
| `scene-render.sch` | cross-field rules, checked after the XSD (ISO Schematron, XPath 1.0 + EXSLT strings) |
| `CHANGELOG.md` | every schema release and what changed |

**Versions.**
- The file names carry no version.
- The release version is the XSD's `xs:schema/@version` (MAJOR.MINOR.PATCH), and each release is tagged
  `schema-X.Y.Z` in the sr-core repository.
- Documents declare only MAJOR.MINOR, as in `<scene version="1.1">`.

**Validation.** Validate a document against the XSD first, then against the Schematron rules.

**Reference.** The HTML reference generated from these files is [docs/schema/index.html](../docs/schema/index.html).

**Changes.** The files change only through an accepted Scene Render Enhancement Proposal (SREP), recorded in
[CHANGELOG.md](CHANGELOG.md). SREPs are in the `srep/` folder of the sr-core repository. When a change lands, in
the same commit:

```bash
sha256sum scene-render.xsd scene-render.sch > SHA256SUMS
python3 -m sr_core.schemadoc          # regenerate ../docs/schema/ (the tests fail if it is stale)
```
