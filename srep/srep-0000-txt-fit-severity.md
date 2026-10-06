```
SREP:            0
Title:           Amend SREPs 18 and 20: report text overflow by what it loses
Author:          scene-render maintainers (drafted by gap-A)
Status:          Draft
Type:            Standards
Created:         2026-10-06
Schema-Version:  1.3 (no schema change)
Requires:        18, 20
```

# SREP 0 (draft) — Amend SREPs 18 and 20: report text overflow by what it loses

## Abstract

[SREP 18](srep-0018.md) registers `TXT-FIT` as a warning: "text does not fit its box at the size drawn". [SREP 20](srep-0020.md),
rule 6, makes the measure "a block taller than its box". Strict delivery counts every warning, so text that overflows
its box by a fraction of a pixel of line box, while its glyphs sit well inside and nothing is lost, fails a production
encode.

This amendment:
1. sets `TXT-FIT`'s severity by what the overflow costs: `info` when the text is drawn whole inside the frame, `warning`
   when it is cut (clipped to its box, or reaching out of the frame). The Rust reference does this since the ruling of
   2026-10-06.
2. proposes, as a separate decision, that the overflow be measured on the glyphs' ink, not on the line box, with a
   1 px tolerance.

## Motivation

On 2026-10-06, under the strict rule (every warning or error fails), the four recent production films were encoded one
frame each with the reference's report, and their text was audited over the whole timeline (≤ 240 sampled frames):

- three films raised no text finding;
- `eleicoes-2026-portrait` raised six `TXT-FIT` warnings and would fail strict delivery:
  - four text layers of size 64 in a 76 px box: the default `lineHeight` 1.2 makes a 76.8 px line box, 0.8 px over;
    the digits themselves, about 45 px tall, are far inside;
  - one layer whose advances are 1.0 px wider than its box;
  - one large title ("2026", size 300, `wrap="none"`) whose advances reach 43 px past its box, drawn whole, inside the
    frame.

All six follow SREP 20 rule 6 to the letter. None loses anything: the overflow is `visible`, and the film was approved
as rendered. A delivery gate that rejects them is measuring the box an author typed, not the picture.

## Specification

### Semantics

**1. Severity (amends SREP 18, Specification 4, row `TXT-FIT`).**

| Code | Severity | Finding |
|---|---|---|
| `TXT-FIT` | `info` or `warning` | text does not fit its box at the size drawn (after `autoFit`); `measured` in px. `info` when the text is drawn whole and inside the frame. `warning` when it is cut: drawn with `overflow="clip"`, or its block reaching out of the frame, `measured` then being the clipped overflow or the distance out of the frame |

- "Out of the frame": a line box of the block, placed as the text is drawn (its layer's content placement, then the
  node's world transform), reaches outside the output's frame [0, width] × [0, height].
- `TXT-CUT` (characters dropped by `maxLines` or `overflow`) is unchanged: a warning.

**2. Ink measure (proposal, amends SREP 20 rule 6; for the owner).** "With a render report, the overflow of a block is
how far the **ink** of its glyphs (their outlines' bounds, at the size drawn, with `letterSpacing` and `tracking`)
reaches past the box, and a `TXT-FIT` is reported only when it exceeds **1 px**." Under this measure, the four line-box
overhangs above vanish; the 1.0 px advance case falls under the tolerance; "2026" is still
reported if its ink, like its advances (43 px), reaches more than 1 px past the box (not measured).

### Defaults and the neutral case

Findings never change pixels.

## Rationale

- **Severity by loss** keeps one rule for strict delivery (warnings and errors fail, information does not), and puts
  every overflow in the report, so an author still sees it.
- **Ink, not line box,** for the measure: the line box is a layout construct whose overhang an author cannot see; the
  ink is what the frame shows. A tolerance of 1 px absorbs anti-aliasing and hinting differences between engines.

## Rejected alternatives

- **Thresholds on the line-box overflow** (for example, ignore under 2 px). It still reports invisible line boxes and
  misses large ink overflow on tight boxes.
- **Fixing the films' boxes.** It works for these six, and every future scene with a tight box fails again.

## Backwards compatibility

No validity or picture changes. Reports change severity for visible-inside-the-frame overflow; with clause 2, fewer
`TXT-FIT` findings are reported at all.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | clause 1 implemented on `gap/srep-18-render-reports`; clause 2 pending | clause 2: measure glyph outline bounds per line instead of the line box | |

## Conformance

| Case | Checks | Expected |
|---|---|---|
| `srep-NNNN-txt-fit-overhang` | size 64 in a 76 px box, inside the frame | `TXT-FIT` at info, measured 0.8 (clause 1); no finding (clause 2) |
| `srep-NNNN-txt-fit-clipped` | one 30 px line in a 20 px box with `overflow="clip"` | `TXT-FIT` at warning, measured 10 |
| `srep-NNNN-txt-fit-off-frame` | a 90 px block at y = 100 of a 120 px frame | `TXT-FIT` at warning, measured 70 |

## Open issues

- Clause 2, for the owner.
- Whether a `cover` or crop placement that clips the text inside its layer box is "cut" too. The reference does not
  count it yet.

## References

- [SREP 18](srep-0018.md), Specification 4 and its Resolution (information is not counted by strict delivery);
  [SREP 20](srep-0020.md), rule 6.

## History

- 2026-10-06: first draft.
- 2026-10-06: drafted with AI assistance (Claude Opus 5.5 via Claude Code (worker gap-A), from the strict-delivery
  measurement of four production films with the Rust reference's integration build). No statement here should be taken
  for granted without its definition or reference.
