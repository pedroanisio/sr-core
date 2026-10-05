---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude via Claude Code"
  date: "2026-10-01"
---

```
SREP:            0
Title:           Place the copies of a repeat on generated points
Author:          scene-render maintainers
Status:          Draft
Type:            Standards
Created:         2026-10-01
Schema-Version:  1.2
```

# SREP 0 — Place the copies of a repeat on generated points

## Abstract

A `repeat` gains an optional child, `<points>`, that generates a list of points: a grid, positions along a
path, a seeded scatter inside a rectangle or a path, the vertices of a path, or an explicit list. With it,
the repeat makes one copy per point and places copy i on point i, before its existing step offsets.
Expressions inside such a repeat read five new names: `pointX`, `pointY`, `pointAngle`, `pointU` and
`pointRandom`. A repeat without `<points>` is unchanged. Documents that use `<points>` declare
`version="1.2"`.

## Motivation

A `repeat` places copy i by cumulative steps: T(i·offsetX, i·offsetY) · R(i·rotationStep) ·
S(scaleStep^i) (D17). Beyond that, an author writes the arrangement as expressions over `index` (D25).

**What the baseline already does.** Checked with `scene-render eval` on the reference engine:

- **A grid** from one repeat of six copies, with
  `x = 200 + (index % 3 - 1) * 100` and `y = 200 + (floor(index / 3) - 0.5) * 100`. The copies land on
  (100, 150), (200, 150), (300, 150), (100, 250), (200, 250), (300, 250).
- **A circle,** through `sin` and `cos` of `index`.
- **Variation per copy that is constant in time,** with `noise(index * 1.37 + 0.125)`: each copy gets a
  different value, and the values at t = 0 and t = 2 are identical.

**What this SREP adds.**

1. **Placement along an arbitrary path.** No expression can measure a path's length, and a `motionPath`
   places one node, not n. Today the positions are computed outside the document and written as numbers.
2. **Placement inside a region,** and on the vertices of a path. Neither can be written as an expression.
3. **A uniform draw with a stated definition.** `noise(index · a + b)` is Perlin noise read at arbitrary
   points: its values are correlated for nearby arguments, are not uniform, and depend on constants the
   author picks. `random()` in D25 is a hash of the seed, the frame, the call site and the property, so it
   changes every frame.
4. **Simpler authoring.** The grid above takes two expressions with the column count written twice.
   `<points type="grid" columns="3" rows="2"/>` states the arrangement itself, and the copies' own
   `x` and `y` stay free for animation.

**Reference picture.** Because a document can already place copies at explicit positions, every
arrangement in this SREP has a baseline equivalent: the same scene with each copy's position written as
a number computed independently. The conformance cases compare against those positions.

Precedent for placing copies on generated points:

- OpenUSD `UsdGeomPointInstancer` and glTF `EXT_mesh_gpu_instancing`: one prototype drawn at a list of
  positions, orientations and scales.
- After Effects and Lottie shape repeaters: the cumulative-step model `repeat` already has, and its limit.
- Cavalry's Duplicator, which takes a distribution (grid, path, shape, point list), and Caddis's Clone to
  Points and Draw Instances, which take a point stream. Both are the peers' central procedural feature
  (feature comparison of 2026-10-01, category "Procedural geometry and fields").

## Specification

### Syntax

The XSD gains `pointListType` and `pointsType`, and `repeatType`'s content gains the `points` element.
`scene/@version` accepts `1.2`.

`pointListType` is also declared by [SREP 16](srep-0016.md); whichever SREP lands first declares it.

