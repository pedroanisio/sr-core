# scene-render definitions D1–D27, P1–P2

Normative through SREP 7. These are the numbered definitions that `CONVENTIONS.md` refers to as Dn, and the preset tables its rulings
5.11 and 5.12 refer to (P1, P2). Each gives
the meaning of attributes the XSD declares without defining, and keeps the declared default as the neutral case.
Where a ruling in `CONVENTIONS.md` §5 differs from a definition here, the ruling applies. The Rust engine's
behaviour overrules both while it is the only active engine ([SREP 25](../srep/srep-0025.md)).

The format's conventions apply throughout: 2D space in pixels with +y down and angles positive clockwise on
screen; physics in metres with +y up.

---

## D1. 3D space

**Definition.** 3D positions and sizes are in pixels. The 3D space extends
the 2D one: +x right, +y down, +z into the screen (away from the viewer),
origin at the frame's top-left corner on the plane z = 0. The system is
right-handed. A 2D node lies on the plane z = 0.

**Evidence.** The declared defaults only make sense in pixels: `object3D`
radius 50, box depth 10, camera `far` 10000, `focusDistance` 1000. In
metres these would be a 50 m sphere and a 10 km far plane. Keeping
2D x and y unchanged means a 3D scene and a 2D scene share coordinates.

**Precedent.** After Effects uses exactly this space for 3D layers.

## D2. Cameras

**Definitions.**

1. **Implicit camera.** When no camera is active, the view is a perspective
   camera at (W/2, H/2, −D) looking along +z with no roll, where
   D = (W/2) / tan(fov/2) and fov = 60°. The plane z = 0 then maps one to
   one onto the frame: a 2D node at z = 0 renders exactly as it does
   without 3D.
2. **`fov` is horizontal**, in degrees. The schema derives fov from
   `focalLength` and `sensorWidth`, a horizontal sensor dimension, so the
   angle it yields is horizontal: fov = 2·atan(sensorWidth / (2·focalLength)).
3. **Orientation.** With yaw = pitch = roll = 0 the camera looks along +z
   with +y down in the image. The camera turns by roll about its view axis,
   then pitch about its x axis, then yaw about the world y axis (applied to
   the camera: R = R_yaw · R_pitch · R_roll).
   - Positive yaw turns the view toward +x (right).
   - Positive pitch turns it toward −y (up).
   - Positive roll turns the **camera** clockwise about its view axis (its
     right edge dips toward +y), so the image content turns
     counter-clockwise on screen (CONVENTIONS 2.4).
4. **`target`.** When set, the camera looks at the named node's origin, and
   yaw and pitch are ignored. Roll still applies.
5. **Declared defaults.** A camera element's `x`, `y`, `z` default to 0,
   as declared, which places it at the frame's top-left corner. The
   implicit camera of (1) exists only when there is no camera element.
6. **`near`/`far`/`focusDistance`** are pixels along the view axis.
7. **`orthographic`.** Parallel projection along the view axis, where
   `orthoHeight` pixels of the scene fill the frame height.

## D3. 3D objects and 2.5D nodes

**Definitions.**

1. **Sizes and origins, in pixels.** Each primitive is centred on the
   node's origin:
   - `sphere`: radius `radius`.
   - `box`: `width` × `height` × `depth`.
   - `plane`: `width` × `height`, in the node's x-y plane, facing −z (the
     viewer).
   - `cylinder`, `cone` and `capsule`: along the node's y axis, with radius
     `radius` and length `height`.
   - `segments` is a quality hint for curved surfaces; the renderer's
     own tessellation is used, as `solverIterations` is a hint for physics.
   - `mesh`: the `<mesh>` asset named by `@mesh`, treated as Y-up metres
     (CONVENTIONS 2.6): a model point (gx, gy, gz) becomes
     (ppm·gx, −ppm·gy, −ppm·gz) with ppm = `physics/@pixelsPerMeter`
     (default 100), then the transform of item 2 applies. glTF and GLB are
     read (triangle primitives of the default scene with their node
     matrices, flat normals, TEXCOORD_0, `baseColorFactor`, metallic and
     roughness factors, `emissiveFactor`, `KHR_materials_unlit`); each
     primitive draws as its own object under the node's transform. An
     XML `material` replaces the file's materials. Other mesh formats,
     other primitive modes, Draco compression, glTF textures, skins,
     morph targets and animations are reported or not read.
2. **Transform.** Scale, then rotationX, then rotationY, then `rotation`
   (about z, clockwise on screen, like 2D rotation), then translation to
   (x, y, z): M = T · R_z · R_y · R_x · S. This is After Effects' order.
3. **2.5D nodes.** A 2D node with `threeD="true"` becomes a textured plane
   of its rendered content at (x, y, zDepth), turned by rotationX and
   rotationY about its anchor, and rendered with the 3D content.
4. **3D blocks.** Consecutive 3D nodes in document order form one block,
   rendered together with a shared depth buffer through the active camera.
   A 2D node between 3D nodes ends a block. Blocks composite in document
   order like any other nodes. This is After Effects' rule for 2D layers
   between 3D layers.

## D4. Lights

**Definitions.** Positions (x, y, z) are pixels in the D1 space.

1. **Direction.** Directional and spot lights point along +z at
   yaw = pitch = 0, turned by yaw and pitch exactly as a camera is (D2.3).
   Roll has no effect on a round spot.
2. **Intensity.** The effective intensity is `intensity` × 2^`exposure`.
3. **Attenuation** of point and spot lights at distance d:

   E(d) = I · min(1, (d₀ / d)^`falloff`) · W(d)

   - d₀ is 1 metre, i.e. `physics/@pixelsPerMeter` pixels (100 by
     default), so light and physics share one scale.
   - `falloff` 2 (the declared default) is the inverse-square law. The
     schema requires `falloff` > 0; within d₀ the attenuation is 1 whatever
     the exponent.
   - W(d) = (1 − (d/`range`)⁴)² for d < `range`, and 0 beyond it. With no
     `range`, W = 1.
4. **Spot cone.** `spotAngle` is the full cone angle. `innerConeAngle` is
   the full angle of full intensity (default: equal to `spotAngle`, a hard
   edge). Between them intensity follows smoothstep in the angle.
