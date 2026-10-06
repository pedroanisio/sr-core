```
SREP:            0
Title:           Measure motion paths and along-path points one way
Author:          scene-render maintainers (drafted by gap-A)
Status:          Draft
Type:            Semantics
Created:         2026-10-06
Schema-Version:  1.3 (no schema change)
Requires:        16, 26
```

# SREP 0 (draft) — Measure motion paths and along-path points one way

## Abstract

D21 says a motion path is flattened "each curve command in 16 equal parameter steps". [SREP 26](srep-0026.md)
(along-path points) and [SREP 16](srep-0016.md) (curved connectors) refer to that rule.

The Rust reference measures motion paths differently, and a node on a motion path and a copy placed `along-path` at
the same fraction do not land on the same point, which SREP 26 promises. They differ in five ways: 32 samples on the
true curve against 16 chords, arcs in quarter pieces against arcs as one command, jumps between subpaths counted as
length, the incoming direction at a vertex, and 0° for a zero-length segment.

This draft states both measurements exactly, names the parameter of an arc (which no text names today), and asks the
owner for one decision: move the motion-path implementation to the text (choice A), or move the text to the
motion-path implementation (choice B). Either choice leaves one rule for all three uses. The Specification gives
both, so the choice is a deletion.

## Motivation

### What the texts say

- **D21, Geometry:** "the path is flattened exactly as a path shape is, each curve command in 16 equal parameter
  steps. A closed subpath includes its closing segment; subpaths follow one another with jumps that take no progress.
  A lone moveto draws nothing and is not part of the path."
- **D21, Speed:** "with `constantSpeed` (the default), p is the fraction of drawn length; otherwise every flattened
  segment takes an equal share."
- **D21, At a vertex:** "the node takes the outgoing segment (its position is the vertex and its direction the next
  segment's)".
- **SREP 26, 3.1:** "`path` is flattened exactly as a motion path is (D21): each curve command in 16 equal parameter
  steps …"
- **SREP 26, 3.5:** "Segments of zero length have no direction and are skipped. At a vertex, including a jump, the
  direction is that of the next segment of non-zero length."
- **SREP 16, 3.6:** "Curves are flattened in 16 equal parameter steps, as for motion paths (D21)."

None of them says what the parameter of an arc is, or how a quadratic is stepped. "Exactly as a path shape is" names
no rule: the reference draws path shapes with an adaptive tolerance.

### What the Rust reference does

Read on `rs-scene-render`, branches `vendor/schema-1.3` and `gap/srep-26-points` (708530c).

**Motion paths** (`sr-eval/src/path.rs`, `MotionPath::parse` and `MotionPath::sample`).

Parsing turns the path into **pieces**: lines and cubic Béziers.
- `L`, `H` and `V` give one line each. `C` and `S` give one cubic each.
- `Q` and `T` give one cubic by degree elevation, with controls a + ⅔(q − a) and p + ⅔(q − p). The parameter is
  unchanged.
- `A` uses the centre form of SVG 1.1 F.6.5, with the radii corrected by F.6.6:
  - nothing when the end point equals the start point;
  - one line when rx or ry is 0;
  - otherwise n = max(1, ⌈|Δθ| / (π/2) − 10⁻⁹⌉) cubics of equal sweep δ = Δθ / n, with handles k = 4/3 · tan(δ/4);
    the last cubic ends exactly on the end point.
- `Z` adds a closing line only when the current point differs from the subpath's start.
- A path with no pieces becomes one zero-length line at the current point.

Measuring and sampling:
- **Length.** Every piece, line or cubic, is sampled at `SAMPLES = 32` equal parameter steps. The table of
  cumulative chord lengths is the drawn length L. A semicircle of r = 100 has 1 + 2·32 samples.
- **Position.** With `constantSpeed`, the target length p·L is found in the table. The parameter is interpolated
  linearly between the two table entries around it, and the node is placed **on the true curve** at that parameter.
- **Without `constantSpeed`,** each piece takes an equal share of progress, an arc counting as its n cubics. The
  position is the true curve at the share's parameter.
- **Jumps.** The table carries the previous sample across a moveto. The first sample of a new subpath is measured
  from the end of the old one, so **the jump counts as length.** For `M0 0 L10 0 M100 0 L110 0`, L = 110 instead of
  20.
- **Direction.** The direction is the tangent of the piece found.
  - At an exact vertex, the table entry at the vertex belongs to the piece that ends there, so the node takes **the
    incoming direction**.
  - A zero-length line has the tangent (0, 0), and gives **0°**.

**Along-path points** (`sr-eval/src/points.rs`, `FlatPath`, SREP 26):
- every curve command is a polyline of `CURVE_STEPS = 16` equal parameter steps;
- **an arc is one command:** 16 equal steps of θ over its whole sweep;
- a `Q` is stepped as a quadratic, which is the same curve and parameter as its degree-elevated cubic;
- jumps take no length;
- at a vertex the point takes the outgoing segment's direction, and zero-length segments are skipped;
- `Z` always adds the line back to the start, which has zero length when the current point is already there.

