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

D21 says that a motion path is flattened "each curve command in 16 equal parameter steps". [SREP 26](srep-0026.md)
(along-path points) and [SREP 16](srep-0016.md) (curved connectors) refer to that rule.

The Rust reference measures motion paths, and since gap-B's branch along-path points too, another way:
- a table of 32 samples per piece, taken on the true curve;
- positions evaluated on the true curve, not on a polyline.

On two more points the reference's motion paths also disagree with the text, and with its own along-path points:
- they count the jump between subpaths as length;
- they take the incoming direction at an exact vertex.

This draft:
- states the reference's measure exactly;
- names the parameter of an arc, which no text names today;
- asks the owner for two decisions:
  - **choice 1**: the measure, polylines of 16 steps (A, the text) or a 32-sample table on the true curve (B, the
    reference);
  - **choice 2**: jumps and vertices, motion paths follow the text (i) or the text follows motion paths (ii).

The Specification gives both sides of each choice, so each choice is a deletion.

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

None of these names the parameter of an arc, or says how a quadratic is stepped. "Exactly as a path shape is" names no
rule an engine can follow: the reference draws path shapes with an adaptive tolerance.

### What the Rust reference does

Read in `rs-scene-render`, `crates/sr-eval/src/path.rs` and `points.rs`, on `gap/srep-26-points` at f53ea6b. There,
gap-B moved along-path points onto the motion-path measure (commit 9bca606) and documented the remaining differences at
`arc_table` (f53ea6b).

**Pieces** (`segments_of`, shared by motion paths and along-path points): the path becomes lines and cubic Béziers.
- `L`, `H` and `V` give one line each. `C` and `S` give one cubic each.
- `Q` and `T` give one cubic by degree elevation, with controls a + ⅔(q − a) and p + ⅔(q − p). This keeps the curve
  and its parameter.
- `A` uses the centre form of SVG 1.1 F.6.5, with the radii corrected by F.6.6 (`arc_shape`):
  - nothing when the end equals the start;
  - one line when rx or ry is 0;
  - otherwise n = max(1, ⌈|Δθ| / (π/2) − 10⁻⁹⌉) cubics of equal sweep δ = Δθ / n, with handles k = 4/3 · tan(δ/4);
    the last cubic ends exactly on the end point.
- `Z` adds a closing line only when the current point differs from the subpath's start.
- A motion path with no pieces becomes one zero-length line at the last point.

**Measure** (`arc_table`, `locate`):
- Every piece, line or cubic, is sampled at `SAMPLES = 32` equal parameter steps, t = k/32, **on the true curve**.
- The table holds the cumulative chord length between consecutive samples, with the piece and parameter of each
  sample. The total is the drawn length L.
- For a target length ℓ, the two table entries around it are found, the parameter is interpolated linearly between
  them, and **the exact curve is evaluated at that parameter**. The point lies on the true curve, not on the 32-sample
  polyline, so drawn length is chord length while the point is on the curve.
- **Without `constantSpeed`** (motion paths), each piece takes an equal share of progress (an arc counts as its n
  cubics), and the point is the exact curve at the share's parameter.

**The two remaining differences** (as f53ea6b documents them):
- **Jumps.** Motion paths build the table with no restart: the first sample of a new subpath is measured from the end
  of the previous one, so **the jump counts as length.** For `M0 0 L10 0 M100 0 L110 0`, L = 110 instead of 20. While progress crosses the jump's 90.3125, the parameter runs only over the first 1/32 of the next piece, so the node holds at (100, 0) to (100.3125, 0): it waits at the next subpath's start for the jump's share of the time.
  Along-path restarts the table at every subpath, so jumps take no length there.
- **Vertices.** At an exact vertex, the entry found belongs to the piece that ends there, so `MotionPath::sample` takes
  **the incoming direction**. A zero-length line has the tangent (0, 0) and gives **0°**. Along-path takes the outgoing
  direction and skips zero-length segments, as SREP 26, 3.5 says.

**Curved connectors** (SREP 16, 3.6) are flattened in 16 steps per curve, as that SREP states.

### Numbers

Drawn length of the semicircle `M-100 0 A100 100 0 0 1 100 0`. The true length is πr = 314.1593.

**Method.** Each value is computed in binary64 by a transcription of `arc_shape`/`arc`, `segments_of` and `arc_table`.
The SVG arc is converted to its two cubics from the end points, as the code does. Then the chords between equal
parameter samples of each piece are summed. Nothing here is measured on a render.

