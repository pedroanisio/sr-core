# scene-render 1.1 — normative spatial conventions

Status: **normative for every scene-render 1.1 implementation** (Rust is the only active one, SREP 25), adopted by
SREP 7. Where the XSD is silent, this document fills the gap; where it speaks, it restates it.

The XSD header already fixes the 2D conventions ("space: 2D pixels, origin top-left, +x right, +y down;
angles: degrees, positive = clockwise on screen"). The 3D rules below adopt definitions D1–D4, because they
extend the schema's 2D space into depth without introducing a second coordinate system. References of the
form Dn are to the numbered definitions in [DEFINITIONS.md](DEFINITIONS.md).

**Precedence.**
1. The XSD and its Schematron rules.
2. This document. Where a §5 ruling and a definition differ, the ruling applies.
3. `DEFINITIONS.md`.
4. For anything still unstated, the reference implementation's behaviour (SREP 0, Baseline).

Conformance is checked by `run.py` in this directory against the cases in `cases/`. §4 lists which rules
have cases. The rules without one (2.7, and the §5 rulings other than 5.14) are checked by each engine's own
tests until cases are added. Changes to these conventions, and to `DEFINITIONS.md`, go through an SREP
(`../srep/srep-0000.md`).

## 1. 2D node transform (all nodes with `transformAttributes`)

1.1 `x`, `y` place the node's **anchor point** in the parent's space. The node's local-to-parent matrix is

    M = T(x, y) · R(rotation) · Skew(skewX, skewY) · S(scaleX, scaleY) · T(−anchorX, −anchorY)

    so the local point (anchorX, anchorY) lands exactly on (x, y), and rotation and scale pivot about it.
    (D23; the After Effects convention.)

1.2 `anchorX`/`anchorY` are `lengthType`: a bare number is local pixels; `%` is a percentage of the
    **parent** box (as for every other `lengthType`, per the XSD header); `vw`/`vh`/`vmin`/`vmax` refer to the
    output frame. Anchors are never normalised fractions.

1.3 `rotation` is in degrees, positive clockwise on screen (+y is down).

1.4 **Colour literals** (`#RRGGBB[AA]`, `rgb()`, tokens resolving to them) are display sRGB-encoded, whatever
    the scene's working colour space: a renderer decodes them with the sRGB transfer function (and converts
    primaries if the working space is not sRGB-based) before compositing. A colour therefore displays as
    written in every working space; `#808080` in a `linear-srgb` scene still outputs code value 128.
    (The XSD's "straight alpha in the working space" refers to how alpha is stored, not to how literals are read.)

## 2. 3D scene space (`object3D`, `camera`, `light`, 2.5D layers)

2.1 **Axes and origin.** Scene space is the composition's pixel space extended into depth: origin at the
    frame's **top-left corner on the plane z = 0**, **+x right, +y down, +z away from the viewer**.
    One scene unit is one pixel. Physical quantities (light falloff, depth of field, thickness) use
    `physics/@pixelsPerMeter` (default 100) units per metre.

2.2 **Implicit camera.** When no `<camera>` is active, the camera sits at
    (W/2, H/2, −(W/2)/tan(fov/2)) with a **horizontal** fov of **60°**, looks along +z with +y down in the
    image, so the plane z = 0 maps onto the frame pixel for pixel.

2.3 **Explicit cameras.** A `<camera>`'s `x`, `y`, `z` are **absolute** scene positions (default 0, 0, 0 —
    the frame's top-left corner). They are not offsets from the implicit camera.
    `fov` is horizontal; with `focalLength`, fov = 2·atan(sensorWidth / (2·focalLength)) (sensorWidth default 36).
    An explicit camera has no implied distance. With `z` omitted it sits on the plane z = 0, so 2D layers and
    objects at z = 0 are at zero depth and are not seen. Give `z` explicitly: −(W/2)/tan(fov/2) reproduces the
    implicit camera's distance.

2.4 **Orientation.** At yaw = pitch = roll = 0 a camera (or light) looks along +z with +y down in the image.
    R = R_yaw · R_pitch · R_roll (roll applied first, in the camera's own frame). Positive yaw turns the view
    toward +x (right); positive pitch toward −y (up); positive roll turns the **camera** clockwise about its
    view axis (its right edge dips toward +y), so the image content appears to rotate counter-clockwise.

2.5 **object3D transform.** M = T(x, y, z) · R_z(rotation) · R_y(rotationY) · R_x(rotationX) · S(scaleX, scaleY, scaleZ),
    in scene space, after the `parent` chain. Primitives are centred on their origin; a `plane` faces the
    camera (its normal is −z). The rotations are right-handed about the scene axes: positive `rotationY` turns
    an object's right edge toward the viewer (−z), and positive `rotationX` turns its top edge toward the
    viewer. 2.5D layers turn the other way (5.14).

2.6 **Imported models.** Every mesh format is treated as Y-up metres (glTF/GLB, OBJ, PLY, STL, FBX after its
    own conversion, USD/USDZ) and enters scene space by a 180° turn about x and a scale of `pixelsPerMeter`
    (default 100): a model point (gx, gy, gz) becomes (100·gx, −100·gy, −100·gz) before the object3D transform.
    A model therefore appears upright and facing the implicit camera with `scaleX/Y/Z = 1`. Z-up sources
    (USD with upAxis Z) are first turned to Y-up. Gaussian-splat files use COLMAP's y-down, z-forward axes,
    which already match scene space, and are only scaled by `pixelsPerMeter`.

2.7 **Lights** use the same space: point, spot and area positions are scene coordinates; orientation follows 2.4.

## 3. Open questions (not normative yet)

- **Default position of an explicit camera** (2.3). Defaulting an omitted `z` to the implicit camera's distance
  would make `<camera/>` useful. It would also change what existing documents that rely on z = 0 render, so it
  is left for an SREP.

## 4. Cases

| Case | Rule | What is measured |
|---|---|---|
| `a1-anchor-translate` | 1.1 | red rect centre lands on (x, y) |
| `a2-anchor-rotate` | 1.1, 1.3 | rotation pivots about the anchor; the anchor is off-centre, so the sign of the rotation shows |
| `a3-anchor-scale` | 1.1 | scale pivots about the anchor (two anchors) |
| `a4-anchor-percent` | 1.2 | percent anchors refer to the parent box |
| `c1-colour-linear` | 1.4 | hex colours display as written in a linear working space |
| `b1-implicit-camera` | 2.1, 2.2 | z = 0 maps pixel for pixel; +y is down |
| `b2-depth` | 2.1, 2.2 | +z is away (smaller, closer to centre) |
| `b3-explicit-camera` | 2.3 | camera x/y/z are absolute |
| `b4-yaw-pitch`, `b4b-pitch` | 2.4 | positive yaw looks right, positive pitch looks up |
| `b6-roll` | 2.4 | positive roll: camera turns clockwise, content counter-clockwise |
| `b5-gltf` | 2.6 | glTF up is screen up and +X is screen right; 1 m = 100 px; single-sided faces are culled from behind |
| `b7-yaw-pitch-combined` | 2.4 | yaw and pitch together, in the order R_yaw · R_pitch |
| `b8-focal-length` | 2.3 | `focalLength` on the default 36 mm sensor gives the horizontal fov |
| `d1-object3d-rotation-order` | 2.5 | `rotationX` applies before `rotation` (the order of M) |
| `d3-object3d-rotation-y` | 2.5 | positive `rotationY` on an object3D is right-handed (right edge toward the viewer) |
| `d2-layer-rotation-y` | 5.14 | positive `rotationY` on a 2.5D layer turns its right edge away |

## 5. Rulings where the XSD is silent (decided 2026-09-29)

Where the XSD and §1–2 say nothing, these rules are normative. The order of sources: (a) the C renderer's
numbered definitions (Dn, including the D9 table) wherever they define the behaviour; (b) the W3C / After Effects precedent;
(c) otherwise the behaviour of existing content (the Python renderer's). Each rule names its source.

5.1 **Expressions** (extends D25). A program is zero or more statements, each a declaration (`var`, `let`,
    `const`) or an assignment `name = expr`, then one expression, separated by `;` or line breaks. Assigning a
    name that is not declared declares it (as `let`). Arrays of numbers and subscripts (`[a, b, c][index]`) are
    expressions; a subscript outside the array is `undefined`. A document is never rejected for this.

5.2 **`object3D/@instances`**. N copies, each evaluated with `index` = 0 … N − 1 and `count` = N; every property
    (not only the transform) may differ by `index`. There is no implicit layout: copies whose transforms are
    equal coincide.

5.3 **Parenting to a camera or light.** An `object3D` whose `parent` is a camera or light inherits its full 3D
    world transform (D23), not its 2D position.

5.4 **Parented cameras and lights.** With `parent` or `transformConstraint type="parent"`, a camera's or light's
    `x`, `y`, `z`, `yaw`, `pitch`, `roll` are in the parent's frame; 2.3 (absolute positions) applies to
    unparented ones. The frame offset of 2.1 is applied once, at the root of the chain.

5.5 **Dome environment** (D5.1). The equirectangular image's centre column is +z; `yaw`, `pitch`, `roll` of the
    dome turn the environment by 2.4's rules. 8-bit images are sRGB-decoded. The visible sky keeps the source's
    resolution (at least 2048 px wide when the source is). A dome is visible with or without an explicit camera.

5.6 **Effects composited with the original.** `compositeOriginal` defaults to `behind`: drop shadow, glow and
    similar effects go beneath the unchanged content (`on-top` above it, `none` the effect alone); interior styles
    (inner shadow, inner glow, inside strokes, inner bevel) are drawn over it. Glow is a bloom of the pixels above
    its `threshold` (working-space luminance, D9) added over the content, as in the C renderer. Adjustment layers: backdrop + (effect − backdrop) ·
    coverage (D17).

5.7 **Blur radius** (D9). `radius` of the blur effect is the Gaussian standard deviation; a drop shadow's
    softness radius is twice it. Samples outside the effect's input (for an adjustment layer, outside the frame)
    are transparent, never clamped to the edge.

5.8 **Vignette** (D9). Darkening 1 − `amount` · smoothstep(r₀, r₀ + `softness`, r), r the distance from the frame
    centre over the half diagonal, r₀ = `radius` / half diagonal. Absent attributes take the XSD's effect defaults.

5.9 **Force fields** (D8). Accelerations in m/s² with +y up, radius in metres; a positive radial strength
    attracts.

5.10 **Cloth soft bodies** (c). A lattice of (rows + 1) × (cols + 1) points; structural springs at the body's
     stiffness k, shear springs at 0.15 k, bend springs at 0.02 k.

5.11 **Text-animator presets** (c). `@preset` expands to the animators of the Python renderer's preset table
     (DEFINITIONS.md P1), which is the documentation the XSD refers to.

5.12 **Caption presets and karaoke** (c). Default caption style, anchor and fill model are the Python renderer's
     (DEFINITIONS.md P2): karaoke lights whole words with a cross-fade.

5.13 **Blending against the background** (b, After Effects). The composition composites on transparency; the
     project background is added last, beneath everything. `behind`, `subtract`, stencils and silhouettes act on
     the layers only. Blend formulas and luminance weights are D14's (W3C, Lum = 0.3 R + 0.59 G + 0.11 B).

5.14 **2.5D layer rotation** (b, After Effects). For flat layers (`threeD="true"` on 2D nodes), `rotationY` > 0
     turns the right edge away from the viewer and `rotationX` > 0 turns the top edge away. This is deliberately
     the opposite sense to object3D (2.5). Layer rotations follow the compositing precedent they come from,
     while object3D rotations follow the right-handed scene axes that meshes and glTF use. Cases d2 and d3
     check both.

5.15 **Mask feather and combining** (D16). Feather is a Gaussian blur with standard deviation `feather`; `add`
     combines as a + m − a·m; polygon and star vertices lie on the ellipse inscribed in the box, from the top,
     clockwise; a mask star's `innerRadius` is a fraction of that ellipse (0.5 when absent). Shapes follow the same
     polygon/star rule, with `innerRadius` in units (D27).

5.16 **Media end and `freezeAt`** (D9). A clip that does not loop ends when its media runs out. `freezeAt` holds
     that source time for the node's whole window.

5.17 **Transitions** (D19). The transition types, their coordinates and progress are D19's. Types D19 does not
     define (zoom, spin, whip-pan, blinds, blur, glitch, pixelize, stripe, squash, shuffle, light-leak, morph, flip,
     cube, page-curl, film-roll, carousel), their `param` children and the motion blur of moving transitions
     (`motionBlur`, default true) are the Python renderer's (c).

5.18 **Generators, gradients, chromatic aberration** (c). Generator patterns (checker phase, stripe period, grid
     phase, gradient interpolation, noise kinds), radial-gradient `aspect` (stretches x), linear-gradient
     rotation pivot (the box centre), mesh-gradient interpolation and chromatic-aberration `amount` (pixels of
     shift at the farthest corner of the effect's input, measured from its centre: the node's geometric box
     (for a group, the union of its own box and its sized descendants' boxes; never the bounds of drawn pixels),
     the frame for an adjustment layer; samples outside the input are transparent) are the Python renderer's.

5.19 **Seeded randomness** (D24). Noise is D24's N(seed, channel, x); `wiggle`, `noise`, grain and every other
     seeded function draw from it or from splitmix64 of (seed, channel, index) as D24 defines, never from a
     library generator.

5.20 **3D defaults** (c). Without `<lights>`, the default rig of the Python renderer applies (ambient 0.35 and a
     key light, plus its default environment); the torus tube radius defaults to the Python renderer's. An ambient
     light lights dielectrics diffusely only (albedo × radiance) and is reflected by metals as a uniform environment
     of its radiance, in proportion to metalness.

5.21 **Stroke start** (b, SVG 2). A closed ellipse starts its path (trim, dash phase) at 3 o'clock, a rect (and a
     rounded rect) at its top-left corner (x + rx, y for rounded corners); both run clockwise on screen.

5.22 **Validation.** Implementations validate against the same XSD and Schematron, the canonical
     `schema/scene-render.xsd` and `schema/scene-render.sch`; a document that fails is reported with every problem, and an implementation may
     offer a lenient mode but defaults to validating.

5.23 **Text-animator units** (b). An animator's `scale`, `scaleX`, `scaleY` are factors, as on nodes (1 = unchanged);
     `tracking`, on animators and text styles alike, is in thousandths of an em (After Effects).

5.24 **Transmission** (schema editor's decision). A transmissive 3D surface refracts everything behind it in paint
     order: the 3D scene and the 2D layers painted before the 3D content, as one composite; it is an opaque layer
     over what it refracts. Clear glass keeps the colour of what it refracts, less its Fresnel reflection.