```xml
<xs:simpleType name="pointListType">
  <xs:list itemType="pointType"/>
</xs:simpleType>
<xs:complexType name="pointsType">
  <xs:annotation><xs:documentation>
    Generates the points on which a repeat places its copies: one copy per point, copy i on point i,
    in the repeat's own space (pixels, +y down). type grid (columns x rows, centred on the origin),
    along-path (count points at equal arc length along @path), scatter (count seeded points inside
    width x height centred on the origin, or inside @path), vertices (one point per vertex of @path)
    or list (the pairs of @at). Expressions inside the repeat read pointX, pointY, pointAngle, pointU
    and pointRandom.
  </xs:documentation></xs:annotation>
  <xs:sequence>
    <xs:element name="animate" type="animateType" minOccurs="0" maxOccurs="unbounded"/>
  </xs:sequence>
  <xs:attribute name="id" type="xs:ID"/>
  <xs:attribute name="type" use="required">
    <xs:simpleType><xs:restriction base="xs:string">
      <xs:enumeration value="grid"/><xs:enumeration value="along-path"/>
      <xs:enumeration value="scatter"/><xs:enumeration value="vertices"/>
      <xs:enumeration value="list"/>
    </xs:restriction></xs:simpleType>
  </xs:attribute>
  <xs:attribute name="columns" type="xs:positiveInteger" default="1"/>
  <xs:attribute name="rows" type="xs:positiveInteger" default="1"/>
  <xs:attribute name="spacingX" type="xs:double" default="100"/>
  <xs:attribute name="spacingY" type="xs:double" default="100"/>
  <xs:attribute name="count" type="xs:nonNegativeInteger"/>
  <xs:attribute name="path" type="xs:string"/>
  <xs:attribute name="fillRule" type="fillRuleType" default="nonzero"/>
  <xs:attribute name="orient" type="xs:boolean" default="false"/>
  <xs:attribute name="width" type="nonNegativeDecimal"/>
  <xs:attribute name="height" type="nonNegativeDecimal"/>
  <xs:attribute name="at" type="pointListType"/>
  <xs:attribute name="seed" type="xs:unsignedLong"/>
</xs:complexType>

<!-- in repeatType, the content model becomes: -->
<xs:choice minOccurs="0" maxOccurs="unbounded">
  <xs:element name="points" type="pointsType"/>
  <xs:group ref="nodeBehaviour"/>
  <xs:group ref="nodeChoice"/>
</xs:choice>
```

Rule C17 is amended, and one version gate and seven checks are added. The rule and pattern ids are
provisional (see Open issues).

```xml
<!-- p11, amended -->
<sch:assert id="C17" test="count(@count) + count(@over) + number(boolean(points)) = 1">repeat needs exactly one of @count, @over or a points child.</sch:assert>

<sch:pattern id="p68">
  <sch:rule context="/scene[@version='1.0' or @version='1.1']">
    <sch:assert id="V10" test="not(.//repeat/points)">points in a repeat needs version="1.2".</sch:assert>
  </sch:rule>
</sch:pattern>
<sch:pattern id="p69">
  <sch:rule context="repeat">
    <sch:assert id="C74" test="count(points) &lt;= 1">a repeat takes at most one points child.</sch:assert>
    <sch:assert id="C80" test="not(points and (@from[. != 0] or @step[. != 1]))">a repeat with a points child takes no @from other than 0 and no @step other than 1.</sch:assert>
  </sch:rule>
  <sch:rule context="repeat/points">
    <sch:assert id="C75" test="not(@type='along-path') or (@path and @count)">points type="along-path" needs @path and @count.</sch:assert>
    <sch:assert id="C76" test="not(@type='scatter') or (@count and ((@path and not(@width or @height)) or (not(@path) and @width and @height)))">points type="scatter" needs @count and either @path or both @width and @height.</sch:assert>
    <sch:assert id="C77" test="not(@type='vertices') or @path">points type="vertices" needs @path.</sch:assert>
    <sch:assert id="C78" test="not(@type='list') or @at">points type="list" needs @at.</sch:assert>
    <sch:assert id="C79" test="not(animate[not(@property='spacingX' or @property='spacingY' or @property='width' or @property='height')])">points animates only spacingX, spacingY, width and height.</sch:assert>
  </sch:rule>
</sch:pattern>
```

### Semantics

Symbols used below:
- **n**, the number of points; **i**, a point's index, 0 ≤ i < n;
- **(xᵢ, yᵢ)**, point i, in the repeat's own space: the space in which the repeat's step offsets are
  applied, pixels, +y down;