| Rule | L | Error |
|---|---|---|
| the reference today, motion path and along-path (choice B): 2 cubics, 32 chords each | 314.1718 | +0.0125 |
| choice A: 2 cubics, 16 chords each | 314.0770 | −0.0823 |
| D21 read with an arc as one command: 16 equal steps of θ | 313.6548 | −0.5045 |
| for reference: the exact length of the two cubics (10⁵ chords) | 314.2033 | +0.0440 |

The two cubics lie slightly outside the circle, since a quarter-circle cubic has a radial error of up to 0.027 % of r.
Their length therefore exceeds πr, and the 32-chord sum lies between the circle and the cubics.

An estimate of "about 314.15" for the reference, given in review, is not reproduced by this method. The figure above
is the one the code's formulas give.

## Specification

### Semantics

This draft replaces D21's **Geometry**, **Speed** and **At a vertex** items, clause 3.1 of SREP 26, and clause 3.6 of
SREP 16. Items marked **[A]**, **[B]**, **[i]** or **[ii]** belong to one side of a choice; the owner deletes the
other.

**1. Pieces.** The path data is parsed as SVG path data (SVG 2, §9.3) into subpaths of pieces (lines and cubic
Béziers), in command order:
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
     - its controls are P(θⱼ) + k·P′(θⱼ) and P(θⱼ₊₁) − k·P′(θⱼ₊₁), with k = 4/3 · tan(δ/4) and P′ = dP/dθ;
     - the last piece ends exactly on the command's end point.
6. `Z`/`z` adds a line back to the subpath's start, only when the current point differs from it.
7. A subpath without pieces (a lone moveto) is not part of the path. A motion path with no pieces holds the node at the
   last moveto, with direction 0.

**2. Length and position (choice 1).**
- **[A] Polylines.** Each cubic is the polyline through B(i/16), i = 0 … 16; a line is one segment.
  - L is the sum of the segment lengths, and positions are on the polyline.
  - Under `constantSpeed` the point is at drawn length p·L.
  - Without `constantSpeed`, piece m of N takes progress [m/N, (m+1)/N); at s = N·p − m the point is the polyline's
    point of parameter s.
- **[B] The 32-sample table on the true curve.**
  - Each piece is sampled at t = k/32, k = 0 … 32. L is the sum of the chords between consecutive samples.
  - For a target length ℓ, the parameter is interpolated linearly between the two samples whose cumulative lengths
    bracket ℓ, and the point is **the exact curve at that parameter**.
  - Without `constantSpeed`, piece m of N takes progress [m/N, (m+1)/N); the point is the exact curve at
    s = N·p − m.

**3. Jumps and vertices (choice 2).**
- **[i] As the text says** (and as along-path does today):
  - going from one subpath to the next is a jump, with no length and no progress;
  - at a vertex, including a jump, the direction is that of the next segment of non-zero length;
  - segments of zero length have no direction and are skipped; where none follows, the direction is that of the last
    segment of non-zero length.
- **[ii] As motion paths do today:**
  - a jump counts as length: the chord from the last point of a subpath to the next subpath's first sample. While
    progress crosses it, the node holds at the next subpath's start (it moves only through that piece's first sample
    interval);
  - at an exact vertex the direction is the incoming segment's;
  - a zero-length segment has direction 0.

**4. Uses.**
- A motion path (D21), along-path points (SREP 26, 3.1 to 3.7), path regions (SREP 26, clause 4) and curved
  connectors (SREP 16, 3.6) all measure their paths by clauses 1 to 3.
- SREP 26, clause 5 (`vertices`) is unchanged: one point per drawing command, so an arc gives one vertex, not one per
  piece.

### Defaults and the neutral case

No syntax changes. Paths made only of lines, in one subpath, through no exact vertex, draw as today under every
choice.

No kit case changes. `srep-0026-path-open`, `srep-0026-path-closed` and `srep-0049-motion-path-additive` use lines in
one subpath, and their sample points are not at vertices.

## Rationale

- **One measure.** SREP 26's rationale is that "a node on a `motionPath` and a copy placed `along-path` at the same
  fraction land on the same pixel". The reference now shares the table between the two; clause 3 decides the rest.
- **The conversion to pieces is common to both sides.** Quarter-turn pieces make an arc's steps 5.6° (A) or 2.8° (B),
  where D21 read with an arc as one command gives a full circle steps of 22.5°.