5. **`colorTemperature`** multiplies `color` by the sRGB colour of a black
   body at that temperature, normalised so its largest channel is 1.
6. **`dome`.** See D5.1.
7. **2D lighting.** An effect with `type="lighting"` and `lights` shades
   its node's content as the plane z = 0 facing the viewer (normal −z).
   The relief attribute tilts the normal from the alpha gradient. So one
   light set lights both 3D objects and 2D content.

## D5. 360°

**Definitions.**

1. **Environment.** A `<light type="dome" environment="ID"
   environmentVisible="true">` is the scene's 360° environment: an image or
   video asset in equirectangular layout, surrounding the camera at
   infinite distance, drawn behind all other content. Mapping:
   - The image centre column is the +z direction (forward); columns to its
     right are toward +x.
   - The top row is straight up (−y), the bottom row straight down.
   - The dome's yaw, pitch and roll turn the environment (D2.3
     conventions).
   - Where the environment is visible, it replaces `project/@background`.
2. **`mode="standard"`.** The output is the view through the active camera
   (D2): the environment, then 3D blocks. 2D nodes are drawn in screen
   space, as always.
3. **`mode="equirectangular"`.** The output is the full sphere around the
   active camera's position, in equirectangular layout, with longitude 0
   along the camera's forward direction. The environment and 3D blocks are
   rendered spherically.
   - 2D nodes are drawn directly on the equirectangular frame, in its pixel
     coordinates (x ↔ longitude, y ↔ latitude).
   - The project's width and height must be in a 2:1 ratio.
4. **`mode="viewport"`.** The composition is authored on the 360° canvas:
   an equirectangular frame of `scene360/@width` × `@height` (3840 × 1920
   by default), rendered as in (3) but at a fixed orientation: longitude
   0 along +z, turning with no camera, so that the camera's orientation
   applies once, to the view.
   - The output, of `project/@width` × `@height`, is the rectilinear view
     of that canvas through `scene360/@viewportCamera` (its yaw, pitch,
     roll and horizontal fov; the active camera when unset).
   - Content that must stay fixed on screen belongs in a `standard`-mode
     scene over the same environment.
5. **`scene360/@layout`.** Only `equirectangular` is defined here.
   Cubemap, EAC and fisheye layouts concern the output encoding and can be
   defined later without changing (1)–(4).
6. **Stereo.** `stereo="mono"` is defined here. Top-bottom and left-right
   stereo, with `interpupillary` in metres, need a stereo camera
   definition and are left for later.

**Evidence.** The dome light is the schema's only construct that places
an equirectangular image around the viewer, and it already has
`environmentVisible`. Definitions (2)–(4) give each declared mode a
distinct, non-overlapping meaning.

## D6. Deformers

**Scope.** A `<deform>` on a layer or shape applies its `<modifier>`
children in document order to the node's own rendered content, in the
node's local space before its transform.

**Node box.** The box a modifier refers to is:
- for a shape, its `width` × `height`;
- for a layer, its asset's size (image, generator, text box);
- for a group, its `width` × `height`, which the group must then have.

`centerX`/`centerY` default to the box centre. Every modifier's declared
`amount` default of 0 is the identity.

**Definitions** (angles in degrees, positive clockwise on screen):

- **`bend`.** Content on the +axis side of the line through the centre
  perpendicular to the axis is wrapped onto a circular arc of radius
  `radius` for an arc angle of `amount`. Content beyond the arc continues
  along the arc's end tangent, and content before the line is unchanged.
  `axis` is `x` or `y`, and positive `amount` bends clockwise.
- **`twist`.** A point at distance r < `radius` from the centre rotates
  about the centre by `amount` · (1 − r/`radius`)². Points beyond `radius`
  are unchanged.
- **`wave`.** The wave travels along `axis` (`x`: rightward, `y`:
  downward). Each point moves by

  `amount` · sin(2π · (s/`radius` − `frequency` · t) + `phase`)

  pixels, along the travel direction turned 90° counter-clockwise on
  screen. Here s is the coordinate along the travel direction measured
  from the node's origin (the wave ignores `centerX`/`centerY`), `radius`
  is the wavelength in pixels, `frequency` is
  cycles per second (the wave moves at `radius` × `frequency` px/s), and
  `phase` is in degrees.
- **`squash` / `stretch`.** With s = 1 + `amount`, `stretch` scales by s
  along `axis` and 1/s across it, about the centre; `squash` scales by 1/s
  along the axis and s across. Both preserve area.
- **`mesh-warp`.** `rows` × `cols` cells cover the node box, giving
  (rows+1) × (cols+1) points indexed from the top-left. A `<point row col
  x y>` moves that point by (x, y) pixels from its rest position, and
  unlisted points stay at rest. Each cell is split along its top-left to
  bottom-right diagonal into two triangles, each mapped affinely.
- **Other types** (`puppet`, `skin`, `bulge`, `pinch`, `spherize`,
  `ripple`, `turbulence`, `corner-pin`) are not defined here. `corner-pin`
  already has a definition in the schema.

**Evidence.** `warpPoint` `x`/`y` default to 0, which as absolute
positions would collapse every mesh point onto the origin. As offsets, 0
means no displacement.

## D7. Soft bodies on nodes

**Definition.** A `<softBody kind="jelly">` makes the node box a lattice of
(rows+1) × (cols+1) masses, with structural and diagonal springs. The
content is drawn through the lattice as in mesh-warp, and the lattice is
simulated in the scene's physics world (gravity, bounds, step).
- **`mass`** is the node's total mass in kilograms, shared equally among
  the lattice points.
- **`stiffness`** (N/m) applies to each spring. Converted through
  `pixelsPerMeter` as for constraints, the number carries over unchanged.
- **`damping`** is the fraction of critical damping, which is why the
  schema bounds it to [0, 1]: each spring's damping coefficient is
  `damping` × 2√(`stiffness` × m), with m the mass of one lattice point.
- **`pin`** fixes the named edge's points, or the four corners.
- `pressure`, `selfCollision`, `cloth` and `rope` are not defined here.

## D8. Force fields