- **θᵢ**, the angle of point i, in degrees clockwise;
- **s**, the seed: `points/@seed`, else `project/@seed`;
- **U(s, c, k)** = ⌊splitmix64(s ⊕ splitmix64(c ⊕ splitmix64(k))) / 2¹¹⌋ / 2⁵³, a number in [0, 1), with
  splitmix64 as D24 defines it. This is D24's lattice hash, read as a unit number.

Every coordinate below is computed in IEEE 754 binary64, in the order the formula is written.

**0. Attributes.**
1. `id`, `type` and `seed` apply to every type. `seed` feeds the scatter and `pointRandom` (clause 7),
   so it is read by `grid`, `along-path`, `vertices` and `list` as well.
2. Of the remaining attributes, each type reads only those its clause names. The others are ignored.
3. `path` is SVG path data. Path data that a path shape would reject is an error here too.
4. A path's **segments** are its flattened line segments (clause 3.1). A path with no segments is
   **empty**: the empty string, or movetos only (a lone moveto is not part of a path, D21).

**1. The repeat.**
1. A repeat with a `points` child MUST make n copies, and inside it `count` is n.
2. Copy i MUST be transformed about the repeat's origin by
   T(xᵢ, yᵢ) · R(θᵢ) · T(i·offsetX, i·offsetY) · R(i·rotationStep) · S(scaleStep^i).
   The step offsets are therefore applied in the point's rotated frame: with (xᵢ, yᵢ) = (100, 0),
   θᵢ = 90°, i = 1 and `offsetX="20"`, the copy's origin is at (100, 20).
3. Opacity, `timeStep`, stacking order and `blend` are as D17 defines them for a counted repeat.
4. When n = 0 the repeat draws nothing.
5. On a repeat with `points`, `@from` MUST be absent or 0 and `@step` MUST be absent or 1 (C80). The
   rule tests the values, so it gives the same verdict whether or not a validator has inserted the
   XSD's defaults (`from="0"`, `step="1"`) before the Schematron runs.

**2. `grid`.** With C = `columns` and R = `rows`:
- n = C · R;
- for point i, col = i mod C and row = ⌊i / C⌋;
- xᵢ = (col − (C − 1)/2) · `spacingX`, yᵢ = (row − (R − 1)/2) · `spacingY`, θᵢ = 0.

**3. `along-path`.**
1. `path` is flattened exactly as a motion path is (D21): each curve command in 16 equal parameter
   steps, a closed subpath including its closing segment, subpaths following one another with jumps
   that take no length.
2. n = `count`, and n = 0 when the path is empty. L is the path's total drawn length.
3. The path is **closed** when it has exactly one subpath and that subpath is closed. Then the arc
   length of point i is ℓᵢ = i · L / n. Otherwise ℓᵢ = i · L / (n − 1), and ℓ₀ = 0 when n = 1.
4. (xᵢ, yᵢ) is the point of the flattened path at drawn length ℓᵢ.
5. The direction at point i is the direction of travel there, in degrees clockwise from +x.
   - Segments of zero length have no direction and are skipped.
   - At a vertex, including a jump, the direction is that of the next segment of non-zero length (D21).
   - Where no such segment follows, it is that of the last segment of non-zero length.
6. θᵢ is that direction when `orient="true"`, and 0 otherwise.
7. When the path has segments and L = 0, every point is the start of the first segment and every
   direction is 0.

**4. `scatter`.**
1. **In a rectangle** (`width` and `height`): n = `count`,
   xᵢ = (U(s, 0, i) − 1/2) · `width`, yᵢ = (U(s, 1, i) − 1/2) · `height`.
