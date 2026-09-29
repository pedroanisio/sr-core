```
SREP:            0
Title:           Add rigid bodies to object3D
Author:          rs-scene-render maintainers
Status:          Draft
Type:            Standards
Created:         2026-09-29
Schema-Version:  1.2
Requires:        the tiles and basemaps SREP (srep-0000-basemaps.md), for scene version 1.2 and rule V5
```

# SREP 0 — Add rigid bodies to object3D

## Abstract

A `<rigidBody>` child of `object3D` makes the object a body in a 3D physics world, simulated beside the 2D
one with the same step, gravity and bounds. The simulated pose replaces the object's transform. Collision
shapes follow the primitive or are chosen explicitly, including a convex hull, an exact triangle mesh and a
convex decomposition. Constraints between 3D bodies gain a depth coordinate, an axis and a ball joint;
force fields and gravity gain a component along z.

## Motivation

Physics in the baseline moves 2D nodes only. 3D motion graphics (crates tumbling, objects dropping into
place, pendulums, product shots that settle) need bodies that turn in depth and collide as volumes, and
today an author has to bake that motion in a separate tool and import it as an animation clip.

## Specification

### Syntax

```xml
<!-- a new child in object3DType's choice -->
<xs:element name="rigidBody" type="rigidBody3DType"/>

<xs:complexType name="rigidBody3DType">
  <xs:annotation><xs:documentation>
    A rigid body in 3D on an object3D: the simulation moves the object from its pose at
    physics@start (its position and rotations, in its parent's frame); from then on the
    simulation, not its own attributes, places it (a kinematic body follows its animation).
    shape="auto" takes the primitive's own form (box, sphere, cylinder, cone, capsule; a plane
    is a thin box) and the convex hull of any other mesh; convex-hull, trimesh (exact triangles,
    for static and kinematic scenery) and decomposition (convex parts of a closed mesh) use the
    object's triangles. Sizes follow the object's scale at the start. Velocities are pixels
    per second in scene axes (y down, z away from the camera), angular velocities degrees per
    second about the scene axes.
  </xs:documentation></xs:annotation>
  <xs:attribute name="type" default="dynamic">
    <xs:simpleType><xs:restriction base="xs:string">
      <xs:enumeration value="static"/><xs:enumeration value="kinematic"/>
      <xs:enumeration value="dynamic"/>
    </xs:restriction></xs:simpleType>
  </xs:attribute>
  <xs:attribute name="shape" default="auto">
    <xs:simpleType><xs:restriction base="xs:string">
      <xs:enumeration value="auto"/><xs:enumeration value="box"/>
      <xs:enumeration value="sphere"/><xs:enumeration value="capsule"/>
      <xs:enumeration value="cylinder"/><xs:enumeration value="cone"/>
      <xs:enumeration value="convex-hull"/><xs:enumeration value="trimesh"/>
      <xs:enumeration value="decomposition"/>
    </xs:restriction></xs:simpleType>
  </xs:attribute>
  <xs:attribute name="mass" type="positiveDecimal" default="1"/>
  <xs:attribute name="friction" type="unitDecimal" default="0.5"/>
  <xs:attribute name="restitution" type="unitDecimal" default="0"/>
  <xs:attribute name="linearDamping" type="unitDecimal" default="0.01"/>
  <xs:attribute name="angularDamping" type="unitDecimal" default="0.01"/>
  <xs:attribute name="velocityX" type="xs:double" default="0"/>
  <xs:attribute name="velocityY" type="xs:double" default="0"/>
  <xs:attribute name="velocityZ" type="xs:double" default="0"/>
  <xs:attribute name="angularVelocityX" type="xs:double" default="0"/>
  <xs:attribute name="angularVelocityY" type="xs:double" default="0"/>
  <xs:attribute name="angularVelocityZ" type="xs:double" default="0"/>
  <xs:attribute name="collisionGroup" type="xs:nonNegativeInteger" default="0"/>
  <xs:attribute name="collidesWith" type="xs:string" default="all"/>
  <xs:attribute name="sensor" type="xs:boolean" default="false"/>
  <xs:attribute name="fixedRotation" type="xs:boolean" default="false"/>
  <xs:attribute name="bullet" type="xs:boolean" default="false"/>
  <xs:attribute name="activateAt" type="xs:double" default="0"/>
</xs:complexType>

<!-- constraintType: a new type value and four attributes -->
<xs:enumeration value="ball"/>
<xs:attribute name="z" type="xs:double"/>
<xs:attribute name="axisX" type="xs:double"/>
<xs:attribute name="axisY" type="xs:double"/>
<xs:attribute name="axisZ" type="xs:double"/>

<!-- forceFieldType -->
<xs:attribute name="z" type="xs:double" default="0">
  <xs:annotation><xs:documentation>Depth of a radial field's centre, for 3D bodies.</xs:documentation></xs:annotation>
</xs:attribute>
<xs:attribute name="forceZ" type="xs:double" default="0">
  <xs:annotation><xs:documentation>m/s² toward the camera, for 3D bodies.</xs:documentation></xs:annotation>
</xs:attribute>

<!-- physicsType -->
<xs:attribute name="gravityZ" type="xs:double" default="0">
  <xs:annotation><xs:documentation>m/s² toward the camera, for 3D bodies.</xs:documentation></xs:annotation>
</xs:attribute>
```

