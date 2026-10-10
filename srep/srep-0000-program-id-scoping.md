---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Opus 5.5 via Claude Code (fix wave agent srep-ids-draft), from SREP 66 on sr-core accept/66-83 (380eee5), the Rust reference at rs-scene-render b51000f7 and the atlas v2 ENGINE_FINDINGS"
  date: "2026-10-10"
---

```
SREP:            0
Title:           Amend SREP 66: scope emitted ids by their program
Author:          scene-render maintainers (drafted with Claude Opus 5.5)
Status:          Draft
Type:            Semantics
Created:         2026-10-10
Schema-Version:  1.6
Requires:        57, 59, 66
```

# SREP 0 (draft) — Amend SREP 66: scope emitted ids by their program

## Abstract

SREP 66 puts the ids that a `<program>` emits into the document's id space unchanged, so two programs that emit the
same id, or one module used twice, fail with PRG14. This SREP gives each program its own id scope: an id `E` emitted by
the program whose id is `P` becomes `P.E` in the document, and the references inside the output that name `E` are
resolved to `P.E`. A reference that names a bare emitted id from anywhere else still resolves when exactly one
program emitted that id, with the new warning W13. When several programs emitted it, the new error PRG17 applies. The XSD
and the Schematron do not change. Every document that SREP 66 accepts renders the same pixels, and some documents
that SREP 66 refuses become valid.

## Motivation

- **SREP 66 leaves this open.** Under "Open issues", item "Id scoping", it says: "Two programs that emit the same ids
  collide (PRG14). Prefixing emitted ids with the program's id (`p.g1`) would allow a program to be reused, but
  references inside the fragment would then need rewriting."
- **The atlas v2 build hit it twice** (`atlas-v2-scene-render/ENGINE_FINDINGS.md`, internal):
  - Finding 11: "an emitted node whose id equals a paint or asset id fails with PRG14/S09 (e.g. a shape called `blade`
    vs a gradient `blade`)".
  - Limitations: "two programs (or one module run twice with different params) that emit the same ids fail at render
    with PRG14/S09 although `validate` reports the document valid (programs are not run by `validate`).
    Workaround: per-part id prefixes (cell 40)."

  Today a module therefore has to know every id in every document that will use it. A module cannot know that,
  because SREP 66 Semantics 1 gives it no access to the rest of the document.
- **What the reference does today** (rs-scene-render `b51000f7`, `crates/sr-model/src/program.rs`,
  `crates/sr-model/src/document.rs:460-500`):
  - It splices each output into the document text unchanged and validates the result again.
  - Every error of that second validation is reported as PRG14 at the program.
  - Its test `failures_carry_their_codes` (`crates/sr-model/tests/program_build.rs`) and the kit case
    `srep-0066-program-id-collision` both expect PRG14 for a document `<shape id="g1">` placed beside a program
    whose module (`srep66-rect.wasm`) emits `g1`.

## Specification

### Syntax

```xml
None (XSD).
```

```xml
None (Schematron). A Schematron validator does not run programs, so it cannot see their output.
```

### Semantics

These rules replace the two sentences of SREP 66 Semantics 5 that read "Emitted ids share the document's id
space. An emitted id equal to any other id in the document is an error." (See "Amended text of SREP 66" below.)
They apply to programs in build mode inside the composition. Data programs (SREP 66 Semantics 6) emit JSON, and step-mode
programs (SREP 69) emit pixels. Neither emits ids, so neither is affected.

Notation:

- `P` is the value of the program's `id`. `nodeCoreAttributes` requires it, so every program in the composition has one.
- `O(P)` is the output of `P`, parsed as the XML fragment of SREP 66 Semantics 5.
- The **local ids** `L(P)` are the values of every attribute of type `xs:ID` on any element of `O(P)`, at any depth.
- `a.b` is the concatenation of the string `a`, the character `.` (U+002E) and the string `b`.

**1. Local ids are unique.** Two equal values in `L(P)` make the output invalid. The engine MUST fail with **PRG14**.