2. **In a path** (`path`): the path is flattened as in 3.1, and every subpath is closed for this purpose.
   B is the bounding box of the flattened vertices, from (bx, by), with size bw × bh.
   - **Candidates.** Candidate j is (pₓ, p_y) = (bx + U(s, 0, j) · bw, by + U(s, 1, j) · bh). The
     candidates tried are those with 0 ≤ j < 64 · `count`, in increasing j, stopping as soon as `count`
     have been accepted.
   - **Winding number.** For a candidate, w is the sum over the segments (x₀, y₀)–(x₁, y₁) of the path:
     - +1 when y₀ ≤ p_y < y₁ and x₀ + (p_y − y₀) · (x₁ − x₀) / (y₁ − y₀) > pₓ;
     - −1 when y₁ ≤ p_y < y₀ and the same expression is > pₓ;
     - 0 otherwise. Horizontal segments contribute nothing.
   - **Acceptance.** A candidate MUST be accepted when w ≠ 0 under `fillRule="nonzero"`, or when w is
     odd under `evenodd`, and rejected otherwise. Nothing is left to the engine: a candidate on a left
     or top edge of the region is inside, and one on a right or bottom edge is outside, as U itself
     includes 0 and excludes 1.
   - **Result.** The points are the accepted candidates, in order of j. n is their number, which is
     less than `count` when fewer are accepted among the candidates tried.
   - n = 0 when `count` is 0, when the path is empty, or when bw = 0 or bh = 0.
3. θᵢ = 0.
4. Points MAY coincide or overlap; no minimum distance is kept.

**5. `vertices`.** One point per drawing command of `path` (lineto, curve and arc commands, and each
moveto), at the command's end point, in document order.
- A closepath adds no point.
- When the last point of a closed subpath coincides with the subpath's first point, it is dropped.
- θᵢ = 0. The path is not flattened: a curve contributes its end point only.
- A path of movetos only gives one point per moveto. The empty string gives n = 0.

**6. `list`.** n is the number of pairs in `at`; (xᵢ, yᵢ) is pair i; θᵢ = 0.

**7. Expression names.** Inside a repeat with `points`, expressions (D25) on the repeat's descendants
read, for the copy they belong to:

| Name | Value |
|---|---|
| `pointX`, `pointY` | xᵢ, yᵢ |
| `pointAngle` | the direction of 3.5 for `along-path`, whatever `orient` says; 0 for the other types |
| `pointU` | i / (n − 1), and 0 when n = 1 |
| `pointRandom` | U(s, 2, i) |

- With nested repeats, the names refer to the nearest enclosing repeat that has `points`.
- Outside any such repeat the names are not defined, as before this SREP.
- `pointRandom` does not depend on time: it is the same on every frame.

**8. Time and animation.**
1. `spacingX`, `spacingY`, `width` and `height` animate. Their keys are read at the repeat's own local
   time t: the time its siblings' keys are read at, group clocks applied.
2. The points are computed once per frame, from the values at t, and every copy is placed from that
   one list. `timeStep` delays the content of copy i by i · `timeStep`; it does not delay the point
   copy i is placed on, nor the five names of clause 7.
3. With nested repeats, an inner repeat's points are computed at the inner repeat's local time inside
   the copy it belongs to, so that time carries the outer copy's delay.
4. No state is kept between frames: the points at t are a function of the document and t alone, whatever
   frames were evaluated before and in whatever order.
5. `count`, `columns`, `rows`, `path`, `at`, `fillRule`, `orient` and `seed` do not animate.

### Design rules of SREP 14

This SREP adds procedural and random values, so [SREP 14](srep-0014.md) applies, should it be adopted.

| Rule | How it is met |
|---|---|
| 1. Time | No simulation and no state: closed forms of the document and t (8.4). |
| 2. Randomness | Every draw is U(s, c, k), D24's lattice hash with integer indices. No generator carries state. |
| 3. Order independence | Each point is a function of its own index. The path scatter is defined by candidate order j, not by evaluation order. |
| 4. Units and frames | Pixels in the repeat's space; no new frame. |
| 5. Agreement | Still-frame measurements at the kit's default 2 px. The scatter and time cases are seek-checked. |
| 6. Validation | Closed forms: grid positions; equal spacing on a circle and on a segment. The hash, the accepted candidates and the point counts cannot be verified to 2 px on a still frame, so they are checked exactly by the numeric tests under Conformance. |
| 7. Pinned external data | None. |
| 8. Permissive sources | No new library or dataset. |

### Defaults and the neutral case

`points` is a new element, so no existing document contains one. A repeat without it takes exactly one of
`@count` and `@over`, as C17 required before, and is placed by D17 unchanged. The five expression names are
defined only inside a repeat with `points`.

