---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart); read from the Rust engine's sampler code, not yet measured"
  date: "2026-10-05"
---

```
SREP:            0
Title:           Add a bicubic resampling filter for magnified layers
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Standards
Created:         2026-10-05
Schema-Version:  1.1
```

# SREP 0 (draft) — Add a bicubic resampling filter for magnified layers

## Abstract

A layer that is drawn larger than its source (scaled above 1, or under a camera push-in) is magnified with
bilinear filtering, which softens it. `layer` gains an optional `resample` attribute with the values `linear` (the
default, as today), `bicubic` (Catmull-Rom) and `mitchell` (Mitchell–Netravali, B = C = 1/3). The new filters apply only
where the layer is magnified; where it is minified every layer keeps trilinear mip filtering. A document without
`resample` renders byte for byte as before.

## Motivation

The Rust engine samples every image layer with hardware filtering: linear magnification and minification, linear mip
selection (the sampler of the layer pass; the mip chain is built on the CPU). Magnification is therefore bilinear on mip
level 0. A production whose background plates are 1672 × 941 and are drawn at about 1.15 times that size, and more on
camera push-ins, shows the softening of bilinear magnification on every frame.

**What is not measured yet.** This draft is written from reading the sampler configuration, not from a comparison of
renders. Before Review it needs one: the same plate magnified by 1.15 with `linear`, `bicubic` and `mitchell`, each compared
with a reference resampling of the source to the target size (a high-quality offline resampler), reported as PSNR and as
the difference image, together with the render time of each.

## Specification

### Syntax

```xml
<!-- layerType gains -->
<xs:attribute name="resample" default="linear">
  <xs:annotation><xs:documentation>The filter used where the layer is drawn larger than its source. linear: bilinear (the
  default). bicubic: Catmull-Rom, with a clamp to the range of the four nearest texels. mitchell: Mitchell-Netravali with
  B = C = 1/3, with the same clamp. Where the layer is drawn at or below its source size every layer uses trilinear mip
  filtering whatever @resample says.</xs:documentation></xs:annotation>
  <xs:simpleType><xs:restriction base="xs:string">
    <xs:enumeration value="linear"/><xs:enumeration value="bicubic"/><xs:enumeration value="mitchell"/>
  </xs:restriction></xs:simpleType>
</xs:attribute>
```

A new attribute with a neutral default, accepted in every version. No Schematron rules.

### Semantics

**1. When it applies.** A layer pixel is *magnified* when the source's texel footprint on screen is larger than a pixel on
both axes (the level of detail of the sample, computed from the screen-space derivatives of the texture coordinates, is
at most 0). For a magnified sample with `resample="linear"`, the sample is the bilinear interpolation of the four nearest
texels, as before. For any other sample, the sample is the trilinear (linear in level and in position) filter, as before.

**2. Bicubic.** For a magnified sample at texel-space position `x` (texel centres at half-integers), let `i = floor(x − 0.5)`
and `t = x − 0.5 − i`. The sample is `Σ_j Σ_k w_j(t_x) · w_k(t_y) · T(i_x + j − 1, i_y + k − 1)` for `j, k ∈ {0, 1, 2, 3}`, over
texels `T` of the base level, in the engine's working colour space with premultiplied alpha, with texel coordinates outside
the image clamped to the edge. For `bicubic` the weights are Catmull-Rom's:

- `w₀(t) = (−t³ + 2t² − t) / 2`
- `w₁(t) = (3t³ − 5t² + 2) / 2`
- `w₂(t) = (−3t³ + 4t² + t) / 2`
- `w₃(t) = (t³ − t²) / 2`

For `mitchell` (B = C = 1/3):

- the weights are the Mitchell–Netravali cubic
  `k(s) = (1/6)·{ (12 − 9B − 6C)|s|³ + (−18 + 12B + 6C)|s|² + (6 − 2B) for |s| < 1;  (−B − 6C)|s|³ + (6B + 30C)|s|² + (−12B − 48C)|s| + (8B + 24C) for 1 ≤ |s| < 2;  0 otherwise }`,
  evaluated at `s = t + 1 − j` for `w_j(t)`.

**3. Anti-ringing.** The result of `bicubic` and `mitchell` MUST be clamped, per channel, to the minimum and maximum of the
four texels nearest the sample (the 2 × 2 neighbourhood bilinear filtering would use).

**4. Exactness.** An engine MAY evaluate the filter with fewer texture fetches (for example, nine bilinear fetches for
Catmull-Rom) if the result matches the weights above within 1/512 of full scale.

### Defaults and the neutral case

`resample` defaults to `linear`; every document that does not set it renders as before. A `layer` that sets `bicubic` or
`mitchell` differs from the baseline only where it is magnified.

## Rationale

- **Magnification only.** Minification is already filtered with mip chains; a cubic filter there adds cost for little gain,
  and changing it would alter every existing scene.
- **Catmull-Rom first.** It interpolates the texels (a sample at a texel centre equals the texel), is sharp, and its nine-tap
  form on bilinear hardware is cheap. Mitchell is the softer choice that avoids Catmull-Rom's halos.
- **Not Lanczos-3.** It needs 36 taps, rings visibly, and offers nothing measurable at magnifications near 1.15.
- **An attribute, not a new default.** Making bicubic the default for scale above 1 changes the pixels of every scene that
  magnifies, which is a behaviour change needing a version gate and a corpus-wide re-baseline.

## Rejected alternatives

- **A project-wide `imageResample`.** Possible later; a per-layer attribute is the minimum and is what a plate needs.
- **Anisotropic filtering controls.** A different problem (oblique minification).

## Backwards compatibility

- **Class: Added, MINOR in effect, accepted in every version** (neutral default).
- No document changes validity; none changes pixels unless it sets `resample`.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending (approved for implementation by the maintainers' coordinator; not started) | a branch in the layer fragment shader, one flag in the draw parameters (the padding-word trick, so the layout is unchanged), the schema attribute; applies to layers whose asset is an image or video | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-resample-default` | a 2 × 2 checker magnified 4 times with no attribute and with `resample="linear"`: identical pictures | 0 |
| `srep-NNNN-resample-bicubic` | the same with `bicubic`: a pixel on a texel centre equals the texel; the value half way between two texels of a 1-D ramp matches the Catmull-Rom weights; no value outside the texels' range | 2 levels |
| `srep-NNNN-resample-mitchell` | the same with `mitchell`: the centre value is (1·a + 16·b + 1·c)/18 for neighbouring texels a, b, c | 2 levels |
| `srep-NNNN-resample-minified` | the layer drawn at half size with `bicubic`: identical to `linear` | 0 |

## Open issues

- The measurement named under Motivation.
- Whether `video` layers (a different sampler) are covered in the first implementation.
- Filtering in the working colour space (linear light) can ring more than in encoded values; the anti-ring clamp bounds it.

## References

- Mitchell and Netravali, "Reconstruction filters in computer graphics", SIGGRAPH 1988 (the B, C family); Catmull and Rom
  (1974) as the B = 0, C = 1/2 member. Not re-read for this draft: the formulas above are the standard ones and are to be
  checked by the conformance cases before Review.
- SREP 0, SREP 4.

## History

- 2026-10-05: first draft.
