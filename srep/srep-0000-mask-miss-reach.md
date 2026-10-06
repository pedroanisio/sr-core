```
SREP:            0
Title:           Amend SREP 34: a feathered mask that reaches its node
Author:          scene-render maintainers (drafted by gap-A)
Status:          Draft
Type:            Standards
Created:         2026-10-06
Schema-Version:  1.3
Requires:        34
```

# SREP 0 (draft) — Amend SREP 34: a feathered mask that reaches its node

## Abstract

`MASK-MISS` ([SREP 34](srep-0034.md)) warns when a rect or ellipse mask's box lies wholly outside the box of the node
it masks. A mask with `feather` or `expansion` reaches beyond its box. When it reaches the node, the node does not
vanish, yet the warning still fires.

This amendment counts the reach: no `MASK-MISS` while the box, grown by `feather` and `expansion`, still meets the
node's box.

## Motivation

- SREP 34's condition looks at the mask's box only. A rect mask 10 px outside a node with `feather="20"` softens into
  the node's edge and leaves part of it visible.
- The reference already applies this amendment (`gap/srep-34-inert-amendment`, `masks_that_miss`): it reports only
  when the gap is at least `feather` + `expansion`, each counted when positive.

## Specification

### Semantics

SREP 34's `MASK-MISS` condition gains: "… whose box lies entirely outside the box of the node it masks, in the node's
own coordinates, **by at least the mask's reach r = max(feather, 0) + max(expansion, 0)**". With x, y, w and h the
mask's box and W, H the node's box, the finding fires when

g = max(x − W, y − H, −(x + w), −(y + h)) ≥ r,

and `measured` is g. That is how far outside the box lies, as SREP 34's erratum of 2026-10-06 defines it.

### Defaults and the neutral case

A mask with neither attribute has r = 0: SREP 34 as accepted.

## Rationale

The warning is for a mask that leaves nothing of its node. A mask that reaches the node leaves something, so warning
about it is a false finding.

## Rejected alternatives

- **The feather alone.** `expansion` grows the shape before the feather, so it reaches just as far.

## Backwards compatibility

No validity or picture changes. Documents with a feathered or expanded mask just outside its node lose a false
warning.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | implemented on `gap/srep-34-inert-amendment` | none | |

## Conformance

| Case | Checks | Expected |
|---|---|---|
| `srep-NNNN-mask-miss-reach` | a rect mask 10 px outside its node; the same with `feather="20"`; with `expansion="15"`; with `expansion="10"` (it reaches exactly to the edge) | MASK-MISS with measured 10; none; none; MASK-MISS |

## Open issues

None.

## References

- [SREP 34](srep-0034.md), registry (`MASK-MISS`).

## History

- 2026-10-06: first draft.
- 2026-10-06: drafted with AI assistance (Claude Opus 5.5 via Claude Code (worker gap-A), from rs-scene-render's
  `masks_that_miss`). No statement here should be taken for granted without its definition or reference.