## Rationale

- **Baseline conventions.** Points are in pixels with +y down and angles clockwise, in the space where
  the repeat's own offsets already apply. A repeat's steps keep their meaning and compose after the
  point, so `timeStep` still staggers the copies and `rotationStep` still fans them.
- **A child of `repeat`, not a new node.** `repeat` already defines copies, their ids, their order, their
  blend, `index` and `count`. A second copying node would define all of that twice.
- **Flattening as D21.** Motion paths already fix how a path is measured: 16 steps per curve. Using the
  same rule means a node on a `motionPath` and a copy placed `along-path` at the same fraction land on
  the same pixel.
- **Randomness from D24.** Convention 5.19 requires every seeded function to draw from D24's hash. U is
  that hash, read as the top 53 bits, as D24 reads its gradients.
- **`pointRandom` is constant in time.** The existing `random()` varies per frame. A per-copy constant is
  what size, delay and opacity variation need; multiplied into `wiggle` it gives variation in time too.
- **Rejection sampling for a path region** is the only method here that needs no triangulation, and its
  result is fixed by the candidate order. The cap of 64 candidates per requested point bounds the cost.
  A region that fills a fraction a of its box accepts about 64 · a · `count` candidates, so a region
  under 1/64 of its box usually, but not always, returns fewer points than asked. The number is fixed
  by the seed either way.
- **Half-open edges.** The winding rule of 4.2 counts a segment for y₀ ≤ p_y < y₁ and a crossing strictly
  to the right. It is the usual crossing-number test, and it gives every boundary point one answer. An
  edge candidate is not hypothetical: seed 14325487974692486532 gives U(s, 0, 0) = 0, which puts the
  first candidate of any region on the left side of its box.
- **Points before delays.** Computing the points once at the repeat's time, and delaying only the
  copies' content, keeps an animated grid one grid. Delaying each copy's point by i · `timeStep` would
  place the copies on n different grids at once.
- **Non-neutral `@from` and `@step` are rejected,** not defined: a `@from` other than 0 or a `@step`
  other than 1. D17 does not say what they do, so giving them a meaning over points would define them
  by the back door.
- **C80 tests values, not presence.** The XSD declares `from="0"` and `step="1"` as defaults, and some
  validators insert defaults into the document before the Schematron sees it. A rule on presence would
  then reject a document that wrote neither attribute. Testing for a non-neutral value is independent
  of that order, as SREP 16's `@fromAnchor[.!='auto']` is. The cost is that an explicit `from="0"` or
  `step="1"` is accepted, which changes nothing.
- **External precedent.** UsdGeomPointInstancer separates the list of positions from the prototype, as
  `points` and the repeat's children do here. Cavalry's distributions and Caddis's point nodes offer the
  same five sources (grid, path, region, vertices, list).

## Rejected alternatives

- **Status quo: expressions over `index`.** Covers grids, circles and noise-based variation, but not
  paths, regions or vertices, and has no uniform draw (see Motivation).
- **A top-level `<pointSets>` section referenced by IDREF.** It would let several elements share one
  set, which nothing needs yet. `points` carries an `id` so a later SREP can reference it where it is.
- **More attributes on `repeat` itself** (`grid`, `alongPath`, `scatter`). Fifteen attributes of which
  each arrangement reads three; a typed child keeps `repeat` as it is.
- **Path functions in expressions** (`pathX(d, u)`). Paths would be parsed from string arguments on every
  node, and scatters and vertices would still be missing.
- **Poisson-disk scattering.** Planned as G1 of [SREP 12](srep-0012.md) (Bridson 2007), with terrain
  masks. It needs a spatial grid and an exactly specified order of insertion; uniform scatter does not.
  A later SREP can add it as a `scatter` option.
- **Fields that weight or move the points.** Planned as MF5 of SREP 12. This SREP gives fields something
  to act on and does not depend on them.
- **Per-point colour.** Expressions set transform and opacity only (D25). Widening that is a separate
  change to D25.

## Backwards compatibility

