---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart), from the Rust engine's motion path evaluation and the NOLN motion research (E7)"
  date: "2026-10-05"
---

```
SREP:            0
Title:           Add an additive mode to motionPath
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Standards
Created:         2026-10-05
Schema-Version:  1.2
```

# SREP 0 (draft) — Add an additive mode to `motionPath`

## Abstract

A `motionPath` replaces the node's `x` and `y` with points of an SVG path. A node that also moves by its own keys,
links or expressions, a puppet that walks and sways, loses one of the two. A new boolean attribute, `additive`, makes the
path an offset instead: the node's position is its own `x`, `y` plus how far the path has gone from its start. A
`motionPath` without `additive` is unchanged.

## Motivation

The NOLN motion research (§1.6 and item E7): "additive motion path (path offsets x/y instead of replacing); marionette
sway along a path". With the Rust reference the path sets `x` and `y` outright, so a keyed `x` under a `motionPath` is
ignored, and a sway has to be built as a separate parent node.

## Specification

### Syntax

```xml
<!-- motionPathType gains -->
<xs:attribute name="additive" type="xs:boolean" default="false">
  <xs:annotation><xs:documentation>true: the path is an offset. The node's position is its own x and y (keys, link,
  expression) plus the path's point at the progress minus the path's first point, so the node starts where it would
  without the path. false: the path's point is the position.</xs:documentation></xs:annotation>
</xs:attribute>
```

```xml
None.
```

New attribute with a neutral default, accepted in every version (SREP 0, Versioning).

### Semantics

Let `(x, y)` be the node's own position at the frame (its animated or static `x` and `y`), `P(p)` the path's point at
progress `p` (as before: `p` from the key or the time, the path's own length parameterisation, `constantSpeed`), and `P(0)`
its first point. With `additive="true"` the node's position is `(x, y) + P(p) − P(0)`. Orientation (`autoOrient`,
`orientOffset`) is unchanged: the path's tangent at `p` is added to the node's rotation as before.

### Defaults and the neutral case

`additive` absent or `false`: the position is `P(p)`, as before.

## Rationale

- **Relative to the first point** so that the authored path can be drawn anywhere (the same offsets whatever the
  coordinates of the drawing), and so that `p = 0` leaves the node where it is, as an additive effect should.
- **One attribute**, the one `animate` already uses for the same idea (`additive`).

## Rejected alternatives

- **The path's coordinates as the offsets** (position = own + `P(p)`): the node would jump by the path's first point.
- **A second element for offsets.** The path machinery is the same.

## Backwards compatibility

Class: Added, MINOR in effect, accepted in every version. No valid document changes validity or rendering.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | the node's local transform adds the path offset instead of replacing the position | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-motion-path-additive` | a node at (100, 50) with `M 0 0 L 100 0`, `additive`: at progress 0.5 it is at (150, 50); the same path drawn as `M 20 20 L 120 20` gives the same | 1e-6 |
| `srep-NNNN-motion-path-additive-keyed` | the node's own `x` keyed 100 to 200 over the path's time: the position is the sum | 1e-6 |

## Open issues

- Whether `additive` should also rotate the offset by the node's own rotation.

## References

- SREP 0; the `animate/@additive` attribute; the engine README on motion paths.
- NOLN motion research, item E7 (internal).

## History

- 2026-10-05: first draft.