**Definition.** Force fields are accelerations, like gravity, and act on
bodies independently of their mass. The name follows common usage in
animation tools.
- **`directional`:** acceleration (`forceX`, `forceY`) in m/s², +y up.
- **`radial`:** acceleration of magnitude `strength` · (1 − d/`radius`)^`falloff`
  toward (x, y), for d < `radius`. Positive `strength` attracts; `radius`
  is in metres, and (x, y) are composition pixels.
- **`vortex`:** the same magnitude, directed tangentially, clockwise on
  screen for positive `strength`.

## D10. The wave-warp effect

**Definition.** `<effect type="wave-warp">` displaces the content of the
node it is applied to exactly as the D6 wave does, with these attributes:
- `amount`: amplitude in pixels;
- `radius`: wavelength in pixels;
- `speed`: cycles per second;
- `angle`: the travel direction in degrees clockwise from +x.

The displacement is along the travel direction turned 90°
counter-clockwise on screen, and s is measured from the node's origin.
`frequency` would duplicate `speed` and must stay 1.

## D11. Materials

**Definition.** An `object3D` shades with its `material`'s glTF 2.0
metallic-roughness BRDF, as the glTF specification's Appendix B defines
it:
- α = `roughness`²;
- a GGX distribution;
- the height-correlated Smith visibility term;
- Schlick Fresnel with F₀ = mix(0.04, `baseColor`, `metallic`);
- a Lambertian diffuse term for c_diff = `baseColor` (1 − `metallic`),
  weighted by (1 − F).

**Lighting.**
- A punctual light (D4) of intensity E contributes π · f · E · (n·l), so
  a white dielectric facing a light of intensity 1 head-on returns about
  1 − F₀ plus its specular peak. The factor π keeps D4's relative
  intensities meaningful.
- An ambient light of intensity I adds I · c_diff.
- `emissive` × `emissiveStrength` adds light.
- Without a material, an object uses the declared defaults: white, not
  metallic, roughness 0.5.

**Unlit.** `unlit="true"` (KHR_materials_unlit) shows `baseColor` (times
`baseColorMap`) with no lighting, emission or ambient term.

**Scope of this definition.** `opacity` 1, `alphaMode` opaque, and none
of the KHR extensions other than unlit, nor maps other than `baseColorMap`
and `emissiveMap`.
Those two maps use each primitive's texture coordinates:
- sphere: equirectangular, longitude 0 toward −z (the viewer);
- box faces and plane: each face spans the whole image, top-left at the
  face's top-left.

## D12. Text colour animation

**Definition.** A text layer's colour lives on its text asset, which
cannot animate. `<animate property="color">` on a `layer` that places a
text asset animates that text's colour, with colour-valued keys and the
asset's `color` as the value between and outside the keys. The alpha must
stay the asset colour's alpha, since colours animate by channel.

## D13. Curves, handles, extrapolation and animate settings

**Curves.** Each curve shapes the segment from its key to the next.
- **Named easings:** `sine`, `quad`, `cubic`, `quart`, `quint`, `expo`,
  `circ`, `back`, `elastic` and `bounce` in `-in`, `-out` and `-in-out`
  are Robert Penner's equations as published on easings.net, with its
  constants: back 1.70158 (1.525 times that for in-out), elastic 2π/3 and
  2π/4.5, bounce 7.5625 and 2.75.
- **`steps`:** CSS `steps(n, start | end)`, where n is `@steps` and
  `stepPosition` selects start or end.
- **`spring`:** progress 1 − x(τ), where τ is seconds since the key, and
  m·x″ + c·x′ + k·x = 0 with x(0) = 1 and x′(0) = 0 (`@mass`, `@damping`,
  `@stiffness`). The segment is not rescaled, so a spring that has not
  settled jumps at the next key.
- **`catmull-rom`:** a cubic Hermite segment with slopes
  (v[i+1] − v[i−1]) / (t[i+1] − t[i−1]), one-sided at the ends.
- **`tcb`:** Kochanek-Bartels. The outgoing tangent uses the key's own
  tension, continuity and bias; the incoming tangent uses the next key's.
  Both are adjusted for non-uniform key spacing; a missing neighbour
  repeats the edge value.

**Temporal handles.** For a `cubic-bezier` segment without `@bezier`, the
key's `easeOut` "influence,speed" and the next key's `easeIn` give the
control points (influence_out, speed_out · influence_out) and
(1 − influence_in, 1 − speed_in · influence_in). Speed 1 is the segment's
average speed, and a missing handle is (1/3, 1), the straight line.
Handles on a segment of another curve are an error.

**Extrapolation.** Outside the keyed range:
- `hold` keeps the edge value;
- `linear` continues the edge segment's average slope;
- `loop` repeats the keyed range;
- `ping-pong` alternates it forwards and backwards;
- `offset` repeats it, shifting each cycle by the range's change.

**Animate settings.**
- `additive` adds the keys to the property's static value.
- `timeBase="local"` measures key times from the node's start.
- `timeBase="normalized"` maps 0 and 1 onto the node's start and end, so
  the node needs an end.

**Roving keys.** Each run of roving keys between fixed keys is retimed so
the value changes at constant speed across the run.

**Not defined here.** `spatialIn`/`spatialOut`: 1.1 transforms animate x
and y as separate properties, so there is no spatial path for tangents to
shape.

## D14. Blend modes

**Definition.** Blending works on working-space values with the W3C
Compositing and Blending Level 1 source-over formula
co = (1 − αb)·cs′ + (1 − αs)·cb′ + αs·αb·B(cb, cs):
- **W3C's own definitions** give B for normal, multiply, screen, overlay,
  darken, lighten, color-dodge, color-burn, hard-light, soft-light,
  difference, exclusion, hue, saturation, color and luminosity.
- **The Photoshop / After Effects definitions** give the rest:
  - subtract max(0, cb − cs);
  - divide cb / cs (1 when cs is 0 and cb is not);
  - linear-burn max(0, cb + cs − 1);
  - linear-dodge (alias of add) cb + cs;
  - linear-light clamp(cb + 2cs − 1);
  - vivid-light: color-burn with 2cs below one half, color-dodge with
    2cs − 1 above;
  - pin-light: min(cb, 2cs) below one half, max(cb, 2cs − 1) above;
  - hard-mix 1 where cb + cs ≥ 1, else 0;
  - darker-color / lighter-color: the whole colour with the lower /
    higher W3C luminance.

