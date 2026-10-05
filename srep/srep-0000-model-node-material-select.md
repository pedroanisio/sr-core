---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart), from the Rust engine's code and the NOLN glTF/FBX assessment"
  date: "2026-10-05"
---

```
SREP:            0
Title:           Select a node and override materials of an imported model
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Standards
Created:         2026-10-05
Schema-Version:  1.2
```

# SREP 0 (draft) — Select a node and override materials of an imported model

## Abstract

An `object3D` of `primitive="mesh"` draws a whole imported model (glTF, GLB, FBX, OBJ, USD, PLY), and its `material`
attribute replaces every material of the model at once. Two optional attributes remove the need to edit the file in a
modelling tool: `node` draws only the named node and what is under it, placed at the object's own origin, and
`materialOverride` replaces chosen materials of the model, by name, with materials of the document, leaving the rest as
imported. A document that uses neither renders as before.

## Motivation

The NOLN music video wants one chess piece (the knight) out of a Poly Haven chess-set file that holds all the pieces on a
board, and wants the model's materials changed (a clay look for the knight, the rim light unchanged on the rest). With
the baseline the whole set is drawn, or every material is replaced by one document material. The engine's assessment of
glTF and FBX use for the video lists "pick one node or mesh out of a file" and "per-material override" as missing
(NOLN glTF/FBX assessment, §A.1 and §D item 4), and says editing the file in Blender is the only workaround.

## Specification

### Syntax

```xml
<!-- object3DType gains -->
<xs:attribute name="node" type="xs:string">
  <xs:annotation><xs:documentation>With primitive="mesh" and an imported model: draw only the node of that name and its
  descendants, placed so that the node's own origin is the object's origin (the node's transform within the model is
  dropped, the transforms below it are kept). The first node of that name in the model's node order is used.
  </xs:documentation></xs:annotation>
</xs:attribute>
<xs:attribute name="materialOverride" type="xs:string">
  <xs:annotation><xs:documentation>With primitive="mesh" and an imported model: a space-separated list of
  imported-material-name:document-material-id pairs. Each primitive of the model whose material has that name is drawn with
  the document material instead. A material with no pair keeps its imported look. @material, when present, replaces every
  material and takes precedence.</xs:documentation></xs:annotation>
</xs:attribute>
```

```xml
<sch:rule context="object3D[@materialOverride]">
  <sch:assert id="MOV1" test="count(str:tokenize(normalize-space(@materialOverride),' ')) &gt; 0 and count(str:tokenize(normalize-space(@materialOverride),' ')) = count(str:tokenize(normalize-space(@materialOverride),' ')[contains(.,':') and substring-before(.,':')!='' and substring-after(.,':')!=''])">@materialOverride is a space-separated list of name:id pairs.</sch:assert>
</sch:rule>
```

That each `id` names a document material cannot be decided by the schema alone for the same reason `@material` is not
checked statically for imported models (the name side depends on the file); an unknown `id` is reported when the object is drawn
(Semantics 3).

New attributes with no default, accepted in every version (SREP 0, Versioning).

### Semantics

**1. Applicability.** `node` and `materialOverride` apply to an `object3D` that draws an imported model
(`primitive="mesh"` with a `mesh` asset that is a model, not a mesh sequence). On any other object they have no effect and
a validator SHOULD report them as inert attributes (SREP 18).

**2. Node selection.** Let N be the first node of the model, in the model's node order, whose name is `node`. Only the
primitives of N and of its descendants are drawn. Their transforms are taken relative to N: a point is drawn at
`object · basis · N⁻¹ · W`, with `W` the model-space world matrix of the primitive's node at the animation pose and `basis`
the source-to-scene axis conversion, so that N's own origin is the object's origin. Skinned and morphed primitives follow
the whole model's pose (the joints do not have to be under N). When no node has that name the object draws nothing and the
engine MUST report the missing name.

**3. Material override.** A `materialOverride` of `a:x b:y` replaces the material named `a` with the document material
`x`, and `b` with `y`. A primitive whose material name matches no pair keeps its imported material. A name that matches no
imported material has no effect and the engine SHOULD report it. An `id` that names no document material MUST be reported
as an error. A document material takes the place of the imported one entirely, as `@material` does for every material:
texture coordinates, maps and parameters come from the document material.

**4. Precedence.** With `@material`, every primitive uses it and `materialOverride` has no effect.

### Defaults and the neutral case

Neither attribute set: the whole model is drawn with its imported materials, as before.

## Rationale

- **Node-local placement.** The node's own transform inside the model (a board position, say) is not part of what the
  author wants to place; the object's `x`, `y`, `z` and rotation already place it. Descendants keep their relative
  transforms, so a rigged knight's parts stay assembled.
- **By name.** glTF, FBX and USD all name nodes and materials; indexes change when the file is re-exported.
- **Pairs, one attribute.** A model has several materials; a list of pairs avoids a child element for a three-word
  mapping, and keeps `@material`'s meaning.

## Rejected alternatives

- **Selecting by mesh index.** Fragile across exports.
- **Dropping the node's world transform only when asked.** Authors want the piece at the origin; keeping the board offset
  needs no attribute (do not select) and a selected piece at its board position is rarely wanted.
- **A `<materialOverride>` child element.** More syntax for the same mapping.

## Backwards compatibility

Class: Added, MINOR in effect, accepted in every version. No valid document changes validity or rendering.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | filter the model's draw list by node subtree with the relative matrix, and look up overrides by material name, in the 3D model draw path; rules mirrored in the rule engine | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-model-node` | a two-node model (red triangle, green triangle at different offsets): `node` of the second draws only the green one, at the object's origin | 1 px |
| `srep-NNNN-model-node-missing` | an unknown `node` draws nothing and is reported | exact |
| `srep-NNNN-model-material-override` | `materialOverride="a:blue"` draws the primitive with material `a` blue and the other material unchanged | exact colours |
| `srep-NNNN-model-material-precedence` | with `@material` set, `materialOverride` has no effect | exact colours |

## Open issues

- Whether `node` should accept a path (`Parent/Child`) for models with repeated names.
- Whether USD prim paths are the names for USD models.

## References

- SREP 0; SREP 18 (inert attributes); the engine README's description of `material` and `materialVariant`.

## History

- 2026-10-05: first draft.