The constraint documentation gains: "Between 3D bodies (object3D rigidBody) the anchor is x, y, z; hinge,
motor and slider turn about or slide along axisX, axisY, axisZ (scene axes; z by default for hinges and
motors, x for sliders); ball is a ball-and-socket joint."

```xml
<!-- a new pattern -->
<sch:pattern id="p43">
  <sch:rule context="object3D/rigidBody">
    <sch:assert id="C48" test="not(@shape='trimesh') or @type='static' or @type='kinematic'">a trimesh rigidBody must be static or kinematic.</sch:assert>
  </sch:rule>
</sch:pattern>

<!-- the version gate V5 (added by the basemaps SREP) extends its test to -->
not(assets/tiles|.//basemap|.//object3D/rigidBody)
```

### Semantics

**World.** The 3D world is separate from the 2D world: 3D bodies meet only 3D bodies. It uses the 2D world's
`physics@start`, `@fixedStep`, `@solverIterations` and `@pixelsPerMeter` (ppm). Its axes are metres with y up
and z toward the camera: a scene point (x, y, z) is (x, −y, −z) / ppm, and a rotation quaternion
(qx, qy, qz, qw) in scene axes is (qx, −qy, −qz, qw). Gravity is (`gravityX`, `gravityY`, `gravityZ`) m/s² in
those axes (default (0, −9.80665, 0)). Each step of Δt = `fixedStep` is divided into k = `solverIterations`
substeps of h = Δt/k; each substep integrates velocities, then solves contacts and joints, then integrates
positions (semi-implicit Euler):

    v ← (v + (g + F/m)·h) / (1 + c·h),  then  x ← x + v·h        (c: linearDamping)

so a free body starting at rest falls g·h²·N(N+1)/2 metres in N substeps. Dynamic bodies are held on their
animation until `activateAt`, as in 2D. A frame at time t shows the state after
floor((t − start)/fixedStep + 10⁻⁹) steps; seeking gives the same state as playing up to t.

**Start pose.** At `physics@start` a body's pose is the object's world transform (conventions rule 2.5,
including its `@parent` chain or its 2D container) split into translation, rotation and scale. The scale
sizes the collision shape and is kept: after the start, the object's world transform is
T(simulated position) · R(simulated rotation) · S(start scale), replacing its own transform and parent.
Objects parented to a body follow it.

**Shapes** (sizes in the object's units times its start scale, centred on the object's origin):

| `shape` | collider |
|---|---|
| `auto` | `box`/`plane`: a box of width × height × depth (a plane is 1 unit deep); `sphere`, `globe`: a sphere of radius; `cylinder`, `cone`, `capsule`: that shape along y, while the scale is equal in x and z; any other primitive, or a non-uniform scale: the convex hull of its triangles |
| `box`, `sphere`, `capsule`, `cylinder`, `cone` | that shape from the object's width, height, depth and radius |
| `convex-hull` | the convex hull of the object's triangles |
| `trimesh` | the object's triangles (static and kinematic bodies only, C48) |
| `decomposition` | convex parts of the object's triangles by V-HACD |

