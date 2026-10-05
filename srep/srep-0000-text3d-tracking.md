---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart), from the Rust engine's code and the style-library finding T21 F3"
  date: "2026-10-05"
---

```
SREP:            0
Title:           Add tracking to extruded 3D text
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Standards
Created:         2026-10-05
Schema-Version:  1.3 (SREP 15 and the other 1.2 drafts keep 1.2)
```

# SREP 0 (draft) — Add tracking to extruded 3D text

## Abstract

`object3D` with `primitive="text"` extrudes the outlines of a string. It has no letter spacing, so a title in 3D cannot be
spaced the way the same title is in 2D, where `textAnimator/@tracking` and the text asset's `tracking` give extra space in
thousandths of an em. `object3D` gains an optional `tracking`, in the same unit, that adds space after every character of
the extruded string. The attribute is valid only on 3D text, and a document that uses it declares version 1.3 or later, like the
other `object3D` additions of that version. A document without it renders as before.

## Motivation

A style-library finding (T21 F3 of the engine's task list) needed an extruded title with the open letter spacing the 2D
version of the same title has. With the baseline rule the glyph advances are the font's own, so the 3D title is set tighter than
its 2D twin, and the only workaround is one `object3D` per letter placed by hand. The engine's 3D text path
and its collider path build the same outlines from the same function, so the attribute has to reach both.

## Specification

### Syntax

```xml
<!-- object3DType gains -->
<xs:attribute name="tracking" type="xs:double">
  <xs:annotation><xs:documentation>Extra space after every character of primitive="text", in thousandths of an em of the
  text size (the object's height). Negative values tighten. Requires version 1.3 or later; valid only with primitive="text".
  </xs:documentation></xs:annotation>
</xs:attribute>
```

```xml
<!-- the version gate, written as the 1.0 rules V1 to V7 are: forbidden in the versions before the one that introduces it -->
<sch:rule context="/scene[@version='1.0' or @version='1.1' or @version='1.2']">
  <sch:assert id="TXT1" test="not(.//object3D[@tracking])">object3D @tracking requires version="1.3" or later.</sch:assert>
</sch:rule>
<sch:rule context="object3D[@tracking]">
  <sch:assert id="TXT2" test="@primitive='text'">@tracking applies to object3D primitive="text".</sch:assert>
</sch:rule>
```

A new attribute with no default.

### Semantics

Let `s` be the text size in pixels (the object's `height`, default 100) and `t` the value of `tracking`. After the glyphs of the
string have been laid out with the font's own advances and kerning (the layout the extrusion uses without `tracking`), the
glyph of character `i` (counting from 0, in layout order) is moved along the baseline direction by `i · t · s / 1000`
pixels. The spacing after the last character does not move any glyph, so it does not change the geometry. The extruded block
is then centred on the object's origin, as without `tracking`.

`tracking` applies to the mesh the object draws and to the collider built from the same text. A change of `tracking`
changes the mesh, so mesh caches key on it. `tracking` of 0 or absent is the baseline layout.

### Defaults and the neutral case

Absent `tracking`, geometry is identical to the baseline.

## Rationale

- **The 2D unit.** `textAnimator/@tracking` and the `tracking-in` preset use thousandths of an em (DEFINITIONS, P1); the
  same unit lets a 3D title match its 2D twin.
- **Moving glyphs after layout.** The extrusion function lays out text once and outlines its glyphs; adding the offset by glyph
  index keeps kerning and shaping as they are, and changes nothing for the neutral case.
- **Version 1.3, not 1.2.** The master schema is 1.1.4 and 1.2 is claimed by SREP 15 and the other 1.2 drafts, which are still
  drafts; the other `object3D` additions that the Rust engine carries are already on 1.3. The editor sets the version on
  acceptance. TXT1 forbids the attribute before 1.3 (as V1 to V7 forbid the 1.1 additions under 1.0) and so allows it in 1.3 and
  every later version.

## Rejected alternatives

- **One object per letter.** The workaround it replaces; it breaks kerning and doubles the scene's nodes.
- **A font-level feature** (OpenType `kern` adjustments). Not an author control.
- **`letterSpacing` in pixels.** The 2D attribute is in em; a pixel unit would not follow the size.

## Backwards compatibility

- **Class: Added, MINOR (1.3).** New attribute, version-gated by TXT1; no valid document changes.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | `sr_text::extrusion::outline_polygons` takes a tracking parameter; the 3D text mesh (render path), the text solid and its collider read it; the mesh cache key includes it | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-text3d-tracking` | `primitive="text"` of "II" at `height="100"`, flat orthographic view: the horizontal distance between the two stems grows by `tracking · 0.1` px (200 gives 20 px) | 1 px |
| `srep-NNNN-text3d-tracking-rules` | `tracking` on a `box` fails TXT2; on text under version 1.2 fails TXT1; under 1.3 it passes | exact |

## Open issues

- **D9.** This draft does not claim to settle the open readings of DEFINITIONS D9 for 3D text; it adds a unit-for-unit
  counterpart of the 2D attribute only.
- Whether tracking should also apply to vertical text.
- **Glyphs are not characters.** A ligature or a cluster is one glyph in layout order, so "character `i`" above means glyph `i`
  of the layout; for text without ligatures or combining marks the two agree. The draft counts glyphs, which is what the engine
  can do without a second layout pass; the 2D attribute counts characters of the shaped text, and the two may differ for ligatures.

## References

- SREP 0; DEFINITIONS P1 (the unit of `tracking`).

## History

- 2026-10-05: first draft.