- **θ as the arc parameter** is the parameter every implementation of SVG 1.1 F.6.5 computes.
- **Choice 1:**
  - **[A]** keeps D21's and SREP 16's 16 steps, and every length is a polyline length. The point lies off the true
    curve by at most max|B″|/2048, with max|B″| ≤ 6·max(|P₀ − 2P₁ + P₂|, |P₁ − 2P₂ + P₃|). For a quarter circle of
    r = 100 that bound is 0.13 px.
  - **[B]** keeps what the reference draws, for motion paths and now for along-path points. Its length error is the
    smallest of the three, and points lie on the curve. Connectors (SREP 16) would change from 16 steps.
- **Choice 2:**
  - **[i]** is what D21 and SREP 26 already say, and what along-path does. It fixes a motion path that stops at a jump for a time
    the author did not ask for.
  - **[ii]** keeps existing motion paths with several subpaths exactly as they render. It changes along-path and
    SREP 26, 3.5.
  - The draft's author leans to [i]: no text supports [ii], and a jump that takes time is the visible symptom.

## Rejected alternatives

- **Adaptive flattening with a tolerance, as path shapes are drawn.** The result would depend on the drawing scale,
  and points must be a function of the document alone (SREP 26, Rationale).

## Backwards compatibility

No document changes validity.

**Choice 1:**
- **[A]:** motion paths and along-path points through curves move to the polyline, a sub-pixel change at the kit's
  sizes (bound above).
- **[B]:** curved connectors move from 16-step polylines to the table.

**Choice 2:**
- **[i]:** motion paths with several subpaths stop spending time in the jumps, and at exact vertices they take the
  outgoing direction.
- **[ii]:** along-path points on paths with several subpaths move.

No kit case changes. The reference's unit tests of the side that moves change with it.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | partial | One table already serves motion paths and along-path (`gap/srep-26-points`). [A]: positions from 16-step polylines. [B]: connectors onto the table. [i]: motion paths restart the table at each subpath and take the outgoing direction. [ii]: along-path stops restarting and takes the incoming direction. | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-arc` | `points type="along-path" count="3"` on `M-100 0 A100 100 0 0 1 100 0`, and a motion path on the same arc at p = 0.5: the same point; L = 314.0770 [A] or 314.1718 [B] | 1e-6 (numeric), 1 px (raster) |
| `srep-NNNN-jump` | a motion path `M0 0 L10 0 M100 0 L110 0` with `constantSpeed`, at p = 0.5: at the jump, drawn at (100, 0) [i]; within the first 1/32 of the second line, x = 100.16 [ii] | 1 px |
| `srep-NNNN-vertex` | `M0 0 L100 0 L100 100`, `constantSpeed`, `autoOrient`, at p = 0.5: at (100, 0) with rotation 90° [i] or 0° [ii] | 0.5° |
| `srep-NNNN-not-constant` | `M0 0 L100 0 C100 100 200 100 200 0`, `constantSpeed="false"`: at p = 0.5, at (100, 0); at p = 0.75, at the cubic's parameter 0.5, on the polyline [A] or the curve [B] | 1e-6 |

## Open issues

- **Choices 1 and 2,** for the owner.
- Whether `vertices` (SREP 26, clause 5) should give one point per arc piece. This draft keeps one per command.

## References

- [SREP 16](srep-0016.md), 3.6; [SREP 26](srep-0026.md), clauses 3 to 5 and Rationale; [SREP 49](srep-0049.md);
  [DEFINITIONS.md](../conformance/DEFINITIONS.md) D21.
- rs-scene-render, `crates/sr-eval/src/path.rs` (`segments_of`, `arc_table`, `locate`, `MotionPath::sample`) and
  `points.rs`, branch `gap/srep-26-points` at f53ea6b (9bca606 shares the measure; f53ea6b documents the two
  differences).
- SVG 1.1, Appendix F.6 (elliptical arc implementation notes). <https://www.w3.org/TR/SVG11/implnote.html#ArcImplementationNotes>
- SVG 2, §9.3 (path data). <https://www.w3.org/TR/SVG2/paths.html#PathData>
- The chord bound: on a curve with |B″| ≤ M, a chord over a parameter interval h lies within M·h²/8 of the curve.

## History

- 2026-10-06: first draft.
- 2026-10-06: drafted with AI assistance (Claude Opus 5.5 via Claude Code (worker gap-A), from rs-scene-render's
  `sr-eval/src/path.rs` and `points.rs` on `gap/srep-26-points` at f53ea6b, with corrections from the reviewers
  brave-heart and gap-B). The lengths in Motivation are computed by transcribing the code's formulas, not measured on
  a render. No statement here should be taken for granted without its definition or reference.