A mesh asset contributes its triangles in its rest pose, after the import convention of rule 2.6.

**Motion.** `velocityX/Y/Z` are pixels per second and `angularVelocityX/Y/Z` degrees per second, in scene
axes, at the start. Kinematic bodies, and dynamic bodies before `activateAt`, follow the object's animated
transform. `collisionGroup`, `collidesWith`, `sensor`, `fixedRotation` and `bullet` mean what they mean for
2D bodies.

**Bounds.** `physics@bounds="floor"` adds a static ground plane at scene y = frame height; `"frame"` adds a box
0 ≤ x ≤ W, 0 ≤ y ≤ H, −D/2 ≤ z ≤ D/2 with D = max(W, H).

**Constraints.** A constraint joins two 3D bodies when `@a` names one; `@b` must then name another (or be
absent for `pin`), and a constraint joining a 2D and a 3D body is reported. The anchor is (`x`, `y`, `z`)
(z default 0) at the start, else `b`'s centre (`a`'s for pins). `hinge` and `motor` rotate about the axis
(`axisX`, `axisY`, `axisZ`) (default (0, 0, 1)) with `minAngle`/`maxAngle` in degrees and `motorSpeed` in
degrees per second; `slider` translates along the axis (default (1, 0, 0)) with `minAngle`/`maxAngle` as the
travel in pixels; `ball` keeps the anchor points together and leaves rotation free; `weld`, `rope`,
`spring`, `distance` and `pin` behave as in 2D. `breakForce` removes the joint once the linear force the
joint applies exceeds it in newtons.

**Force fields** act on 3D bodies in 3D: `radial` pulls toward (or pushes from) (`x`, `y`, `z`) along the 3D
distance; `directional` and `wind` push along (`forceX`, `forceY`, `forceZ`) with +z toward the camera, the z
part of `wind` gusting with the same noise as its x and y parts; `drag` opposes the velocity in 3D; `vortex`
turns about the line through (`x`, `y`) parallel to z; `turbulence` and `attractor-path` act in the xy
plane, from the body's x and y.

### Defaults and the neutral case

The element is new, and the new attributes default to zero; documents without 3D bodies render as before.

## Rationale

- **A separate 3D world** keeps the baseline's 2D behaviour bit-identical.
- **Scene axes in the document, y-up metres inside** follow the conventions (rule 2.1, 2.6) and the 2D
  physics baseline (metres, y up, `pixelsPerMeter`).
- **Shapes from the primitive** mirror the 2D baseline, which derives a body's box from its node.
- **C48:** a dynamic triangle mesh has no well-defined volume or inertia; every mainstream engine (Rapier,
  PhysX, Bullet) restricts it to static or kinematic use.

## Rejected alternatives

- **One world for 2D and 3D bodies.** 2D nodes have no depth or volume; mixing them changes 2D results.
- **A new `rigidBody3D` element name.** The context (`object3D`) already says it is 3D, and authors
  expect the 2D name.

## Backwards compatibility

Every 1.1 document is valid and renders the same. `object3D/rigidBody` requires `version="1.2"` (V5). The
new constraint, field and physics attributes are accepted in every version and do nothing without 3D bodies.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | branch `maps-physics` | done: Rapier 3D (f64, enhanced determinism), checkpoints, shapes, joints, fields | |
| C (`c-scene-render`) | pending | a 3D rigid-body solver | |
| Python (`py-render`) | pending | | |
| JavaScript (`js-render-engine`) | pending | Rapier has a JavaScript build | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `conformance/cases/srep-0000-rigid3d-fall.xml` | a sphere after 0.5 s of free fall (physics@start = −0.5) lands at the semi-implicit Euler position | 2 px |
| `conformance/cases/srep-0000-rigid3d-rest.xml` | a sphere dropped onto a static box rests on its top | 2 px |

## Open issues

- The contents of `physics@cache` are engine-specific; whether a 3D cache format should be standardised.
- Whether `turbulence` and `attractor-path` should act along z.
- Rule id C48 is provisional until the editor assigns it.

## References

- Rapier physics engine: https://rapier.rs
- V-HACD: https://github.com/kmammou/v-hacd

## History

- 2026-09-29: first draft.
