---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart), from the Rust engine's commits and the G2 lab log"
  date: "2026-10-05"
---

```
SREP:            0
Title:           Clarify six schema annotations (documentation only)
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Standards
Created:         2026-10-05
Schema-Version:  1.1 (documentation only)
```

# SREP 0 (draft) — Clarify six schema annotations (documentation only)

## Abstract

Six `xs:documentation` strings in `scene-render.xsd` were silent, ambiguous or contradicted by the behaviour the
baseline engine has had all along. They are rewritten to say what the engine does. No declaration, default or rule
changes, and no picture changes. SREP 5 is the precedent for a documentation-only change: it gets an SREP and a PATCH
entry in `schema/CHANGELOG.md`.

## Motivation

Each wording below was found wrong or missing by the G2 lab or a style study, by a reader who followed the schema and got
a different result from the engine.

## Specification

The documentation of these declarations changes. With documentation removed the file is identical, in canonical XML, to
its previous version.

1. **`colorType`.** Adds: "The shorthand #RGB and #RGBA is not accepted." The pattern already rejects it; authors wrote
   `#abc` and got an error that did not say why.
2. **`expressionType`.** Replaces "Computes @property every frame" with: "Computes @property every frame; @property names an
   attribute the element's own type declares (or position, scale, anchor, skew): a text layer's text, for one, is not an
   animatable property." Evidence: an expression on a text layer's `text` is rejected when compiled for rendering.
3. **`radialGradientType/@aspect`.** Adds: "Multiplier on the gradient's x extent about its centre, applied after the units
   are mapped. 1 is no stretch. With units="object" the gradient already follows the painted box, so a radial gradient on a
   wide shape is an ellipse without any aspect; > 1 widens it further, < 1 narrows it."
4. **`geoLayerType`.** "lines stroked (drawn on by @progress)" gains "; polygon outlines are always drawn whole". `progress`
   trims lines only.
5. **`textAnimatorType/@presetStart`.** Adds: "Time on the layer's parent timeline (composition time for a top-level layer), not
   an offset from the layer's start; when absent the preset starts at the layer's own start."
6. **`camera/@fov`.** Adds: "Horizontal field of view in degrees, across the frame width: the focal distance in pixels is
   (frame width / 2) / tan(fov / 2), whatever the frame's height, so a portrait frame sees a narrower vertical angle than a
   landscape one." This is the convention the compatibility kit already uses (CONVENTIONS, camera).

Not in this SREP: the documentation of `safeAreaForce`, `presetEase`, the effect types (`halftone`, `selective-color`)
and `group/@collapse`. Those travel with the SREPs that define them (safe-area enforcement, preset ease, effect parameter
meanings, and the inert-attribute amendment).

### Defaults and the neutral case

Documentation only. Every document validates and renders as before.

## Rationale

SREP 0 requires the Specification to say what the picture is. These strings are normative text in the generated reference;
where they disagree with the engine, the engine is the baseline (SREP 25), so the text is corrected.

## Rejected alternatives

- **Leave them as errata in the README.** The schema's annotations are what the generated reference shows.

## Backwards compatibility

Documentation only; PATCH. No document changes validity or rendering.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | implemented in the engine's copy of the schema: commit `7eeaf35` (and the annotation edits in the same series) | none | |

## Conformance

None: documentation only. Where a sentence states a behaviour (`fov`, `presetStart`), the cases of the SREPs that define
that behaviour cover it; `fov` is covered by the kit's cases b8 and b3 at `hfov` 60.

## Open issues

- None.

## References

- SREP 0, SREP 4, SREP 5 (documentation-only precedent); the compatibility kit's CONVENTIONS.

## History

- 2026-10-05: first draft, after the engine's edits landed.
