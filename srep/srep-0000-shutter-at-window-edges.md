```
SREP:            0
Title:           Blur a node at the edges of its window
Author:          scene-render maintainers (drafted by gap-A)
Status:          Draft
Type:            Semantics
Created:         2026-10-06
Schema-Version:  1.3 (no schema change)
Requires:        55
```

# SREP 0 (draft) — Blur a node at the edges of its window

## Abstract

A node's motion blur samples it at times spread over the shutter ([SREP 55](srep-0055.md), Semantics). When some of
those times fall outside the node's window, the node does not exist there. This happens before its start, after its
end, and before composition time 0. Nothing says what to do. The Rust reference then draws the node **without blur**
on that frame, so a node that moves from its first frame is sharp on frame 0 and blurred from frame 1.

This SREP says: a sample time outside the node's window is taken at the nearest edge of the window. The node is held in
its pose there, blurred by the motion that happens inside the window, and drawn at full weight.

## Motivation

**What the reference does.** `rs-scene-render`, `crates/sr-gpu/src/render_fx.rs`, `motion_blur`, on
`vendor/schema-1.3`:

```rust
let times: Vec<f64> = (0..count)
    .map(|k| g.time + (pr.shutter_phase / 360.0 + angle / 360.0 * (k as f64 + 0.5) / count as f64) / fps)
    .collect();
let (first, last) = (sub.at(times[0]), sub.at(times[count - 1]));
let (Some(&a), Some(&b)) = (first.index.get(&n.id), last.index.get(&n.id)) else { return false };
```

- `sub.at(t)` evaluates the whole scene at time t.
- A node is in that graph only inside its window, with its ancestors' windows and clocks applied.
- When the node is missing at the first or the last sample, `motion_blur` returns `false`, and the node is drawn once,
  at the frame time, without blur.
- When only samples in the middle are missing (possible only when the node leaves the graph and comes back within
  the shutter), the general path skips them. They then contribute nothing, so the node is drawn at reduced weight.

**Example.** 50 fps, `shutterAngle="180"`, `shutterPhase="-90"` (a centred shutter), a node with `start="0"` moving
from its first frame:
- frame 0 at t = 0: the samples span t ∈ [−0.005, 0.005); the first sample is before 0, so the node is drawn sharp;
- frame 1 at t = 0.02: the samples span t ∈ [0.015, 0.025), so the node is blurred.

The same happens at any node's own start under a negative phase, and at its end when the last sample passes the end.

**Why it matters.** A blur that switches on between the first two frames of a move is visible: a sharp first frame,
then a smear. It is the reverse of what a shutter does.

## Specification

### Semantics

This amends SREP 55, Semantics, and the motion blur of the conventions, for every node with motion blur on.

1. Let t₀, …, t_{N−1} be the shutter's sample times for the node, as SREP 55 defines them.
2. Let [ws, we) be the node's **window** on the composition timeline: the times at which its own window and every
   ancestor's contain the time, with the ancestors' clocks applied (the window that rule I8 of
   [SREP 18](srep-0018.md) tests).
   - The composition's own time range does not bound it.
   - A node with no end has we = +∞.
3. **A node drawn at the frame time** is accumulated over the samples, with each sample time tₖ replaced by
   t′ₖ = min(max(tₖ, ws), we).
   - At t′ₖ = we the node is evaluated as at its last instant: its animated values take their value at we, and the
     window is treated as closed for this purpose.
   - Every sample keeps the weight 1/N.
   - When all t′ₖ are equal, the node is drawn sharp, at full weight.
4. **A node not drawn at the frame time** is not drawn. Samples never make a node visible on a frame outside its
   window.
5. A `condition` that hides the node at some samples is not covered here (Open issues). Until it is, such samples
   are held at the frame time.

### Defaults and the neutral case

A node whose window contains all its sample times renders as before. Only frames near a window edge change.

## Rationale

- **Hold, not drop.**
  - Dropping the samples outside the window, with weight 1/N each, fades the node at its edges: on the example's
    frame 0, to half opacity. That is what a camera would record for an object that appears mid-exposure, but here
    the node is meant to be fully there from its start.
  - Renormalising the remaining samples keeps full opacity, but the blur then covers a shorter interval. The amount
    of blur would then depend on where the window edge falls in the shutter.
  - Holding keeps both the weight and the interval. The node's motion inside the window is all the blur there is.
- **Composition time 0 is not special.** A node's window is what decides whether it exists. Time 0 matters only
  because default windows start there.

## Rejected alternatives

- **The reference's behaviour (no blur on that frame).** It produces the sharp-then-blurred step of the Motivation.
- **Shift the shutter into the window** (move every sample later by ws − t₀). That changes the exposure's phase on
  some frames only, which shows as a jump in the trail's position between frames.

## Backwards compatibility

- No document changes validity.
- **Rendering changes:** nodes with motion blur on frames where a shutter sample falls outside their window. Those
  frames gain the blur of the motion inside the window. Frames whose samples all fall inside the window are unchanged.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending | `motion_blur`: clamp the sample times to the node's window before evaluating; drop the early return for a missing first or last sample | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-shutter-start` | 50 fps, 180°, phase −90: a 20 px square starting at t = 0 and crossing at 1000 px/s (10 px in the 0.01 s a 180° shutter is open at 50 fps). Frame 0 has a trail of 5 px (the half of its shutter after t = 0); frame 1 a trail of 10 px | 1 px |
| `srep-NNNN-shutter-end` | the same square with `end="1"`, phase 0: the last frame before 1 is blurred over the part of its shutter before t = 1, at full opacity | 1 px |

## Open issues

- Samples at which a `condition` hides the node.
- Clocks with time remapping (`timeRemap`, symbols with speed): the window is computed through them, but whether
  "nearest edge" should be taken in composition time or in the node's own time has not been measured.

## References

- [SREP 55](srep-0055.md) (the node's shutter angle and the sample times); [SREP 18](srep-0018.md), rule I8 (the node's
  window on the composition timeline).
- rs-scene-render `crates/sr-gpu/src/render_fx.rs`, `motion_blur`; `crates/sr-gpu/src/render.rs`, `SubFrames::at`.

## History

- 2026-10-06: first draft.
- 2026-10-06: drafted with AI assistance (Claude Opus 5.5 via Claude Code (worker gap-A), from rs-scene-render's
  `motion_blur`). The example's sample times are computed from the formula above; the trail lengths in Conformance are
  derived from it, not yet measured on a render. No statement here should be taken for granted without its
  definition or reference.