These modes take inputs clamped to [0, 1]; add, multiply and difference
pass HDR values through.

**Modes outside the formula.**
- `plus-lighter`: Porter-Duff plus, clamped at 1 per premultiplied
  channel.
- `behind`: destination-over.
- `alpha-add`: colour source-over, alpha αs + αb clamped at 1.
- `dissolve`: at each pixel, a stateless hash of (x, y, scene seed)
  uniform in [0, 1) selects the source, made opaque, where it falls below
  αs, and otherwise leaves the backdrop.
- `stencil-alpha` / `stencil-luma` scale the whole backdrop of the
  isolated parent buffer by the source's alpha / Rec. 709 luminance,
  clearing it where the source is absent.
- `silhouette-*` scale it by one minus those values.

## D15. Track mattes

**Definition.** `matte` names a sibling node, one in the same group, which
is drawn in the same parent space.
- **Rendering:** the matted node renders isolated, its buffer is scaled per
  pixel by the matte's factor, and the result composites with the node's
  own blend and opacity.
- **Factor by `matteMode`:** alpha (αm); alpha-inverted (1 − αm); luma
  (the Rec. 709 luminance of the matte's premultiplied working values,
  clamped to [0, 1]); luma-inverted (1 − luma). Where the matte draws
  nothing, alpha and luma are 0.
- **Visibility:** the matte node itself is hidden unless a node using it
  sets `matteVisible="true"`.

A matte outside the node's group, and chains of mattes that form a cycle,
are errors.

## D16. Masks

**Shapes**, in the node's local space:
- `rect` and `ellipse`: as before.
- `rounded-rect`: the box with circular corners of `radius`, capped at
  half the shorter side.
- `polygon`: `points` vertices on the ellipse inscribed in the box,
  starting at the top and going clockwise on screen; at least 3.
- `star`: 2 × `points` vertices alternating between that ellipse and the
  ellipse scaled by `innerRadius`, a fraction of the outer ellipse (0.5
  when absent).
- `path`: SVG path data filled with `fillRule`.

**Per mask, in order:**
1. anti-aliased coverage;
2. `expansion`: the maximum (positive) or minimum (negative) over a disc
   of that radius;
3. `feather`: a Gaussian blur whose standard deviation is `feather`
   (pixels in the node's space, like the blur effect's radius);
4. `invert`: 1 − coverage;
5. `opacity`: multiplies the result.

**Combining**, in document order: intersect a·m, add a + m − a·m,
subtract a·(1 − m), lighten max, darken min, difference |a − m|; `none`
masks are skipped. The coverage starts empty when the first active mask
adds, lightens or differences, and full otherwise. A node without active
masks is fully covered.

## D17. Symbols, instances, repeat and adjustment layers

**Instances.**
- **Size and background:** a symbol's box is its `width` × `height` (the
  project size when absent), and a `background` is a rect of that box
  beneath its content.
- **The clock:** an instance runs the symbol on its own clock,
  local = (t − start) · speed + clipIn, with `clipOut` defaulting to the
  symbol's `duration`. `reverse` runs from clipOut backwards; `loop="N"`
  wraps the clock over [clipIn, clipOut) and plays N + 1 times;
  `timeRemap` keys give local time directly.
- **When it ends:** without an explicit end, the instance ends when its
  clock runs out, as a video clip does (D9 reading).
- **`fit`:** CSS `object-fit` of the symbol box into `boxWidth` ×
  `boxHeight`, centred; `contain-blur` is not defined here.
- **Overrides:** `override` sets an attribute on the element with that id
  inside this instance's copy of the symbol, including inside nested
  instances; a target found nowhere inside the instance is an error. The schema types `@target` as
  an NCName, so the documented scoped form `instanceId/innerId` cannot
  occur, and targets are the inner id.

**Repeat.**
- **Copies:** copy i is transformed about the repeat's origin by
  T(i·offsetX, i·offsetY) · R(i·rotationStep) · S(scaleStep^i), has
  opacity max(0, 1 − i·opacityStep), and runs i·timeStep behind.
- **Order and blend:** copies stack from 0 upward and composite normally
  with each other; the repeat's `blend` composites the whole onto its
  backdrop.

**Adjustment layers.** An adjustment takes the composite of its siblings
below, within its group, applies its effects, and puts the result back
as backdrop + (effect − backdrop) · coverage. Coverage is its opacity
times its masks; only the normal blend has this meaning.

## D18. Include

**Definition.** `<include src>` reads another scene format 1.1 document.
- **Reading:** `src` is relative to the document that contains the
  include, `sha256` is checked against its bytes when given, and the
  document is validated (XSD and Schematron) with its own includes
  expanded first.
- **Merging:** its assets, effects, symbols and materials are merged
  under the namespace `includeId/`, and every reference to them is
  renamed. Asset paths stay relative to the included document.
- **Content:** with `symbol`, the include is an instance of that merged
  symbol (D17). Without it, the included composition's content forms a
  group at the include.
- **Overrides:** they change elements of the included content; an
  override whose target lies inside a nested instance applies to that
  instance's copy.

**Not carried over.** Everything other than content, assets, effects,
symbols and materials: project, output and metadata belong to the
included document, and any other section (lights, physics, audio,
markers, parameters, paints, styles) is reported, since merging it would
change what the included content means. An include that reaches itself
is an error.

**Diagnostics.** Diagnostics from validating an included document name
it. Errors found later, while translating included content, carry the
included document's line numbers but not its name.

## D19. Sequences and transitions

**Sequences.** Children are placed in document order.
- **Placement:** the first child keeps its own window [a, b); child k
  starts at P = previous end + `timeGap` + its own start a, and lasts
  b − a.
- **Shifting:** everything inside a child (keys, clips, nested instances)
  shifts with it, and its transform stays its own.
- **Unbounded children:** only the last child may have no end.
- **Default transitions:** `transition` names a transition type that is
  applied, with `transitionDuration`, at every junction without an
  explicit transition.
- **Not defined:** a transform `parent` on a sequence child.