- **Class: Added, MINOR (1.2).** `<points>` is new and needs `version="1.2"` (V10).
- **C17 is amended,** and accepts exactly the documents it accepted before among those with no `points`
  child. No document valid under 1.1 becomes invalid, and none renders differently.
- **Expression names.** `pointX`, `pointY`, `pointAngle`, `pointU` and `pointRandom` become defined
  inside a repeat with `points` only. A 1.1 document cannot contain one, so no existing expression
  changes meaning.
- **Evidence.** Not yet gathered: the amended schema has not been run against the local scene corpus.
  This is required before Review.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending; no branch yet | `sr-model`: parse `points`. `sr-eval` `program.rs`: where a repeat expands into `RepeatCopy` entries, take n and the copy transform from the points; `path.rs` already flattens and measures by D21 (`MotionPath::sample`). `sr-eval` `expr`: five new variables beside `index` and `count`. `sr-vector` `d24.rs`: U from the existing `splitmix64`. Animated `spacingX`/`spacingY`/`width`/`height` make the copy transforms time-dependent, which the offscreen and prefix caches must key on. | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `conformance/cases/srep-0-grid.xml` | 3 × 2 grid of squares: six centroids (2), and `count` = 6 through an opacity expression. A second group draws the same squares at explicit positions in another colour; the two sets of centroids agree | 2 px |
| `conformance/cases/srep-0-grid-steps.xml` | grid with `offsetX` and `scaleStep`: centroids and extents show the point applied before the steps (1.2) | 2 px |
| `conformance/cases/srep-0-order.xml` | `along-path` on `M100,-50 L100,0`, `count="2"`, `orient="true"`, `offsetX="20"`: point 1 is (100, 0) with direction 90°, and copy 1's centroid is at (100, 20), not (120, 0) (1.2) | 2 px |
| `conformance/cases/srep-0-path-open.xml` | 5 copies on a horizontal segment: centroids at 0, ¼, ½, ¾ and 1 of its length (3.3) | 2 px |
| `conformance/cases/srep-0-path-closed.xml` | 4 copies on a closed square path: centroids at i · L / 4, none doubled at the start (3.3) | 2 px |
| `conformance/cases/srep-0-path-orient.xml` | bars on a circle with `orient="true"`: each bar's extent is that of the tangent direction; with `orient="false"`, of the unrotated bar (3.5, 3.6) | 2 px |
| `conformance/cases/srep-0-path-curve.xml` | copies on a cubic: centroids from the 16-step flattening, not the true curve (3.1) | 2 px |
| `conformance/cases/srep-0-path-degenerate.xml` | `path=""` and `path="M50,50"`: the colour does not appear (0.4, 3.2). `path="M50,50 L50,50"`, count 3: one centroid at (50, 50), bar unrotated (3.7). A path with a zero-length segment before a vertical one: the bar at the start takes the vertical direction (3.5). `count="0"`: the colour does not appear | 2 px |
| `conformance/cases/srep-0-scatter-rect.xml` | `count="1"` for three seeds: centroid equals U(s, 0, 0), U(s, 1, 0) scaled (4.1). Seek-checked | 2 px |
| `conformance/cases/srep-0-scatter-edge.xml` | square region `M0,0 H100 V100 H0 Z`, `seed="14325487974692486532"`, `count="1"`: the copy's centroid is at (0, 60.38), candidate 0 on the left edge, and not at (48.81, 82.09), candidate 1 (4.2, acceptance). Seek-checked | 2 px |
| `conformance/cases/srep-0-scatter-sliver.xml` | region `M0,0 H100 V0.5 H0.5 V100 H0 Z` (99.75 px², 0.9975% of its box), `count="10"`: with `seed="7"` exactly 7 copies are drawn, and with `seed="61"` exactly 6, counted as separate colour blobs (4.2, candidates and result). Seek-checked | 2 px |
| `conformance/cases/srep-0-scatter-fillrule.xml` | region `M0,0 H100 V100 H0 Z M25,25 H75 V75 H25 Z` (two nested squares wound the same way), `seed="7"`, `count="5"`: under `nonzero` a copy is drawn at (30.35, 66.18), inside the inner square; under `evenodd` no copy is drawn inside the inner square and one is at (88.77, 13.93) (4.2, acceptance). Seek-checked | 2 px |
| `conformance/cases/srep-0-vertices.xml` | closed triangle with a curved side: three centroids, none for the closepath; `path="M10,10 M90,10"`: two centroids (5) | 2 px |
| `conformance/cases/srep-0-list.xml` | three pairs: three centroids (6) | 2 px |
| `conformance/cases/srep-0-names.xml` | `scaleX` from `pointU` and from `pointRandom`, `rotation` from `pointAngle`: each copy's extent equals the computed value; `pointRandom` on a `grid` with `seed` differs from the same grid with another seed (0.1); the same frame at two times is identical (7) | 2 px |
| `conformance/cases/srep-0-animate.xml` | `spacingX` keyed 50 → 150 with `timeStep="0.5"`: at mid-time every copy sits on the grid of spacing 100, whatever its delay (8.1, 8.2) | 2 px |
| `conformance/cases/srep-0-nested-time.xml` | an outer counted repeat with `timeStep`, holding an inner repeat with animated `spacingX`: inner grids differ per outer copy by the outer delay (8.3). Seek-checked, with the frames evaluated out of order (8.4) | 2 px |