**Curved connectors** (SREP 16, 3.6) are flattened in 16 steps per curve, as that SREP states.

### The two disagree

Drawn length of the semicircle `M-100 0 A100 100 0 0 1 100 0` (true length πr = 314.1593). The values are computed from
the formulas above, not measured on a render.

| Rule | L | Error |
|---|---|---|
| motion path today: 2 cubics, 32 chords each | 314.1718 | +0.0125 |
| along-path today and D21 as written: 16 steps of θ | 313.6548 | −0.5045 |
| choice A below: 2 cubics, 16 chords each | 314.0770 | −0.0823 |

## Specification

### Semantics

This draft replaces D21's **Geometry**, **Speed** and **At a vertex** items, clause 3.1 of SREP 26, and clause 3.6 of
SREP 16 with the rule below. Items marked **[A]** or **[B]** belong to one choice; the owner deletes the other.

**1. Pieces.** The path data is parsed as SVG path data (SVG 2, §9.3) into subpaths of pieces, lines and cubic Béziers,
in command order. The conversion is the one the reference does today:
1. `M`/`m` starts a subpath; its further coordinate pairs are lines.
2. `L`, `H`, `V` give one line each.
3. `C`, `S` give one cubic each; `S` reflects the previous cubic's second control.
4. `Q`, `T` give one cubic each, by degree elevation: (a, a + ⅔(q − a), p + ⅔(q − p), p). `T` reflects the previous
   quadratic control.
5. `A` gives:
   - nothing when its end equals its start;
   - one line when rx or ry is 0;
   - otherwise n cubics. The arc is parameterised by **θ, the angle of the SVG 1.1 F.6.5 centre form**:
     (x, y) = (cx, cy) + R(φ)·(rx cos θ, ry sin θ), θ from θ₁ over Δθ, with the radii corrected by F.6.6. Then:
     - n = max(1, ⌈|Δθ| / 90° − 10⁻⁹⌉), and piece j covers θ ∈ [θ₁ + jδ, θ₁ + (j+1)δ] with δ = Δθ / n;
     - its controls are P(θⱼ) + k·P′(θⱼ) and P(θⱼ₊₁) − k·P′(θⱼ₊₁), with k = 4/3 · tan(δ/4), P′ = dP/dθ;
     - the last piece ends exactly on the command's end point.
6. `Z`/`z` adds a line back to the subpath's start, only when the current point differs from it.
7. A subpath without pieces (a lone moveto) is not part of the path.

**2. Length and position.**
- **[A] Flattened.** Each cubic is the polyline through B(i/16), i = 0 … 16; a line is one segment.
  - L is the sum of the segment lengths.
  - Positions are on the polyline. Under `constantSpeed` the point is at drawn length p·L.
  - Without `constantSpeed`, piece m of N takes progress [m/N, (m+1)/N); within it, at s = N·p − m, the point is the
    polyline's point of parameter s.
- **[B] True curves.**
  - L is the sum of the chords between 32 equal parameter samples of each piece.
  - Under `constantSpeed` the point is on the piece's true curve, at the parameter interpolated linearly between the
    two samples whose cumulative chord lengths bracket p·L.
  - Without `constantSpeed`, piece m of N takes progress [m/N, (m+1)/N); within it, the point is the true curve at
    parameter s = N·p − m.
- **Either choice:**
  - Going from one subpath to the next is a jump. It has no length and takes no progress.
  - A path with no pieces holds the node at the last moveto, direction 0.