**2. Namespaced ids.** Each attribute of type `xs:ID` in `O(P)` whose value is `E` takes the value `P.E` in the document.
`P.E` is an `NCName`, and therefore a valid `xs:ID`:

- `P` and `E` are NCNames.
- `.` is a `NameChar`.
- An NCName is a `Name` without `:`, so `P.E` begins with the `NameStartChar` that begins `P` and contains no `:`.

The engine MUST fail with **PRG14** when `P.E` equals any other id in the document. That other id may be written in
the document or produced by another program. One example is program `a` emitting `b.c` beside program `a.b` emitting
`c`, since both produce `a.b.c`.

**3. References inside the output resolve locally first.** Inside `O(P)`, a reference to the id `R` resolves to `P.R`
when `R ∈ L(P)`. Otherwise it resolves by the rules for references from outside (4). The positions this rule covers
are:

1. every token of an attribute of type `xs:IDREF` or `xs:IDREFS`;
2. the id part of the string-literal argument of `prop("id.property")` and `propAtTime("id.property", t)`. The id
   part is everything before the **last** `.` of the literal, and the property is everything after it.

Rule 3 never applies to the following positions, which keep their present resolution:

- the `url(#id)` paint reference of `paintType` and the `#id` material-map reference of SREP 71. These name paints and
  assets, which cannot occur in a program's output (SREP 66 Semantics 5 admits only `nodeChoice` elements);
- the marker references, which have type `xs:NCName` under SREP 57;
- `override/@target` inside an emitted `instance`, which resolves in the instance's scope (`instanceType`);
- `param(name)`, the `{{name}}` and `{{name.field}}` placeholders and repeat variables, which name parameters and
  variables, not elements.

**4. Bare references from outside.** This rule covers three kinds of reference to the id `R`:

- a reference outside every program's output, at one of the positions of rule 3 or at `override/@target` of a `layout`
  or a `variant`;
- a reference inside `O(P)` that rule 3 did not resolve;
- a reference inside `O(P)` that names an id another program emitted.

Such a reference resolves as follows:

- if `R` is an id of the document after rule 2, it resolves to that element;
- otherwise, let `M` be the set of programs `Q` with `R ∈ L(Q)`:
  - if `M = {Q}`, the reference resolves to `Q.R`. A validator or engine SHOULD warn **W13**, naming the reference and
    `Q.R`;
  - if `M` has two or more programs, the engine MUST fail with **PRG17**, naming the reference and the programs in `M`;
  - if `M` is empty, the reference is unresolved, and the error that its position already defines applies (for
    example S10 for an `xs:IDREF`, E05 for an override target, and a compile error for `prop`).

A reference written in full, such as `prop("p.g1.x")`, is an id of the document and resolves without a warning.

**5. Order.** The document is validated with every reference resolved by rules 3 and 4. That means an engine that
rewrites references does so before the validation of SREP 66 Semantics 5, and the identity constraints of SREP 59 then
hold for the rewritten document. The program's group keeps the id `P`, so the group `P` is the parent of `P.E`.

**6. The output bytes do not change.** The output digest (`outputSha256`, PRG15) and the cache key (SREP 66, Determinism
6) are computed over the bytes the module returned, before rules 1 to 5. Renaming a program therefore changes neither of them.

**7. Values derived from ids use the local id.** Where the format derives a value from an element's id, an element
emitted by a program uses its local id `E`, not `P.E`. Two such derivations are known to the drafter:

- the per-element seed, CRC-32 of `"project seed:id:@seed:purpose"` (the baseline; described in SREP 12, F1;
  `crates/sr-vector/src/d24.rs`, `element_seed`);
- the cell seed of SREP 80, the FNV-1a-64 hash of the owner's id.

Because of this rule the picture of a program's output depends only on the output, as its cache key already does, and
renaming the program does not change its pixels.

**8. Scopes compose.** A program inside a `symbol` is expanded where it is written, so its namespaced ids are the
symbol's inner ids. The instance scoping of `instanceType` then applies to them, which makes the effective id
`instanceId/P.E`. The `/` of instance and `include` scoping is not a `NameChar`, and the `.` of this SREP is, so the
two separators cannot be confused.

