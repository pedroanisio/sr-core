---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart), from the Rust engine's 3D shader and the NOLN glTF/FBX assessment"
  date: "2026-10-05"
---

```
SREP:            0
Title:           Add procedural unevenness to materials (a clay finish)
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Standards
Created:         2026-10-05
Schema-Version:  1.2
```

# SREP 0 (draft) — Add procedural unevenness to materials (a clay finish)

## Abstract

A document `material` is a glTF metallic-roughness material with the KHR extensions. A high roughness and a sheen make a
surface look matte and soft; nothing makes it look hand-made. `material` gains three optional attributes,
`unevenness`, `unevennessScale` and `unevennessSeed`, that perturb the shading normal and the roughness with a smooth
procedural noise fixed to the object, so that any mesh, imported or built in, can take a clay finish from its material
alone. With `unevenness` 0, the default, a material shades exactly as before.

## Motivation

The NOLN music video wants an imported knight (a chess-set mesh) to read as hand-pressed clay under the same lights as the
hand-made marionette. The engine's assessment of glTF and FBX use for the video (§A.1) finds what the baseline gives:
roughness, sheen and normal maps. Roughness 0.85 with a sheen makes a soft matte surface, but a surface whose normal and
roughness are constant across it still looks machine-smooth. The only unevenness in the baseline is `fingerprints` and `boil`
on `primitive="clay"` blob objects, which displace the blobs' own surface and do not apply to imported meshes. A normal map
could carry the unevenness, but a material's maps are files, so each look needs an authored image and a UV layout.

## Specification

### Syntax

```xml
<!-- materialType gains -->
<xs:attribute name="unevenness" type="unitDecimal" default="0">
  <xs:annotation><xs:documentation>Amount of procedural surface unevenness: a smooth noise fixed to the object that tilts the
  shading normal and varies the roughness, for a hand-made (clay) look. 0 is off.</xs:documentation></xs:annotation>
</xs:attribute>
<xs:attribute name="unevennessScale" type="positiveDecimal" default="8">
  <xs:annotation><xs:documentation>Size of the largest features of the unevenness, in scene units (pixels at the object's
  scale).</xs:documentation></xs:annotation>
</xs:attribute>
<xs:attribute name="unevennessSeed" type="xs:nonNegativeInteger" default="0"/>
```

New attributes with neutral defaults, accepted in every version (SREP 0, Versioning). No Schematron rules.

### Semantics

Let `p` be the position of the shaded point relative to the object's origin, measured along the object's own axes in scene
units (the uniform scale of the object's transform, including the unit conversion of an imported model, is applied, so the
pattern moves, turns and keeps its feature size with the object), `s = unevennessScale`, `A = unevenness` and `σ =
unevennessSeed` (an unsigned 32-bit integer; larger values wrap).

1. **Lattice values.** The 32-bit PCG step is `pcg(x)`: `state = x · 747796405 + 2891336453`,
   `word = ((state ≫ ((state ≫ 28) + 4)) ⊕ state) · 277803737`, `pcg(x) = (word ≫ 22) ⊕ word` (all arithmetic modulo 2³²,
   shifts logical). For integers `(i, j, k)`, the hash is `H(i, j, k, c) = pcg(pcg(pcg(pcg(c) ⊕ k) ⊕ j) ⊕ i)`, with the
   coordinates as two's-complement 32-bit integers. The lattice value of octave `o` is `v(i, j, k, o) = f32(H(i, j, k,
   σ + o)) · 2⁻³¹ − 1`, with the `u32` converted to single precision by rounding to nearest. The integer part is exact on
   every adapter; the rest is single-precision arithmetic.
2. **Value noise.** `V(q, o)` is the trilinear interpolation of the eight surrounding lattice values with the weight
   `t² (3 − 2t)` on each fractional part.
3. **Height.** Let `f` be the screen footprint of a pixel in scene units: the length of the vector `|∂p/∂X| + |∂p/∂Y|`
   (componentwise absolute values of the position's derivatives along the screen axes, as `fwidth` computes them). The octave
   amplitudes fade with it: `a_o = clamp((s / 2^o) / f − 1, 0, 1)`, which is 1 for features of 2 or more pixels, 0 for features
   of 1 pixel or less, and linear between, so that detail finer than the screen can show disappears instead of aliasing.
   Then `h(p) = (a₀·V(p/s, 0) + a₁·V(2p/s, 1)/2 + a₂·V(4p/s, 2)/4) / 1.75`, in `[-1, 1]`. The amplitudes `a_o` are those of the
   shaded pixel and are used for all seven evaluations of `h` in item 4. An engine whose derivatives are not those of a
   2 × 2 pixel quad MUST approximate `f` within a factor of 1.5.
4. **Shading normal.** With `e = s/32`, `g_x = (h(p + e·x̂) − h(p − e·x̂)) · s/(2e)` and `g_y`, `g_z` likewise along the object's
   `y` and `z` axes, let `w = g_x·a_x + g_y·a_y + g_z·a_z` where `a_x, a_y, a_z` are the unit vectors of the object's axes in world
   space. The shading normal `n` (after any normal map) becomes `normalize(n − 0.5·A · (w − (w · n) n))`, and the tangent
   frame is re-orthogonalised to it.
5. **Roughness.** `r' = clamp(r + 0.25·A·h(p), 0.03, 1)`, where `r` is the roughness after any map.
6. **Where it applies.** To every surface drawn with the material. A material whose `unlit` is true shows no unevenness.
   An engine that cannot apply it (a renderer without per-point shading) MUST say so.