**What the raster cases do not prove.** The raster cases measure centroids, copy counts and the
difference between fill rules. They do not prove the generator numerically exact: a centroid within
2 px does not show that U is computed bit for bit, or that every coordinate is right to the last
digit. The numeric tests below carry those checks.

**Numeric tests.** These are engine tests in sr-core (SREP 14 rule 6), in two groups.

**Hash tests** call the hash and the unit draw directly. U discards the low 11 bits of the hash, so
no copy transform can verify all 64; these tests compare the full values exactly.

| Test | Expected |
|---|---|
| Hash | splitmix64 chain for (s, c, k) = (0, 0, 0) is `0x238275bc38fcbe91`; for (7, 0, 0), `0xd3c8201d52fd2df4`; for (7, 1, 0), `0x7a099dad0dd482f0`; for (14325487974692486532, 0, 0), `0x0` |
| Unit draw | U(0, 0, 0) = 0.13870941014555427; U(7, 0, 0) = 0.8272724219886994; U(7, 1, 0) = 0.47670922732307197; U(14325487974692486532, 0, 0) = 0 exactly |

**Transform tests** run on the evaluated copy transforms and expression values, before
rasterisation. Counts and candidate indices are compared exactly; coordinates to 10⁻⁹ px.

| Test | Expected |
|---|---|
| `pointRandom` | seed 7: copy 0 reads U(7, 2, 0) = 0.5407366383275906; copy 5 reads U(7, 2, 5) = 0.356758657594873 |
| Rectangle scatter | seed 7, 100 × 100, point 0 = ((0.8272724219886994 − 0.5) · 100, (0.47670922732307197 − 0.5) · 100) |
| Edge acceptance | square `M0,0 H100 V100 H0 Z`, seed 14325487974692486532, count 3: accepted candidates are j = 0, 1, 2; point 0 = (0, 60.38343622198615) |
| Sliver count and order | region `M0,0 H100 V0.5 H0.5 V100 H0 Z`, count 10: seed 7 accepts j = 77, 81, 90, 149, 299, 490, 592 (n = 7); seed 1 accepts 4; seed 42 accepts 5 |
| Candidate bound | the same region, seed 61, count 10: accepts j = 40, 115, 164, 315, 437, 464 (n = 6). Candidate j = 640, at (0.42830310767921764, 10.420086475479973), is inside the region and MUST NOT be tried: an engine that tries it returns 7 points. (Seed 7 cannot show this: its candidate 640 is outside.) |
| Fill rule | region `M0,0 H100 V100 H0 Z M25,25 H75 V75 H25 Z`, seed 7, count 5: `nonzero` accepts j = 0, 1, 2, 3, 4; `evenodd` accepts j = 0, 1, 3, 4, 5 |
| Transform order | the copy transform of `srep-0-order.xml` maps the origin to (100, 20) |
| Degenerate paths | n = 0 for `path=""` under `along-path`, path-based `scatter` and `vertices` (`grid` and `list` ignore `path`, so an empty one does not remove their copies), and for movetos only under `along-path` and `scatter`. For `scatter` only, n = 0 when bw = 0 or bh = 0; a vertical or horizontal path stays valid for `along-path` and `vertices`, as in `srep-0-order.xml` |