### Hazards of the `.` separator (normative where stated)

- **`prop` and `propAtTime` split on the last `.`.** The schema annotation of `expressionType` writes
  `prop("id.property")` without saying which `.` separates the two parts. This SREP makes the last `.` normative
  (Semantics 3). Property names never contain a `.`: they are attribute names or the aliases `position`, `scale`,
  `anchor` and `skew`. This is what the reference already does (`crates/sr-eval/src/program.rs:3323`, `rsplit_once('.')`). An
  engine that splits on the first `.` would read `prop("p.g1.x")` as the property `g1.x` of `p`, which is wrong.
- **Names that are split on the first `.`.** `param(name)`, `{{name.field}}` and repeat-variable fields split on the
  first `.` (`crates/sr-eval/src/eval.rs:685,700`; `crates/sr-eval/src/program.rs:749,1710`). They never name elements,
  so a namespaced id never reaches them. A later SREP that lets one of them name an element MUST split on the last `.`.
- **Generated marker ids (`beat.N`, `bar.N`).** SREP 57 tests a generated id by what follows its **first** `.`, which must be
  1 to 19 decimal digits (its test `G(x)`, and the reference's `marker_time`, `split_once('.')`). In `P.E`, the
  text after the first `.` contains `E`, whose first character is a `NameStartChar` and so never a digit (XML 1.0 §2.3,
  production [4]). The text after the first `.` therefore always contains a non-digit, and no namespaced id has the
  generated form. This holds even when `P` is `beat` or `bar`. Markers are also not `nodeChoice` elements, so a
  program cannot emit one.

### Errors and warnings

| Code | When | Stage |
|---|---|---|
| PRG14 | (amended) as in SREP 66, except that an emitted id no longer collides by its local value. Two equal local ids in one output (1), or a namespaced id equal to another id (2), fail. | build (output) |
| PRG17 | (new) a bare reference names a local id that two or more programs emitted (4) | build |
| W13 | (new, warning) a bare reference resolved to the namespaced id `Q.R` of the only program that emitted `R` (4) | build |

The codes are free in sr-core (no SREP uses W13 or PRG17; W01 to W12 and PRG1 to PRG3 and PRG10 to PRG16 are taken) and in
the reference's `crates/sr-model/src/codes.rs` at `b51000f7`. A validator that does not run programs reports neither
W13 nor PRG17.

### Amended text of SREP 66

Semantics 5, second paragraph:

```diff
 The program draws as a `group` with the program's `nodeAttributes`, `nodeBehaviour` and `blend` would draw:
-its transform, timing, opacity, masks, matte and effects apply to the emitted nodes. Emitted ids share the
-document's id space. An emitted id equal to any other id in the document is an error. So is output that is
-not well-formed, ...
+its transform, timing, opacity, masks, matte and effects apply to the emitted nodes. An id `E` that the program
+`P` emits is `P.E` in the document, and references inside the output resolve to the program's own ids first
+(SREP NNNN). Two equal ids in one output, or a namespaced id equal to any other id, are errors. So is output
+that is not well-formed, ...
```

Errors table, PRG14: "collides with an id" becomes "repeats an id within the output, or its namespaced id collides
with another id (SREP NNNN)". The Open issues item "Id scoping" is resolved by this SREP.

### Defaults and the neutral case

There is no new attribute. A document without a program in the composition is unaffected. A document that SREP 66
accepts renders the same pixels under this SREP (see Backwards compatibility).

## Rationale

- **The format's own precedent is lexical scoping.** `instanceType` already says "ids inside a symbol are scoped to the
  instance (effective id = instanceId/innerId)", and the reference resolves an id "from the scope outward"
  (`Builder::resolve`, `crates/sr-eval/src/program.rs:1250`). Rule 3 is the same rule for a program's output. The module
  controls both its ids and its own references, so it can be written without knowing the document.
- **`.` and not `/`.** SREP 66 validates the document again with the output in place, and SREP 59 makes the XSD
  identity constraints (unique `xs:ID`, resolved `xs:IDREF`) part of the format. A namespaced id must therefore be an
  `xs:ID` written in the document, which means an NCName, and `/` is not a `NameChar`. A symbol differs: it is written
  once, and its instances are scoped only when the scene is built.
- **Bare references keep working.** Every reference that SREP 66 resolved names an id that exactly one element carries,
  because collisions were errors. The fallback of rule 4 therefore resolves every such reference to the same element,
  and W13 tells the author to write the qualified form.
- **Ambiguity is an error, not a choice.** If an engine picked "the first" program, a reference would depend on document
  order, and that would turn a one-line edit into a different picture with no message.
- **Seeds from the local id (rule 7).** SREP 66 already treats the output as a function of the module, its parameters
  and the seeds (Determinism 6), and that function does not involve the program's id. Seeding from `P.E` would let a
  rename change the picture, and it would change the pixels of every document SREP 66 accepts whose emitted
  elements draw id-seeded randomness.

## Rejected alternatives

- **An opt-in attribute (`ids="document|program"`, default `document`).** It meets the neutral-default rule trivially,
  but it keeps the collision, which is the failure the atlas hit, as the default. Rules 4 and 7 already keep every
  document SREP 66 accepts rendering the same, so the opt-in protects nothing.
- **A `/` separator, as for instances.** It is not an NCName, as explained under Rationale.
- **`-`, `_` or `__` as the separator.** These are common inside ids (`g-1`, `bar_2`), so `P-E` would be
  ambiguous far more often than `P.E`. `.` is already the format's separator for `id.property`.
- **Keeping the local id and scoping only at build time, like symbols.** The document with the output in place
  would then contain duplicate `xs:ID` values, so SREP 59's check would fail, or the XSD would need a scoped-ID
  extension.
- **Rewriting `url(#id)` paint references and `#id` material maps too.** These name paints and assets, which no
  program output can contain. Rewriting them would turn the atlas case (an emitted shape `blade` beside a gradient
  `blade`, with `fill="url(#blade)"` in the output) into a reference to the shape.
- **Resolving a bare reference to the first program in document order.** See Rationale ("Ambiguity is an error").

## Backwards compatibility

The class is MINOR, and the change rides in 1.6.0, which is not released yet (`schema/CHANGELOG.md`, Unreleased).
Programs exist only from 1.6, so no released document is affected.

- **Validity.** Every document valid under SREP 66 stays valid. Some documents that SREP 66 refuses with PRG14 become
  valid:
  - two programs, or two uses of one module, that emit the same id;
  - an emitted id equal to a document id outside every output, such as the atlas `blade` case.
- **Pixels.** A document that SREP 66 accepts renders identically:
  - by rule 3, each reference inside an output still names the same element;
  - by rule 4, each reference from outside or from another program still names the same element, with W13;
  - by rule 7, id-derived seeds are unchanged.
- **What changes besides pixels.** The id of an emitted element as engines report it: render reports (SREP 18),
  messages, and any engine API or command-line option that selects nodes by id. W13 warnings appear for bare references.
- **Kit.** The verdict of `srep-0066-program-id-collision` changes from PRG14 to valid. Its scene is amended below so that
  it still tests a collision.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | pending (not implemented; the draft names no branch) | Listed below this table. | |

The work in the Rust reference:

1. **`crates/sr-model/src/program.rs`, `expand`.** After the output passes PRG15 and before it is spliced, parse it.
   Collect `L(P)` (PRG14 on a duplicate). Rename the `xs:ID` values to `P.E`. Rewrite the `xs:IDREF` and `xs:IDREFS`
   tokens in `L(P)`, and the literal ids of `prop` and `propAtTime`, in the output's expressions. Then apply rule 4 to
   the tokens that are still bare, emitting W13 or PRG17. Rewriting needs the attribute types of the output's
   elements. The structure check (`crate::xsd::structure::validate_typed`) types the document; whether it can type a
   fragment before the splice was not checked.
2. **`crates/sr-eval`.** Apply the fallback of rule 4 to `prop` and `propAtTime` from outside (`ExprResolver::prop`)
   and to `override/@target` of layouts and variants (`apply_override`, which reports E05 today).
3. **Rule 7.** Keep each emitted element's local id beside its document id, and pass it to `element_seed` and to the
   SREP 80 cell seeds.
4. **Tests, written first.** In `crates/sr-model/tests/program_build.rs`, add:
   - two programs `p` and `q` running `srep66-rect.wasm` load, as `p.g1` and `q.g1`;
   - an emitted `xs:IDREF` naming an emitted id resolves to the program's own element;
   - `prop("g1.x")` from outside resolves, with W13;
   - the same reference with two emitters fails PRG17;
   - `a`/`b.c` beside `a.b`/`c` fails PRG14;
   - `outputSha256` is unchanged by namespacing.

   Existing tests that change:
   - `d.node("g1")` becomes `d.node("p.g1")` in `a_build_program_becomes_a_group_holding_its_output`,
     `the_seed_reaches_the_module` and `parameters_reach_the_module`;
   - the collision case of `failures_carry_their_codes` becomes `<shape id="p.g1">`.
5. **Byte identity.** Every corpus and kit scene that contains a build-mode program, rendered at `--time 0.5`, keeps its
   SHA-256 between the base binary and the implementation (llvmpipe, `SR_GPU_BACKEND=vulkan`). This includes the SREP
   66 and 69 kit cases and the atlas cells with programs, such as cell 40.

## Conformance

The cases go in `conformance/srep_cases/srep-NNNN.json`. They reuse the SREP 66 modules (`srep66-rect.wasm` emits a
rect `g1`). A case that needs a module emitting a reference is written by `conformance/tools/srep66_cases.py` with
`wasm_min.py`, as a constant fragment. The failure cases wait for the kit to express a failed render, like the failure
cases of SREP 66. For a warning, the case checks the warning code, as SREP 57's cases do.

| Case | Checks | Tolerance |
|---|---|---|
| `srep-NNNN-program-ids-reuse` | two programs `a` and `b` running `srep66-rect.wasm` at different `x` both draw (2) | 2 px |
| `srep-NNNN-program-ids-local-ref` | two programs running one module whose output is a rect `m` and a shape with `matte="m"`: each shape is matted by its own rect (3.1) | 2 px |
| `srep-NNNN-program-ids-local-wins` | a document node `m` beside a program whose output has its own `m` and `matte="m"`: the program's `m` is used (3.1) | 2 px |
| `srep-NNNN-program-ids-qualified-prop` | an outside node with `prop("a.g1.x")` follows `a.g1`, with no warning (3.2, 4) | 2 px |
| `srep-NNNN-program-ids-bare-prop` | an outside `prop("g1.x")` with one emitter follows `a.g1` and warns W13 (4) | 2 px / exact |
| `srep-NNNN-program-ids-bare-override` | `layout/override target="g1"` with one emitter applies to `a.g1` and warns W13 (4) | 2 px / exact |
| `srep-NNNN-program-ids-ambiguous` | an outside `prop("g1.x")` with emitters `a` and `b` fails PRG17 (4) | exact |
| `srep-NNNN-program-ids-composed-collision` | `a` emitting `b.c` beside `a.b` emitting `c` fails PRG14 (2) | exact |
| `srep-NNNN-program-ids-duplicate-local` | an output with two elements `g1` fails PRG14 (1) | exact |
| `srep-NNNN-program-ids-seed-local` | an emitted node whose `wiggle` has no seed moves as the same node written by hand with id `g1` (7); expected values from the per-element seed of the baseline | 2 px |
| `srep-NNNN-program-ids-beat-program` | a program with id `beat` emitting `x1`, beside a `beatGrid`: `startMarker="beat.1"` still starts at the grid's beat 1 (Hazards) | 2 px |
| `srep-NNNN-program-ids-output-sha256` | `outputSha256` of `srep66-rect.wasm`'s output passes for programs `a` and `b` alike (6) | 2 px |
| `srep-0066-program-id-collision` (amended) | `<shape id="p.g1">` beside program `p` emitting `g1` fails PRG14 (2) | exact |

Not covered by a case: the W13 of an `xs:IDREF` token in one program's output that names another program's id. The
mechanism is the same as for `bare-prop`, and the case would need two cooperating modules.

## Open issues

1. **A local id that shadows a definition.** Rule 3 resolves by id only, not by kind. An output that emits a node `blade`
   and also writes `asset="blade"` (an `xs:IDREF` to an outside asset) has its asset reference resolved to its own node,
   and then fails the check that position makes. SREP 66 refuses the same output (PRG14), so nothing regresses. A rule
   that resolves locally only when the local element is of a kind the position accepts would make such outputs valid,
   but it needs a table of the referent kinds of the roughly 70 `xs:IDREF` attribute names.
2. **Copies share id-derived randomness.** By rule 7, two programs with identical output draw identical id-seeded
   streams, so their wiggles move in step. An author who wants them to differ gives the programs different `seed`
   values and has the module write `seed` attributes. Whether the namespaced id should seed instead was decided against
   here for byte identity (Rationale), and the schema editor may reverse that before 1.6.0 is released.
3. **Other values derived from ids.** Rule 7 names the two derivations the drafter found
   (`element_seed`, SREP 80). The reference also hashes ids elsewhere, for example `crates/sr-gpu/src/text.rs` (the
   scramble seed takes the frame node's id) and the cache fingerprints of `crates/sr-gpu/src/render.rs`. The drafter has
   not audited whether any of these reaches pixels.
4. **`validate` does not run programs.** W13 and PRG17 therefore appear only at build, as PRG14 does today (atlas
   limitation). A validator option that runs build programs would surface them earlier.
5. **Inside `repeat`.** A program inside a `repeat` template is expanded once, where it is written. How repeat copies
   then scope ids is the existing behaviour of `repeat`, which this draft has not checked.

## References

- SREP 66, Semantics 5, Errors, Open issues ("Id scoping"), Determinism 6 (sr-core `accept/66-83`, 380eee5).
- SREP 57 (generated marker ids, its test `G(x)`); SREP 59 (the identity constraints of XSD 1.0 are part of the
  format); SREP 69 (step mode, no XML output); SREP 71 (`#id` material maps); SREP 80 (cell seed from the owner's id);
  SREP 12, F1 (per-element seeds, Informational).
- `instanceType` annotation, sr-core `schema/scene-render.xsd` on `accept/66-83`: "ids inside a symbol are scoped to the
  instance (effective id = instanceId/innerId)".
- XML 1.0 (Fifth Edition), §2.3, productions [4] `NameStartChar` (no digits, no `.`), [4a] `NameChar` (includes `.`
  and `[0-9]`) and [5] `Name`; Namespaces in XML 1.0 (Third Edition), §3, production [4] `NCName ::= Name - (Char* ':'
  Char*)`. Both read on 2026-10-10 at <https://www.w3.org/TR/xml/> and <https://www.w3.org/TR/xml-names/>.
- rs-scene-render `b51000f7`: `crates/sr-model/src/program.rs`, `crates/sr-model/src/document.rs`,
  `crates/sr-model/src/codes.rs`, `crates/sr-model/tests/program_build.rs`, `crates/sr-eval/src/program.rs`
  (`resolve`, `marker_time`, `ExprResolver::prop`, `apply_override`), `crates/sr-eval/src/eval.rs`,
  `crates/sr-vector/src/d24.rs`.
- atlas v2 `ENGINE_FINDINGS.md` (internal): finding 11 and the limitation on program ids (cell 40).

## History

- 2026-10-10: first draft. Drafted with AI assistance (Claude Opus 5.5 via Claude Code). Nothing here has been
  implemented or tested. The engine behaviour cited was read from the source at rs-scene-render `b51000f7`, not run.
