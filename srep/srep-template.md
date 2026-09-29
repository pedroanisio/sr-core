```
SREP:            <number; the editor assigns it, use 0 while drafting>
Title:           <imperative, under 60 characters: "Define camera shake units">
Author:          <name, contact>
Status:          Draft
Type:            Standards | Semantics | Process | Informational
Created:         <YYYY-MM-DD>
Schema-Version:  <target, e.g. 1.2; n/a for Process and Informational>
Requires:        <SREP numbers this depends on, or omit>
Replaces:        <SREP numbers this supersedes, or omit>
Discussion:      <link to the issue or thread, or omit>
Resolution:      <filled in by the editor: date, decision, one-line reason>
```

# SREP <n> — <Title>

## Abstract

<Three to five sentences. What changes, for which elements, and what a document author sees.>

## Motivation

<The problem, with evidence. Name the scene, video or case that shows it, and what each engine does today.
Show a difference from the baseline (Rust) as a measurement (PSNR, pixel offsets, times), not a description.>

## Specification

<The normative part: RFC 2119 words, engine-neutral wording, all units, axes and order of operations given.
A reader must be able to implement it from this section alone.>

### Syntax

```xml
<!-- XSD fragment: the complete new or changed declarations, with defaults, as they will read in sr-core/schema/ -->
```

```xml
<!-- Schematron rules: cross-field constraints and the version gate, or "None." -->
```

### Semantics

<Formulas, not prose, wherever a number is computed. Give every constant exactly. For randomness, give the
exact function of project/@seed, the element seed and time (for example, noise seeded by splitmix64 of the seeds and the lattice index).>

### Defaults and the neutral case

<Show that omitting every new attribute renders what the document rendered before. If it doesn't, say why,
and repeat it under Backwards compatibility.>

## Rationale

<Why this design. Argue in the order of SREP 0: the baseline (its conventions and declared defaults), then
Accepted SREPs, then external precedent with section references (SVG 2, CSS, glTF, OpenUSD, After Effects),
then the scenes in use that the change affects.>

## Rejected alternatives

<Each option considered and the reason it lost. Keep the losing arguments that would otherwise come back.>

## Backwards compatibility

<Is every document valid under the previous version still valid? Does any valid document render differently from the baseline?
If so, list the known affected scenes and the migration. State the version gate: does the change require
version="1.N"?>

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | <branch or commit of the reference implementation> | <what changes> | <issue> |
| C (`c-scene-render`) | exact / sized / pending / n/a | <what changes; size in files or days> | <issue> |
| Python (`py-render`) | | | |
| JavaScript (`js-render-engine`) | | | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `conformance/cases/srep-<n>-<slug>.xml` | <what is measured: positions, colours, edge shift, event times> | ≥ 40 dB against the Rust reference render, or <stated> |

<Every normative sentence in Specification is covered by at least one case. Say which case covers which
sentence when it isn't obvious.>

## Open issues

<Questions to settle before Accepted. Empty when Accepted.>

## References

<Specs, papers, precedent, prior SREPs, D-definitions and rulings this builds on.>

## History

- <YYYY-MM-DD>: first draft.