**Transitions.**
- **Window:** a transition combines `from` (outgoing) and `to` (incoming),
  siblings, over a window of `duration` at the cut: centred on it,
  starting at it, or ending at it (`alignment`). The cut is `from`'s end,
  or `to`'s start when there is no `from`.
- **Handles:** both nodes' windows extend over the transition window, with
  their clocks unchanged. Inside the window they are drawn only through
  the transition, which composites where the later of them sits.
- **One node:** with only one node, the other side is transparent (a
  fade in or out).
- **Progress:** p = `curve` over the window, any curve without key
  parameters.
- **Geometry:** the frame's. `direction` gives the travel (left 180°,
  right 0°, up 270°, down 90°, `angle` degrees clockwise from +x);
  `softness` is the edge width as a fraction of the travel. Every masked
  type shows b where its coordinate s ∈ [0, 1] satisfies
  s < e − w, blends across [e − w, e], and shows a beyond, with
  e = p·(1 + w).

**Types:**
- `cut`: nothing is combined.
- `crossfade`: a·(1 − p) + b·p.
- `additive-dissolve`: a·min(1, 2(1 − p)) + b·min(1, 2p), clamped at 1.
- `dip-to-color`: a to `color` over the first half, `color` to b over the
  second.
- `wipe`: s along the travel, from the side it starts on.
- `barn-door`: s = the distance from the centre along the travel, over
  half the span.
- `circle-open` (and its alias `iris`): s = distance from the centre over
  half the diagonal.
- `circle-close`: its reverse on a.
- `clock-wipe`: s = the angle clockwise from 12 o'clock over 360°;
  `radial-wipe` sweeps from `angle`.
- `luma`: s = the Rec. 709 luminance of the `matte` sibling, which is not
  drawn itself.
- `push`: a leaves along the travel as b follows.
- `cover` (and its alias `slide`): b arrives over a static a.
- `reveal`: a leaves, uncovering a static b.

**Reported:**
- **No definition here yet:** `zoom-in`, `zoom-out`, `spin`, `whip-pan`,
  `blinds`, `blur`, `glitch`, `pixelize`, `stripe`, `squash`, `shuffle`,
  `light-leak` and `morph`, whose look no cited standard pins down;
  `flip`, `cube`, `page-curl`, `film-roll` and `carousel`, which need a
  3D projection of the node buffers.
- **Needs a GLSL runtime:** `shader`.
- **Also reported:** transition `param` children and animation, and
  motion blur on moving types (`motionBlur` defaults to true; set it
  false). Visual nodes carry no sound, so `audio` has nothing to mix.

## D20. Group layout, clocks and clips; layer media boxes

**Group clock.** Children see (t − `timeOffset`) · `timeScale`, D17's
group clock. The group's own window, effects and matte stay on master
time.

**Clip.** `clip="true"` clips the children to the group's box, so the
group needs `width` and `height`.

**Layout.** A flexbox subset over each child's untransformed box.
- **Boxes:** a shape's or group's size; a layer's `boxWidth` ×
  `boxHeight` or its asset's; an instance's box, or its symbol's (D17);
  an include's symbol's box. A composition include has no box, so it
  cannot be laid out.
- **Slots:** the layout computes a slot for each child in document order,
  and places the child's box there (its anchor included); the child's own
  x and y are offsets from the slot.
- **Padding:** insets the group's box.
- **Row and column:** place along the axis with `gap`. `justify` follows
  CSS (start, center, end, space-between, space-around, space-evenly; an
  overfull row puts space-between at the start and the others at the
  centre). `alignItems` start, center or end places across the axis.
  Without a size, the group is as large as its content.
- **Stack:** puts every child at the same slot, with `justify` across x
  and `alignItems` across y.
- **Grid:** fills `gridColumns` equal columns row by row; rows are as high
  as their tallest child.
- **Reported:** `alignItems` stretch and baseline (they would resize or
  measure content), and 3D objects in a layout.

**Media box.** A layer's asset is placed through one composed transform:
1. crop by the four fractions (the kept region moves to the origin);
2. the video's metadata `rotation`, clockwise on screen, in quarter turns;
3. its `pixelAspect`, scaling x;
4. `flipX` and `flipY` within the box;
5. `fit` (CSS object-fit) into `boxWidth` × `boxHeight` (the displayed
   box when absent), at `focusX` and `focusY` (CSS object-position).

The node's own transform applies around this, and the box clips.
`contain-blur` is reported, since its blurred fill is not defined.

**Frame blending.** `frame-mix` blends the two source frames floor(p) and
floor(p) + 1, where p = source time × frame rate, by the fraction of p,
wrapping or clamping like the frame index. `optical-flow` is reported.

**Also reported:** `stabilize` (no algorithm), `audioBus` (audio routing
is batch 7), and `collapse` (there are no 2.5D nodes yet).

## D21. Motion paths

**Definition.** A `motionPath` sets the node's x and y to a point on its
`path` at progress p.
- **Geometry:** the path is flattened exactly as a path shape is, each
  curve command in 16 equal parameter steps. A closed subpath includes
  its closing segment; subpaths follow one another with jumps that take
  no progress. A lone moveto draws nothing and is not part of the path.
- **Speed:** with `constantSpeed` (the default), p is the fraction of
  drawn length; otherwise every flattened segment takes an equal share.
- **Progress:** p comes from a nested `animate` on `progress`, or from
  `interpolation` (any curve without key parameters) over [`start`,
  `end`], with `end` defaulting to the node's end; before and after, p
  holds.
- **`autoOrient`:** adds the direction of travel, in degrees clockwise
  from +x, plus `orientOffset`, to the node's rotation.
- **At a vertex, including a jump:** the node takes the outgoing segment
  (its position is the vertex and its direction the next segment's), as a
  key applies from its time on.

**Reported:** animating x or y beside a motion path (the path sets the
position), and a second motion path on the same node.

## D22. Property links

**Definition.** A `link` drives a node's `property` (x, y, rotation,
scaleX, scaleY, anchorX, anchorY or opacity) as
clamp(source(t − `delay`) · `scale` + `offset`, `min`, `max`).
- **Sources:** `nodeId.property` is that node's own animated value of the
  property, anywhere in the composition, before its links, motion path or
  rigid body. Links are not followed through other links, so there are no
  cycles. `param:name` is a numeric parameter's value.