**Validation tests** run the XSD and Schematron on four documents: a repeat with `points` and
(a) neither `@from` nor `@step`, (b) `from="0" step="1"`, (c) `from="1"`, (d) `step="2"`; each of (a)
to (d) once with the XSD's defaults inserted before the Schematron and once without. (a) and (b) MUST
validate and (c) and (d) MUST fail C80, the same in both orders.

The expected values above were computed from the definitions in this SREP with an independent script,
not taken from an engine.

## Open issues

- **Rule and pattern ids.** V10, C74–C80, p68 and p69 follow the highest ids in SREPs 15–23 as drafted.
  The editor assigns the final ones.
- **Reference implementation and cases.** Neither exists yet. A Rust branch and the cases above, with
  expected values generated by `make_cases.py`, are required before Review (SREP 0, Lifecycle 3).
- **`floor` in expressions.** D25 lists `floor` as a bare name; the reference engine's current build
  accepts `Math.floor` and rejects `floor`. The grid in Motivation was run with `Math.floor`. This is
  outside this SREP and needs an engine fix or a ruling.
- **`@over` together with `points`.** Placing data rows on generated points (row i on point i) is useful
  and excluded here by C17. It needs a rule for unequal lengths.
- **The unit draw.** SREP 14 rule 2 expects a Semantics SREP on random streams to define derived draws.
  If that SREP lands first, U here should be its unit draw, and the channel numbers 0, 1 and 2 its
  channel allocation.
- **Relative lengths.** `spacingX`, `width` and the others are plain pixels. Whether they should take
  `lengthType` (`%`, `vw`, `vh`) as node positions do.
- **Coverage of a path region.** Whether returning fewer than `count` points (4.2) should be reported
  through the render report of SREP 18.
- **Corpus validation** of the amended C17, as under Backwards compatibility.

## References

- [SREP 0](srep-0000.md): design rules, versioning, compatibility kit.
- [SREP 7](srep-0007.md): D17 (repeat), D21 (motion paths), D24 (noise and hash), D25 (expressions),
  convention 5.19.
- [SREP 12](srep-0012.md): roadmap items G1 (scattering) and MF5 (fields).
- [SREP 14](srep-0014.md): design rules for procedural and random values.
- [SREP 16](srep-0016.md): `pointListType`.
- [SREP 18](srep-0018.md): render reports and inert-attribute findings.
- OpenUSD, `UsdGeomPointInstancer`.
- glTF 2.0, `EXT_mesh_gpu_instancing`.
- Lottie 1.0, shape repeater.
- Steele, Lea, Flood 2014, "Fast Splittable Pseudorandom Number Generators", OOPSLA (splitmix64).
- Bridson 2007, "Fast Poisson Disk Sampling in Arbitrary Dimensions", SIGGRAPH sketches.

## History

- 2026-10-01: first draft.
- 2026-10-01: revised after review. Edge acceptance fixed by a half-open winding rule (4.2); candidate
  bound stated as 0 ≤ j < 64 · count; `id`, `type` and `seed` made common to all types (0); points
  computed once at the repeat's time, before `timeStep` (8); `@from` and `@step` rejected with `points`
  (C80); empty and zero-length paths defined; Motivation corrected to what the baseline already does;
  numeric tests and five raster cases added.
- 2026-10-01: second review. C80 tests values instead of presence, so inserted XSD defaults do not trip
  it; candidate-bound test moved to seed 61, where candidate 640 is inside the region; fill-rule case
  and test added; hash tests separated from transform tests; zero-size box limited to scatter; the
  sliver's area corrected to 0.9975%.
- 2026-10-01: third review, wording only. Empty `path` limited to the types that read it; the rationale
  on `@from` and `@step` matched to C80; the note on what raster cases prove corrected.