### Defaults and the neutral case

`unevenness` 0 shades as the baseline: items 4 and 5 are the identity for `A = 0`.

## Rationale

- **In the material.** The look belongs to a material: it follows the material onto any mesh (`@material`,
  `@materialOverride` of the model-select draft), and it needs no authored texture or UVs.
- **Object space.** A knight rising from the pit must not swim through a fixed noise; object space keeps the finish on the clay. Scene
  units, with the object's uniform scale applied, keep `unevennessScale` meaningful for models authored in metres.
- **A fully specified noise.** Integer hash and trilinear value noise are exactly reproducible on every adapter; the engine's
  other noise (Perlin) is specified through its own lattice and is not a 3D shading primitive.
- **Normal and roughness only.** Displacing geometry would change silhouettes and shadows and needs a tessellated mesh; the
  baseline's `displacementScale` already exists for that.

## Rejected alternatives

- **A `finish="clay"` preset.** A preset hides the numbers; the attributes expose what it is and compose with roughness and sheen.
- **World-space noise.** The pattern would swim as the object moves.
- **Procedural noise as a generator-asset normal map.** Needs a UV layout.

## Backwards compatibility

Class: Added, accepted in every version. No valid document changes validity or rendering.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | three material uniform and shader (normal and roughness), the object-space position as a varying; not applied by the optional path tracer (reported) | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-unevenness-off` | a sphere with `unevenness` 0 and absent: identical pixels | 0 |
| `srep-NNNN-unevenness-varies` | `unevenness` 0.8 on a smooth sphere: the luminance varies across the lit face where it did not | variance above a stated floor |
| `srep-NNNN-unevenness-sticks` | the same object turned about its axis: the pattern turns with it | 2 px |
| `srep-NNNN-unevenness-fade` | `unevennessScale` 1 on a sphere seen at about 1 px per unit: no pixel changes by more than 0.02 against `unevenness` 0; at scale 16 the change exceeds 0.15 | 0.02 |
| `srep-NNNN-unevenness-seed` | two seeds give different patterns; the same seed repeats exactly | exact |

## Open issues

- Whether the noise should also be offered in world space, for backdrops.
- The strengths 0.5 and 0.25 of items 4 and 5 are chosen for a visible but subtle effect at `A` = 0.2 to 0.4; they are not derived.
- The path tracer.
- Whether the fade should use the mean rather than the sum of the two derivative magnitudes; the engine uses the vector length of `fwidth`.

## References

- SREP 0; the model-select draft; the glTF 2.0 material model (normal and roughness).
- O'Neill, "PCG: A Family of Simple Fast Space-Efficient Statistically Good Algorithms for Random Number Generation" (2014): the
  PCG family, whose 32-bit output permutation (xorshift-right by `(state ≫ 28) + 4`, multiply, xorshift by 22) item 1 uses. The exact constants
  of item 1 were compared with the Rust engine's WGSL on 2026-10-05 and are identical; they were **not** checked against O'Neill's
  source in this session (the engine's constants are the ones in common use for this 32-bit variant).
- Jarzynski and Olano, "Hash Functions for GPU Rendering", Journal of Computer Graphics Techniques 9(3), 2020, <https://jcgt.org/published/0009/03/02/>.
  The paper's Table 1 lists the hash `pcg` with the reference O'Neill 2014a among the hashes it tests; read from the paper's PDF text on 2026-10-05. The constants of item 1 do **not** appear in the text extracted from
  the paper (its own listings are `pcg3d` and `pcg4d`, with other constants), so the paper is cited for the choice of family, not for the constants.

## History

- 2026-10-05: first draft.