- **Smoothing:** with `smoothing` > 0, the source is the mean of 16 evenly
  spaced samples across [t − delay − smoothing, t − delay].

**Reported:**
- `audio:` sources: audio analysis is batch 7.
- `marker:` sources: what number a marker yields is not defined.
- Animating a linked property.
- Links on anything but nodes.

## D23. Transform constraints

**Model.**
- **World space:** the frame (the composition, at render scale).
- **A node's pose:** where its anchor lands, its rotation and its scales,
  so its transform is T(P) · R(θ) · S(sx, sy) · T(−anchor).
- **Order:** a node's constraints apply in document order, after its
  keyframes, links and motion path.
- **Influence:** each constraint is blended into the pose by `influence`,
  position, rotation (in degrees) and scale each linearly.
- **Targets** are read unconstrained: their world transform through their
  ancestors (with their clocks), transform parents, motion paths and
  links, but not their own constraints. So constraints never cycle.

**Types:**
- `parent`: the node's own transform composes onto the target's world
  transform instead of its ancestors'. It lives in the target's layer
  space, anchor offset included, as in After Effects.
- `look-at`: rotation is the direction from the node to the target plus
  `offsetRotation`.
- `copy-position`, `copy-rotation`, `copy-scale`, `copy-transform`: the
  target's world position (plus `offsetX`, `offsetY`), rotation (plus
  `offsetRotation`) and scales, or all three. With `space="local"`, the
  target's own values are used instead (its position as a point in the
  composition).
- `distance`: moves the node along the line to the target so that the
  distance lies in [`minDistance`, `maxDistance`].
- `follow-path`: places the node on `path` at `progress`, the path
  flattened as for motion paths (D21) and taken in composition pixels;
  `autoOrient` sets the rotation to the travel direction plus
  `offsetRotation`.

**Reported:**
- `ik`: a bone chain is batch 5 rigging.
- `track` and `point`: tracking data is not supported.
- `space="local"` on a non-copy constraint.
- A node constrained to itself.

## D24. Noise and camera shake

**Noise.** N(seed, channel, x) is 1D Perlin gradient noise.
- **Gradients:** at lattice point i the gradient is
  g = h / 2⁵³ · 2 − 1, where h is the top 53 bits of
  splitmix64(seed ⊕ splitmix64(channel ⊕ splitmix64(i))), with splitmix64
  the standard finaliser (increment 0x9E3779B97F4A7C15, multipliers
  0xBF58476D1CE4E5B9 and 0x94D049BB133111EB).
- **Value:** with f = x − ⌊x⌋ and u = 6f⁵ − 15f⁴ + 10f³,
  N = 2 · (g_i·f + (g_{i+1}·(f − 1) − g_i·f) · u). It lies in [−1, 1] and
  is zero at integers.
- **Fractal:** the sum over octaves k < `octaves` weights octave k by
  0.5ᵏ, samples channel · 1024 + k at x · 2ᵏ, and divides by the sum of
  the weights.

**Camera shake.** A camera's `shake`, within [`start`, `end`), takes four
fractal noise channels (0 to 3) at x = `frequency` · t, with `seed` or,
when absent, the project's seed.
- **Units:** `amplitude` moves the image by that many pixels at its
  centre:
  - 3D blocks: the camera moves by amplitude · N₀ right and amplitude · N₁
    down, in composition pixels (exactly that shift on the plane z = 0
    through the implicit camera);
  - panorama views: yaw moves by amplitude · N₀ and pitch by −amplitude ·
    N₁ times the degrees per pixel (the fov over the width, or 360 over
    the width in equirectangular mode).
- **Roll and zoom:** `rotation` adds rotation · N₂ degrees of roll;
  `zoom` scales the image by 1 + zoom · N₃, through the field of view.
- **2D layers:** they are not moved, since a camera does not see them.

## D25. Expressions

**Language.** A pure subset of ECMAScript.
- **Structure:** zero or more `const` or `let` declarations
  (`name = expression;`), then one expression, with an optional trailing
  `;`; comments are allowed.
- **Values:** numbers; `true`, `false` and comparisons are 1 and 0.
- **Operators:** `+ - * / % **` (right-associative), unary `- + !`,
  `< <= > >= == != === !==`, `&&` and `||` (short-circuit, returning an
  operand), `?:` and parentheses.