**3. Direction.**
- The direction is the direction of travel, in degrees clockwise from +x.
- At a vertex, including a jump, it is that of the next segment of non-zero length. Segments of zero length have no
  direction and are skipped. Where no such segment follows, it is that of the last segment of non-zero length.
  (This is SREP 26, 3.5, made D21's for motion paths too.)

**4. Uses.**
- A motion path (D21), along-path points (SREP 26, 3.1 to 3.7), path regions (SREP 26, clause 4) and curved
  connectors (SREP 16, 3.6) all measure their paths by clauses 1 to 3.
- SREP 26, clause 5 (`vertices`) is unchanged: one point per drawing command, so an arc gives one vertex, not one
  per piece.

### Defaults and the neutral case

No syntax changes. Paths made only of lines draw as today under both choices, except for:
- motion paths with jumps, which are corrected under both choices;
- motion paths through exact vertices, whose direction is corrected under both choices.

No kit case changes: `srep-0026-path-open`, `srep-0026-path-closed` and `srep-0049-motion-path-additive` use lines, and
none of them samples a vertex or a jump.

## Rationale

- **One rule.** SREP 26's rationale is that "a node on a `motionPath` and a copy placed `along-path` at the same
  fraction land on the same pixel". That holds only if the two use one function.
- **The conversion to pieces is the same under both choices.** It is what the reference's motion paths already do, and
  what arc-to-Bézier converters do. Quarter-turn pieces make an arc's 16 steps 5.6° each, where D21 as written gives a
  full-circle arc steps of 22.5°.
- **θ as the arc's parameter** is the parameter every implementation of SVG 1.1 F.6.5 computes.
- **The jump and the vertex** are fixed in both choices. They are deviations from D21 that no text supports.
- **For choice A:**
  - It keeps D21's 16 steps and SREP 16's.
  - Every length is a polyline length, so it agrees with what a renderer draws for a path flattened the same way.
  - A position off the true curve is bounded: a chord of a C² curve at 1/16 parameter steps lies within
    max|B″|/2048 of it, with max|B″| ≤ 6·max(|P₀ − 2P₁ + P₂|, |P₁ − 2P₂ + P₃|). For a quarter circle of r = 100 that is
    0.13 px.
- **For choice B:**
  - It keeps the motion paths of every existing document where they are, apart from the jump and vertex fixes.
  - Its length error is the smallest of the three.
  - Along-path points and connectors change, but no published kit case does.

## Rejected alternatives

- **D21 as written: an arc in 16 steps of θ over its sweep.** It is the coarsest of the three for large arcs (the
  table above), and it disagrees with the conversion both choices share.
- **Adaptive flattening with a tolerance, as path shapes are drawn.** The result would depend on the drawing scale,
  and points must be a function of the document alone (SREP 26, Rationale).

## Backwards compatibility

No document changes validity.

**Choice A:**
- Motion paths through curves move to the polyline, a sub-pixel change at the sizes of the kit (bound above).
- Along-path points on arcs move to quarter pieces: on the semicircle, L goes from 313.6548 to 314.0770.

**Choice B:**
- Along-path points and connector curves change to 32-sample true-curve measurement, and arcs to quarter pieces.

**Both choices:**
- Motion paths with more than one subpath stop counting the jumps.
- At exact vertices, motion paths take the outgoing direction.
- The reference's unit tests of the old rules change with it. No kit case changes.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | one measuring function for `MotionPath`, `FlatPath` and connectors. Choice A: motion paths onto 16-step polylines. Choice B: along-path and connectors onto the 32-sample true-curve table. Both: jumps without length, outgoing direction at a vertex | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-arc` | `points type="along-path" count="3"` on `M-100 0 A100 100 0 0 1 100 0`, and a motion path on the same arc at p = 0.5: the same point. L is 314.0770 under A or 314.1718 under B | 1e-6 (numeric), 1 px (raster) |
| `srep-NNNN-jump` | a motion path `M0 0 L10 0 M100 0 L110 0` with `constantSpeed`: at p = 0.5 the node is at the jump and takes the outgoing segment, so it is drawn at (100, 0) | 1 px |
| `srep-NNNN-vertex` | `M0 0 L100 0 L100 100`, `constantSpeed`, `autoOrient`: at p = 0.5 the node is at (100, 0) with rotation 90° (outgoing) | 0.5° |
| `srep-NNNN-not-constant` | `M0 0 L100 0 C100 100 200 100 200 0`, `constantSpeed="false"`: at p = 0.5 the node is at (100, 0); at p = 0.75, at the cubic's parameter 0.5, on the polyline (A) or the curve (B) | 1e-6 |

## Open issues

- **The choice, A or B,** for the owner.
- Whether `vertices` (SREP 26, clause 5) should give one point per arc piece. This draft keeps one per command.

## References

- [SREP 16](srep-0016.md), 3.6; [SREP 26](srep-0026.md), clauses 3 to 5 and Rationale; [SREP 49](srep-0049.md);
  [DEFINITIONS.md](../conformance/DEFINITIONS.md) D21.
- SVG 1.1, Appendix F.6 (elliptical arc implementation notes). <https://www.w3.org/TR/SVG11/implnote.html#ArcImplementationNotes>
- SVG 2, §9.3 (path data). <https://www.w3.org/TR/SVG2/paths.html#PathData>
- The chord bound: on a curve with |B″| ≤ M, a chord over a parameter interval h lies within M·h²/8 of the curve.

## History

- 2026-10-06: first draft.
- 2026-10-06: drafted with AI assistance (Claude Opus 5.5 via Claude Code (worker gap-A), from rs-scene-render's
  `sr-eval/src/path.rs` and `sr-eval/src/points.rs` on `gap/srep-26-points` 708530c, with corrections from the
  reviewers brave-heart and gap-B). The lengths in Motivation are computed from those formulas, not measured on a
  render. No statement here should be taken for granted without its definition or reference.