- **Math:** `abs`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sqrt`,
  `exp`, `log`, `floor`, `ceil`, `round` (⌊x + 0.5⌋, as ECMAScript),
  `sign`, `trunc`, `atan2`, `pow`, `hypot`, `min`, `max`, `PI` and `E`.
- **Strings:** literal arguments only, read when the expression compiles.
- **Excluded:** loops, functions, objects, arrays and assignment.

**Built-ins:**
- `time`: the node's time, group clocks applied.
- `frame`: ⌊time · fps + 10⁻⁹⌋.
- `value`: the property's own value (keys and links).
- `valueAtTime(t)`: its keys at t.
- `index` and `count`: the copy number from 0 and the copy count inside a
  repeat; otherwise the 0-based position among the parent's children in
  drawing order, and their number.
- `seed`: `@seed`, else the project's seed.
- `param(name)`: a numeric parameter.
- `prop("id.property")`: that node's own keys and links, not its
  expression, so expressions never cycle.
- `markerTime(id)`: the marker's time.
- `wiggle(freq, amp, octaves = 1, ampMult = 0.5)`: value + amp · Σ
  ampMultᵏ · N(seed, property · 1024 + k, time · freq · 2ᵏ) / Σ ampMultᵏ,
  over k < octaves, with N the D24 noise.
- `noise(x)`: N(seed, 7, x).
- `random()`: uniform in [0, 1) from a splitmix64 hash of (seed, frame,
  call site, property), the same within a frame; `random(max)` and
  `random(min, max)` scale it.
- `loopIn` and `loopOut(type, n = 0)`: before the first key or after the
  last, D13 extrapolation of the first or last n segments (all when 0):
  cycle as loop, pingpong, offset, and continue as linear.
- `linear`, `ease`, `easeIn`, `easeOut` with (t, t0, t1, v0, v1) or
  (t, v0, v1) over [0, 1]: v0 to v1 through the linear curve or the CSS
  ease-in-out, ease-in or ease-out, clamped.
- `clamp`, `lerp`, `smoothstep` (the GLSL form), and
  `spring(t, stiffness, damping, mass)` (D13's spring progress).

**Where.** An `expression` computes a node's x, y, rotation, scaleX,
scaleY, anchorX, anchorY or opacity. With `enabled="false"` it is
ignored.

**Reported:**
- `audioAmplitude` and `beat`: audio analysis is batch 7.
- `textIndex` and `textTotal`: text animators.
- `noise` in more than one dimension.
- Expressions on other properties or elements.
- An expression and a link on the same property.

## D26. Stroke style and fill rule

**Stroking.** Strokes follow SVG's stroking.
- **Segments:** each segment is a rectangle half the stroke width to
  either side.
- **Joins:** round (a disc); bevel (the triangle between the two offset
  corners); miter (the corner extended to its tip while the miter length
  over the stroke width, 1 / sin(θ / 2), stays within `miterLimit`, else
  a bevel). Only the outer side of a turn gets a join.
- **Caps:** at the ends of open subpaths and of every dash: butt
  (nothing), round (a disc), square (a half-width box).
- **Accuracy:** discs are 16-sided and coverage is exact over the
  resulting polygons, as for fills.

**Dashes.** `dash` lengths in path units, an odd list repeated (SVG);
the pattern starts `dashOffset` into itself and runs continuously along
each subpath, a closed one's closing segment included.
- **Joins:** a dash that runs through a vertex keeps its join.
- **Closed subpaths:** the dashes at the start and end stay separate,
  each with its caps.
- **Zero-length dashes:** draw nothing (a deviation from SVG, where round
  and square caps draw dots).
- **Limits:** at most 32 lengths, none negative; an all-zero list draws a
  solid stroke.

**`strokePosition`.** `inside` and `outside` stroke at twice the width,
kept within the fill or outside it (coverage times the fill's coverage or
its complement); open subpaths close for this, as fills do.

**`paintOrder`, `fillRule`.** `stroke-fill` paints the stroke under the
fill. `evenodd` takes the winding parity (|w| mod 2, folded).

**Rects and ellipses.** A stroked rect or ellipse draws as a closed
polygon, used for fill and stroke alike: the rect exactly; the ellipse
with ⌈π / acos(1 − 0.05 / r)⌉ sides (at least 16, r the larger radius),
within 0.05 units of the curve. Its size and fill cannot animate, since
the outline is fixed at load, so animating them is reported.

## D27. Shapes, vector assets and SVG

**Outlines**, in the node's box (0, 0, width, height), shared with D16's
masks:
- `rounded-rect`: circular corners of `radius`, or `cornerRadii` (four
  radii: top-left, top-right, bottom-right, bottom-left), each corner in
  16 steps. When two radii on a side exceed it, every radius scales by
  the least ratio (CSS `border-radius`).
- `polygon`: `points` vertices (3 to 1024), from the top, clockwise on
  screen, on the box's ellipse, or on a circle of `outerRadius` units
  about the box's centre.
- `star`: 2 × `points` vertices (2 to 1024 tips) alternating between that
  outer ellipse or circle and an inner circle of `innerRadius` units (when
  absent, the outer scaled by 0.5). On shapes, both radii are in units; on
  masks (D16) `innerRadius` is a fraction.
- `outerRoundness`, `innerRoundness` (0 to 1): give each vertex cubic
  handles tangent to its ellipse, of length roundness × 4/3 · tan(φ / 4)
  times the ellipse's derivative there (φ the angle between neighbouring
  vertices), flattened in 16 steps. At 1, with equal radii, the outline
  is the cubic approximation of a circle.
- `line`: from (0, height / 2) to (width, height / 2), across the box's
  vertical middle (the schema requires a positive height; rotation gives
  other angles); open, with no fill.

These outlines are fixed at load, so animating their size is reported.
Fill and stroke follow D26.

**Vector assets.** A layer of a `vector` asset draws the asset's shape
exactly as a shape node with its attributes would. The asset's default
`fillRule` is `evenodd`, as the schema gives it. Vector assets have no
`outerRadius`, roundness or stroke-style attributes, so those take their
defaults.

**SVG.** `shape="svg"` draws the file at `src` through nanosvg.
- **The subset:** `svg`, `g`, `path`, `rect`, `circle`, `ellipse`, `line`,
  `polyline`, `polygon`, `defs`, `title`, `desc`, `metadata`, with
  transforms, style attributes and inheritance.
- **Shapes:** each visible shape is a path layer, its cubics flattened in
  16 steps. Its colour is multiplied by its opacity, and its stroke width,
  caps, joins, miter limit, dashes, fill rule and paint order carry over.
- **Placement:** a group scales the SVG's size (its width and height, or
  viewBox; with neither, its shapes' bounds, as nanosvg sizes it) to the
  asset's `width` × `height`, strokes included, as SVG scales them.
- **Reported:** any other element (text, image, use, filter, clipPath,
  mask, pattern and the rest), `clip-path`, `mask`, `filter` and
  `marker-*` attributes (nanosvg would drop them without a word), a
  `paint-order` other than `normal` or all three keywords (nanosvg would
  draw it fill first), and gradients until paints exist.

## D9. Readings and effect units

| Point | Definition |
|---|---|
| Layer `loop="N"` | N plays after the first (N + 1 in total) |
| Clip end | A clip that does not loop ends when its media (clipOut, or the asset's duration) runs out |
| Effect units | Blur `radius` is the Gaussian standard deviation; drop-shadow `radius` is twice it (CSS Filter Effects `blur()` and `drop-shadow()`); glow threshold is working-space luminance |
| Particles | `size` is a diameter; `spread` is the full cone angle; gravity is px/s²; `speedVariance` is a uniform ± range |
| Physics | Positions (node x/y, pin x/y) are composition pixels; magnitudes are metres, +y up; walls take each body's restitution and friction; `solverIterations` is a quality hint |
| Markers | With `startMarker`/`endMarker`, `start`/`end` are offsets from the marker, as `time` is for `key/@marker` |
| Percentages | Relative to the parent box: the frame at the top level, a group's `width`/`height` when set; an unsized group passes its parent's box through |
| Vignette | Darkening 1 − `amount` · smoothstep(r₀, r₀ + `softness`, r), with r the distance from the frame centre over the half diagonal and r₀ = `radius` / half diagonal | new; exact in the engine |
| Colour grade | On unpremultiplied working values: `exposure` scales by 2^exposure; `contrast` maps v to 0.18 · (v / 0.18)^contrast; `saturation` blends from Rec. 709 luma; `brightness` then adds to each channel; negative results clamp to 0 | new; exact in the engine |

---

## P1. Text-animator presets (ruling 5.11)

A `textAnimator/@preset` expands onto the range-selector machinery with these values. Units, easing
names and `em` are as in the schema; `D` is `presetDuration` (default 1 s), `M` the number of position slots.

```
Timed selection. When @stagger is set, or for presets, each unit gets its own window:
with M position slots, duration D = presetDuration (default 1 s) and overlap o, a unit
lasts d = D / (1 + (M - 1)(1 - o)) and starts (1 - o)·d after the previous one
(explicit @stagger sets that step and d = stagger / (1 - o)). The window starts at
@presetStart (default: the layer's start), on the layer's clock (composition time,
or symbol time inside an instance). Progress q in [0, 1] is eased; "in" animators
select s = 1 - ease(q) (units rest in the offset state until their window starts),
"out" animators s = ease(q).

Presets (em = the text size after autoFit; an
explicit attribute, including @unit and @overlap, overrides the preset's value):
  preset            unit       mode    offsets at s=1                           ease        overlap
  typewriter        character  step    opacity 0                                -           -
  fade-in           character  in      opacity 0                                quad-out    0.6
  fade-out          character  out     opacity 0                                quad-in     0.6
  word-by-word      word       step    opacity 0                                -           -
  letter-by-letter  character  in      opacity 0, y +0.15em                     cubic-out   0.5
  line-by-line      line       in      opacity 0, y +0.4em                      cubic-out   0.3
  slide-up          word       in      opacity 0, y +0.8em                      cubic-out   0.5
  slide-down        word       in      opacity 0, y -0.8em                      cubic-out   0.5
  slide-left        word       in      opacity 0, x +1em                        cubic-out   0.5
  slide-right       word       in      opacity 0, x -1em                        cubic-out   0.5
  pop               word       in      scale 0 (back-out), opacity 0            back-out    0.5
  scale-in          word       in      scale 0, opacity 0                       cubic-out   0.5
  blur-in           word       in      blur 0.35em, opacity 0                   cubic-out   0.6
  wave              character  wave    y -0.25em * sin(2π(1.5·t - p/8)), faded in/out over 10% of D
  bounce            character  in      y -1em (bounce-out), opacity 0 (quad-out) bounce-out  0.6
  spin              character  in      rotation -180, scale 0.3, opacity 0      cubic-out   0.5
  ascend            character  in      y +0.5em, opacity 0                      expo-out    0.8
  shift             character  in      x -0.4em, opacity 0                      expo-out    0.7
  scramble          character  reveal  hidden before start; then unrevealed units show seeded random
                                       letters/digits (20 per second), unit p resolving at start + (p + 1)·D/M
  counter           -          text    every number in the text (or in @span) counts from 0, cubic-out over D
  karaoke           word       out     fill -> @fill (default #FFD400)          linear      0
  highlight         word       out     highlight box (paint @fill, default #FFD40059) wipes in   linear  0
  tracking-in       character  in      tracking +500 (1/1000 em), opacity 0     expo-out    0.85
  mask-reveal       line       in      y +1.1em inside a mask of the unit's line box  cubic-out  0.3
"step" shows unit p from start + p·D/M on (no fade).
```

## P2. Caption layout and presets (ruling 5.12)

For plain cues (inline, SRT, WebVTT and the transcription cache). Styled sources (ASS/SSA, TTML/IMSC, SCC)
carry their own presentation.

```
* x is the horizontal centre and y the top of the caption block; width is the wrap width.
  Lengths are relative to the output frame. The block is kept inside the track's safe area
  (else the project's) by moving it.
* cue/@position (and WebVTT cue settings, which fill it) overrides the placement:
  "X Y" (two lengths: centre x and top y), a keyword top | middle | bottom (the block's
  top / centre / bottom at the top / centre / bottom of the safe area, else of the frame),
  or WebVTT settings "line:L position:P size:S align:A" -- line N% puts the block's top
  (",center": centre, ",end": bottom) at N% of the frame height, line n (integer) is line
  n from the top (n < 0: from the bottom) in caption line heights; position P% anchors the
  block horizontally (",line-left" left edge, ",center" centre, ",line-right" right edge;
  default from align: start/left -> left edge, end/right -> right edge, else centre);
  size S% is the block width; align start|left|center|middle|end|right aligns the text.
* Lines are filled greedily with whole words up to maxCharsPerLine characters and
  maxWordsPerLine words; a cue needing more than maxLines lines is split into pages.
  Pages with word timings start at their first word; otherwise the cue duration is
  shared out by character count. Cues without <word> children get word timings the
  same way (so word-based presets work on plain cues).
* Caption time is composition time. Cue windows are half-open [start, end).
* Styles: the track @style (or the cue's @style), else 4.4% of the frame height in
  white DejaVu Sans; the active word takes @activeStyle and @activeColor
  (default #FFD400). emphasis="true" words are drawn at weight 800.
* Presets:
    classic     text as styled; a soft drop shadow is added when the style has neither
                shadow nor stroke
    boxed-line  a #000000B3 box behind each line (padding 0.25 em, radius 0.2 em)
    boxed-word  the active word sits on an activeColor box (padding 0.12 em)
    one-word    only the active word is shown
    karaoke     spoken words take activeColor; the current word blends in over its duration
    highlight   the active word takes activeColor
    pop         the active word takes activeColor and pops (scale 1.15, back-out, 0.25 s)
    fade        each page fades in and out over 0.15 s
    bounce      each word drops in (0.3 em, bounce-out over 0.35 s) when spoken
    slide       each page slides up 0.4 em and fades in over 0.25 s
    typewriter  words appear as they are spoken
    enlarge     the active word scales to 1.2 over 0.1 s and takes activeColor
    none        text as styled, nothing added
```
