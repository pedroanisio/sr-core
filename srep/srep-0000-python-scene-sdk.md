---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Opus 5.5 via Claude Code, from sr-core at 07eaec8 (schema 1.7.0), the engine's validate and capabilities commands at 0.5.0, and the maintainers' 2026-10 film builders"
  date: "2026-10-12"
---

```
SREP:            0
Title:           Generate a Python scene SDK from the schema
Author:          Pedro Anisio Silva (drafted with Claude Opus 5.5)
Status:          Draft
Type:            Process
Created:         2026-10-12
Schema-Version:  n/a
Requires:        0, 3, 4, 8, 22, 59, 75, 87
```

# SREP 0 (draft) — Generate a Python scene SDK from the schema

## Abstract

sr-core gains `sr_core.scene`, a Python package to build, read, edit and check scene documents. Its element
classes, attributes, value types, content models and version gates are generated from `schema/scene-render.xsd`
and `schema/scene-render.sch` by the reader that `sr-schemadoc` already uses. The generated code is committed and
checked for staleness, as `docs/schema` is. A schema release cannot be cut while the SDK is stale, and the generator
stops on any schema construct it does not model rather than dropping it. This SREP amends SREP 4 so that the
`sr_core.scene` API becomes part of the distribution's contract. No document changes validity or picture.

## Motivation

**Every builder writes scene XML by hand.** In the maintainers' 2026-10 productions, the two most recent long films
each define their own `node()` and `anim()` helpers over lxml. The shared helper library the maintainers keep writes
XML from string templates, and it targets document versions 1.1 and 1.2, while those films declare 1.6. A separate
in-house XSD validator still defaults to a schema file name (`scene-render-1.1.xsd`) and a directory that no longer
exist. Each of these is a hand-made copy of facts the schema already states, and each has drifted from it.

**The schema's own rules are found late, by the engine.** These were recorded while building scenes:

| Error | How it surfaced | Where the schema states it |
|---|---|---|
| `<styles>` after `<output>`; `<assets>` after `<paints>`; `<effects>` before `<composition>` or before `<lights>` | S02, misplaced element | the `xs:sequence` of `scene` |
| `<data>`, `<font>` directly in `<scene>`; `<textPath>` in `<text>` | S02, element not allowed here | the content model of the parent |
| `circle` for `ellipse` (shape), `left` for `start` (alignment) | refused by the engine's validation | `xs:enumeration` |
| attributes the element does not declare (`strokeDash`, where the schema's is `dash`, removed again by string replacement; `lineWidth` on a `generator` under an older schema) | S04, unknown attribute | the attribute declarations |
| the same id in two sections | S09, duplicate id | one `xs:ID` space per document |

Builders work around them in code: one keeps the comment "effects last: a shot's `<lights>` must precede them",
and moves the element after building. With a generated model, a misplaced or unknown element or attribute cannot be
built, and a wrong value raises when it is assigned. The order of the root's sections comes from the schema when
the document is written.

**The version a document needs is a schema fact that builders choose by hand.** Twenty-four Schematron asserts
gate constructs by `scene/@version`: V1 to V16, VOX1, MSQ1, P3D1, OCN1, CRT1, BH1, FRX1 and GEO1. A builder can
compute the lowest version its document needs from them, instead of copying a number from an earlier film.

**A hand-written SDK would drift as the copies above did.** The schema has had twelve releases (1.1.0 to 1.7.0). It
has 169 complex types, 67 simple types, 989 distinct attribute names and 322 Schematron asserts. Before release
pinning, the engine once vendored a schema that was a strict superset of the tagged 1.5.0, with 108 XSD and
76 Schematron items beyond the tag. The design question is therefore how the SDK stays equal to the schema, not only
what it offers. Section 9 of the Specification answers it.

## Specification

### 1. Scope and placement

1. The SDK MUST be the package `sr_core.scene` in the sr-core distribution, versioned with it (SREP 4).
2. Building, reading, writing and the level 0 and level 1 checks (section 6) MUST use the Python standard library
   only, as the rest of sr-core does. Level 2 MAY use lxml, declared as the optional extra `sr-core[validate]`.
   Level 3 needs an engine binary.
3. The SDK MUST be engine-neutral: no engine names in generated code, and no behaviour beyond what the schema and
   the Schematron state. Production helpers (house styles, captions from word timings, camera rigs) are out of
   scope. They belong to libraries built on the SDK.

### 2. Sources and generation

1. The only inputs MUST be `schema/scene-render.xsd` and `schema/scene-render.sch` at the same commit.
2. The generator MUST read them with `sr_core.schemadoc.model.read`, so that the HTML reference and the SDK share
   one reading of the schema.
3. The generator is `python3 -m sr_core.scene.generate [--check]`. It writes:
   - `sr_core/scene/_generated.py`: the classes of section 3 and the gate table of section 5;
   - `sr_core/scene/schema/`: byte copies of the two input files and their `SHA256SUMS`, shipped as package data.
4. The output MUST be a pure function of the two input files: no timestamps, and members ordered as in the schema.
5. The generated module's header MUST record:
   - the schema release (`xs:schema/@version`);
   - the SHA-256 of both inputs;
   - the generator's version;
   - the counts of section 9, D4.
6. With `--check`, the generator MUST write nothing. It exits 1 when the committed output differs from a fresh run,
   and 0 when they are equal.

### 3. The generated model

1. **Classes.** Each complex type MUST become one class.
   - The class name is the type name without the suffix `Type`, with its first letter in upper case: `layerType`
     becomes `Layer`, `rigidBody3DType` becomes `RigidBody3D`. The root becomes `Scene`.
   - When two types would give the same class name, generation MUST fail. At schema 1.7.0 no two do.
2. **Element names.** A class MUST know which element names its parents give it.
   - Six element names have two types, chosen by the parent: `point`, `pin`, `rigidBody`, `burst`, `program` and
     `param`.
   - Reading MUST pick the class from the element name and its parent, as `Schema.types_of_element` does.
   - If one parent allows one name with two types, generation MUST fail.
   - A class can cover several element names: `Still` covers `poster` and `thumbnail`. The constructor of such a
     class takes the keyword `xml_name`, one of the names of `_element_names` (typed as a `typing.Literal` in the
     hints); without it the first name is used. Any other value, in any class, raises `SchemaValueError`. `xml_name`
     is a reserved runtime name (3.11), so no attribute can collide with it, and the chosen name is what `xml_name`
     returns afterwards. `add`, `find`, `iter`, the occurrence limit of a parent, the diagnostic paths, `copy`, writing
     and the level 1 checks all use that name, and `read` keeps the name found in the document. The factories
     `add_poster` and `add_thumbnail` already fix the name.
3. **Attribute names.** Each attribute MUST be a Python attribute with the XML name unchanged (camelCase), so that
   the reference, the engine's diagnostic paths and the SDK use the same strings.
   - A name that is a Python keyword takes a trailing underscore. At 1.7.0 the only one is `from`, which becomes
     `from_`.
   - Classes MUST use `__slots__`, so that assigning an undeclared attribute raises `AttributeError`.
4. **Attribute data.** Each generated attribute MUST carry:
   - its XSD type;
   - `use`;
   - `default` and `fixed`;
   - its `xs:documentation`, as a docstring.
5. **Values.** Assignment MUST check a value at once, and refuse it with `SchemaValueError`. The error names the
   element path, the attribute and the XSD type.

   | XSD type | Python value accepted | Written as |
   |---|---|---|
   | enumeration | `str` in the list (`typing.Literal` in the hints) | itself |
   | `xs:integer` family, with facets | `int`, or a lexically valid `str` | decimal digits; a `str` as given |
   | `xs:decimal` and its restrictions, with facets | `int`, `float`, `decimal.Decimal`, or a lexically valid `str` | section 4.3; a `str` as given |
   | `xs:double` | `float`, `int`, or a lexically valid `str` | shortest round-trip form; a `str` as given |
   | `xs:boolean` | `bool`, or a lexically valid `str` | `true` / `false`; a `str` as given |
   | `xs:ID` | an NCName `str` (the name characters of XML 1.0 Second Edition, which XSD 1.0 references: productions 84 to 89) | itself |
   | `xs:IDREF` | an NCName `str`, or an element that has an `id` | the id |
   | `xs:IDREFS` | a sequence of the above | ids separated by spaces |
   | list types | a sequence of the item type | items separated by spaces |
   | union types | a value any member type accepts | the first member type that accepts it |
   | string types with `xs:pattern` | `str` | itself |

   **Lexical `str` values.** For every type that is not string-valued (the integer family, `xs:decimal`,
   `xs:double`, `xs:boolean`, `xs:dateTime`, and restrictions of them), a `str` is a lexical form. It is accepted when
   it is a valid lexical form of the type and meets every facet (range, pattern, enumeration), and is refused with
   the same `SchemaValueError` otherwise. An accepted `str` is stored exactly as `read` stores a lexical form found
   in a file (4.2), with no normalisation, not even of white space around it. It is written as given, and the getter
   gives what it gives after a read (`"0.3000"` reads as `0.3`). Python-native values (`int`, `float`, `bool`,
   `Decimal`, `datetime`) are formatted as before. This is what lets a ported builder write the exact text of the
   builder it replaces (part 3).

6. **Patterns.** The generator MUST translate each `xs:pattern` into a Python regular expression matched against
   the whole value (XSD patterns are anchored implicitly).
   - Generation MUST fail on any XSD regex feature it does not translate: `\i`, `\c`, `\p{…}`, character-class
     subtraction, and anything else outside the shared subset.
   - The 14 patterns at 1.7.0 use none of them.
7. **Absent attributes.** An attribute that is not set reads as `None` and is not written.
   - `default_of(element, name)` returns the schema default.
   - Writing MUST NOT add attributes that were not set, so a neutral default stays implicit.
8. **Content.**
   - Children of ordered content (the 25 `xs:sequence` content models, the root's among them) MUST be written in the
     order of the content model, whatever order they were added in.
   - Children of unordered content (`xs:choice`, any number) keep the order in which they were added.
   - Adding a child MUST check that the parent allows the name and that `maxOccurs` is not exceeded.
   - Adding an element to itself or to one of its descendants MUST be refused: the tree would become a cycle, and
     walking it would never end. This holds for `add` and for a direct change of `.nodes`.
   - `minOccurs`, and attributes with `use="required"`, are checked by `check` (section 6). A document is built in
     steps, so they cannot be checked earlier.
9. **Factories.** For each child a parent allows, the class MUST have a method `add_<elementName>` that creates,
   adds and returns the child. For example, `composition.add_layer(id="l-title", asset=title, x=120)` returns a
   `Layer`. The prefix keeps factories apart from attributes: `sequenceType` has both an attribute and a child named
   `transition`, and `viewport3DType` has both named `camera`.
10. **Text, comments and processing instructions.**
    - Simple content (three types at 1.7.0, and no mixed types) is held in `.content`.
    - Comments, processing instructions and whitespace text are nodes in `.nodes`, and survive reading and writing.
    - Whitespace is XML white space (XML 1.0 production `S`): space, tab, carriage return and line feed. A no-break
      space, U+2003 or any other Unicode space is character data, here and in every check of section 6.
    - `.nodes` may be changed directly. An element it gains MUST have no owner, or that parent, and gets that
      parent as owner; an element it loses has none.
11. **Runtime names.** The schema already uses `parent`, `path`, `text` and `version` as attribute names, so the
    runtime cannot use them. The element API uses these names:
    - `xml_name` (a read-only property, and the constructor keyword that chooses it, see 3.2), `owner`, `nodes`, `elements()`, `content`;
    - `add`, `add_<name>`, `remove`, `find`, `find_all`, `iter`, `copy`;
    - `attributes()`, `xml_path`, `source_line`, `source_column`;
    - `new_id`, `min_version`, `check`, `to_bytes`.

    Every other runtime member starts with `_`. The generator MUST fail when a schema attribute takes a reserved name,
    starts with `add_`, or starts with `_` (D3).

### 4. Reading and writing

1. **Functions.** The core provides:
   - `read(source) -> Scene`, from a path or bytes;
   - `write(scene, target, *, layout="preserve")`;
   - `to_bytes(scene, *, layout="preserve")`.

   Three layouts exist:
   - `"preserve"` writes the stored whitespace, attribute order and child order;
   - `"pretty"` writes 2-space indentation, new attributes in the order the schema declares them, and sequence
     children in content-model order, and drops the whitespace it replaces;
   - `"indent"` keeps the stored order and applies libxml2's pretty-print rule, which is what
     `lxml.etree.tostring(..., pretty_print=True)` does. An element none of whose children is a text node (white
     space included) is written with each child (element, comment or processing instruction) on its own line, indented
     2 spaces per level, and its end tag on a line of its own. An element that has a text node is written exactly as
     stored, and so is everything below it. An element without children is `<x/>`. The XML declaration and each
     comment or processing instruction outside the root stand on their own lines, and the document ends with a
     newline. The rule was determined against lxml 6.1.3 (libxml2 `xmlsave`, format mode) and is tested against it on
     random trees. It never reorders or drops anything.
2. **Round trip.** For every document the SDK reads, writing it back unchanged with `layout="preserve"` MUST give a
   document whose C14N 2.0 form, with comments, equals that of the original.
   - An attribute value that was not changed keeps its lexical form: `1.50` stays `1.50`.
3. **Numbers.**
   - A `float` is written in the shortest form that reads back as the same float, in positional notation. It never
     uses an exponent, because the lexical space of `xs:decimal` has none.
   - `-0` is written `0`. NaN and the infinities are refused.
   - A `decimal.Decimal` is written exactly, with all of its digits. SREP 75 allows `xs:decimal` values of any
     length.
4. **Ids.**
   - Ids are unique across the whole document.
   - `scene.new_id(prefix)` returns `prefix`, then `prefix-2`, `prefix-3`, and so on: deterministic, and never a
     taken id. It does not reserve the id it returns.
   - A loop that calls `new_id` and adds one element per call MUST take time linear in the number of elements, not
     quadratic: the document's ids are indexed, and the index follows every change.
   - A reference to an id that a program emits (`P.E`, SREP 87) is not resolved by the SDK. It is left to the engine,
     as the schema leaves it.
5. **Version.**
   - `scene.min_version()` returns the lowest version in the `scene/@version` enumeration that no version gate
     refuses.
   - `Scene(version="auto")` MUST write `min_version()`.
   - An explicit version below `min_version()` is a `check` error. The error names the gate's assert id and message.

### 5. Version gates

1. **What the generator extracts.** It MUST extract every Schematron assert that refuses constructs by
   `scene/@version`. The accepted forms are:
   - a rule whose context is `/scene[@version='a' or @version='b' …]`, with a test `not(T)` or `count(P) <= n`;
   - a rule whose context is a construct path C, with a test
     `not(/scene/@version='a' or /scene/@version='b' …)`, optionally `or` another expression over C.

   Each record holds the assert id, the set of versions it refuses, the trigger, and the message.
2. **Triggers.** They MUST be compiled from this XPath 1.0 subset only:
   - child (`/`) and descendant (`//`) steps from the context, name tests and `|` unions;
   - predicates of the form `@a`, `@a='literal'`, and `or` / `and` / `not()` over them;
   - `count(path) <= n`.

   Any other form MUST fail generation. At 1.7.0 all 24 gate asserts fit the subset.
3. **Evaluation.** The SDK MUST evaluate the compiled triggers natively, without lxml.

### 6. Checks

| Level | Call | Covers | Needs | Findings |
|---|---|---|---|---|
| 0 | construction | element names, parents, `maxOccurs`, attribute names, value spaces, patterns | stdlib | exceptions |
| 1 | `check(scene)` | level 0, plus `minOccurs`, required attributes, unique ids, IDREF and IDREFS targets (SREP 59), the version gates | stdlib | `Finding` |
| 2 | `check(scene, schema=True)` | the whole XSD and all Schematron asserts, run on the bundled canonical files | lxml | `Finding` with the assert ids |
| 3 | `check(scene, engine=PATH)` | `<engine> validate --format json` on the written bytes; the engine's diagnostics are returned unchanged | an engine | `Finding` with the engine's codes |

1. **`Finding` fields.** A `Finding` has:
   - `severity` (`error`, `warning` or `info`);
   - `code`;
   - `message`;
   - `path`, in the engine's form `/scene/composition/layer[2]`;
   - `line` and `column`, when the document was read from a file.
2. **Level 1 codes.**
   - Gate findings use the gate's assert id.
   - Structural findings use `xsd:<kind>`, one of:
     - `xsd:element`: a name the parent does not allow, or an unknown element;
     - `xsd:occurs`: children that do not match the content model, `minOccurs` included;
     - `xsd:attribute`: an undeclared attribute;
     - `xsd:required`: a missing required attribute;
     - `xsd:value`: a value outside its type's lexical or value space;
     - `xsd:id-unique`, `xsd:idref`, `xsd:version`.

     A document that was read can carry all of these. A document built through the SDK can carry only `xsd:occurs`,
     `xsd:required` and the reference and version codes.
   - **Character data.** Character data other than XML white space (space, tab, CR, LF), in element-only content,
     and any character data in empty content, is `xsd:occurs`.
   - **Version below the minimum.** An explicit version below `min_version()` gives the gate findings and one
     `xsd:version` finding that names the gates.
   - **References into programs.** A document with a program that emits nodes (SREP 87) may hold references that only
     the build resolves, including bare references to an emitted id. Level 1 does not report unresolved `xs:IDREF` or
     `xs:IDREFS` tokens in such a document, and leaves them to the engine.
   - Engine code catalogues are not copied into sr-core.
3. **Agreement.** Level 1 is a subset of level 2. It MUST NOT report a document valid that level 2 refuses for a
   check level 1 performs, nor the reverse (section 9, D5).
4. **Level 3 as authority.** Level 3 is the authority for what only an engine knows: compile-for-render findings,
   engine-only warnings, and evaluation errors.
   - When the engine reports a finding with the same code at the same path as level 1 or level 2, only the engine's
     is kept.
   - Level 2 drops a finding that level 1 already reports, with the same code at the same path.
5. **Limits.** A document nested deeper than lxml can parse gives level 2 one `error` with code `sdk:too-deep`. It
   does not crash. Levels 0, 1 and writing have no depth limit.

### 7. Engine schema check

1. `engine_info(path)` MUST run `<engine> capabilities` and read the manifest's `engine` and `schema` fields
   (SREP 22).
2. A level 3 check MUST add a `warning` with code `sdk:schema-skew` when the engine's schema release differs from
   the SDK's.
3. It MUST add an `error` when the MAJOR.MINOR of the engine's schema release is below the document's
   `scene/@version`. Document versions follow the schema release, not the engine's own version.

### 8. Command

The console script `sr-scene` provides three commands:

| Command | What it does | Exit codes |
|---|---|---|
| `sr-scene check FILE... [--schema] [--engine PATH] [--data DIR] [--format human\|json] [--deny-warnings]` | runs level 1, and level 2 or 3 when asked; `--data` is the folder the engine resolves assets from | 0 valid (warnings alone do not fail unless `--deny-warnings`), 1 errors, 2 read error |
| `sr-scene min-version FILE...` | prints each file's lowest valid version | |
| `sr-scene format FILE... [--check]` | rewrites with `layout="pretty"` and the content-model order, atomically; says when it reordered elements; refuses a file with a DOCTYPE, whose entities a rewrite would inline | with `--check`, rewrites nothing and exits 1 when a file would change |

### 9. Drift controls

Each control names the drift it stops and the place it runs. Together they make "the SDK equals the schema at this
commit" a tested property, rather than a convention.

| Id | Drift it stops | Control | Runs in |
|---|---|---|---|
| D1 | schema changed, SDK not regenerated | `generate --check` MUST pass | the test suite, and `tools/release.py check` (hygiene R6) |
| D2 | schema released with a stale or unrecorded SDK | `tools/release.py release schema` MUST regenerate the SDK, as it regenerates `docs/schema`, and MUST refuse to finish without a `CHANGELOG.md` Unreleased entry for it, classed as in section 10 | the release command |
| D3 | a new schema construct silently missing from the SDK | the generator MUST fail on any XSD construct, regex feature, gate form or name collision it does not handle; nothing is dropped | generation |
| D4 | partial generation | a test MUST match each complex type to one class, each attribute declaration to one attribute, each enumeration value to one literal, and each version-gate assert to one gate record, both ways; the counts are in the generated header | the test suite |
| D5 | the SDK's checks disagree with the schema's | for every document in `conformance/cases/` and `tests/fixtures/`, three checks: (a) the round trip of section 4.2 holds; (b) level 1 agrees with lxml (XSD plus Schematron) on the checks level 1 performs; (c) the document is relabelled at every enumerated version, and `min_version()` equals the lowest version at which lxml raises none of the gate asserts | the test suite, with lxml (same skips as `test_schema_rules.py`) |
| D6 | value-space checks drift from the XSD | for every simple type with facets or enumerations, generated probes (each enumeration value and one non-member; each numeric bound, inclusive and exclusive, and one step beyond it; the pattern examples in the type's documentation, when present) are accepted or refused by the SDK exactly as lxml decides for a minimal document carrying them | the test suite, with lxml |
| D7 | the shipped schema copy differs from the canonical files | `sr_core/scene/schema/` MUST be byte-equal to `schema/`, and its hashes equal to `schema/SHA256SUMS` and to the generated header | the test suite, and `release.py check` |
| D8 | a broken or mixed installation | on its first check in a process, the SDK MUST compare the hashes in its generated header with its bundled schema files, and refuse to run on a difference | runtime |
| D9 | the engine runs a different schema release than the SDK | section 7 | runtime, at level 3 |
| D10 | libraries built on the SDK drift by writing XML themselves | libraries SHOULD build documents only through `sr_core.scene` and type-check against its hints, so that a schema rename breaks their build, not a render. To make this possible, the SDK ships `py.typed`, and every attribute is an `Attr[Get, Set]` descriptor: it reads as the parsed type and accepts the input types of 3.5. The constructors and `add_<name>` factories have keyword-only, typed signatures for type checkers. At run time an undeclared keyword still raises `AttributeError` (3.3). sr-core does not enforce D10 | downstream |

### 10. Amendment of SREP 4

1. **The changed sentence.** In SREP 4, "Version lines", the sentence "The Python modules are internal. They may
   change in any release, and they are not part of the distribution's contract." becomes:

   > The Python modules are internal, except `sr_core.scene` (SREP n). Its classes, attributes, functions,
   > exceptions and `Finding` fields are part of the distribution's contract.

2. **How changes to `sr_core.scene` are classed.**
   - A change that regeneration makes after a schema release takes the class of the schema change:
     - Added, for new types, attributes or enumeration values;
     - Breaking, for anything the schema removes or renames.
   - A change to the hand-written core is classed as a change to a command is.

## Rationale

- **Generation, not a hand-written mirror.** The schema is too large, and changes too often, to copy by hand: the
  copies in Motivation each drifted. Generation turns each schema change into a reviewable diff of generated code
  in the same commit.
- **One reader.** `sr_core.schemadoc.model` already reads the whole schema and stops on constructs it does not model.
  Generating from it means the reference and the SDK cannot read the schema differently.
- **Committed output, not runtime generation.** Committed classes give editor completion, static type checking,
  and a staleness test. This is the pattern `docs/schema` and hygiene R6 already use.
- **XML names unchanged.** The names in the reference, in the engine's diagnostic paths and in the SDK stay one
  vocabulary. A snake_case mapping would be a second vocabulary to keep in step.
- **Gates read from the Schematron.** The Schematron is normative. A separate table of versions would be a second
  source, which is exactly the drift this SREP prevents.
- **Standard library core.** sr-core declares no dependencies (`dependencies = []`). lxml stays optional, for
  level 2.
- **Python.** The maintainers' builders, sr-core's own tools and its tests are Python. The same reader could later
  generate a TypeScript model; that is outside this SREP.
- **Precedent.** Generic XSD-to-Python generators exist, for example xsdata and generateDS. Section "Rejected
  alternatives" says why this SREP generates its own model.

## Rejected alternatives

- **Using a generic XSD binding generator (xsdata, generateDS).** These were not evaluated in depth for this draft.
  The deciding points are three:
  - the version gates and cross-field rules live in the Schematron, which a generic XSD binding does not read;
  - section 4.2 requires a lossless round trip (comments, lexical forms);
  - a dependency would be added to a package that has none.

  A reviewer who shows a generator meeting all three would reopen this point.
- **Extending the existing helper library by hand.** It drifted to versions 1.1 and 1.2 while the films moved to
  1.6. Hand-written mirrors drift.
- **Generating classes at import time from the XSD.** This gives no static types, no reviewable diff and no
  completion, and it slows every import.
- **Engine validation only.** Findings come only after a document is written, from a binary not every builder has.
  An SDK still needs the schema model to build anything.
- **Version data in `xs:appinfo`, or in a separate JSON table.** SREP 22 rejected `xs:appinfo` for capability data.
  Version availability is already normative in the Schematron, and a copy would drift.
- **A separate repository or distribution for the SDK.** Schema and SDK would then release separately, and skew
  between them is the drift this SREP prevents. Same repository, same commit, same release.

## Backwards compatibility

- No change to the schema, to the validity of any document, or to any picture.
- The distribution gains a package, an optional extra and a command. That is Added, a MINOR release under SREP 4.
- The amendment of SREP 4 widens the contract to `sr_core.scene`. No existing command, option or output changes.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | n/a | none required. Level 3 reads the fields `valid` and `files[].diagnostics[].{severity, code, message, loc, path}` of `validate --format json`, and `schema` and `engine` of `capabilities`. A change to those is a change to command output for the engine. A JSON form of `explain` would let the SDK list engine codes; it is optional | |

## Conformance

None. The SREP changes no rendering. Its checks are sr-core tests: D1, D4, D5, D6 and D7, in
`tests/test_scene_sdk_*.py`.

## Open issues

1. **Animatable properties are not in the schema.** Which `animate/@property` names an element takes, and what
   shape each value has (scalar, or `x,y` pair), are not stated in the schema. Today the engine finds them only at
   evaluation: E02 "has no property" and E04 "is not an x,y pair" were both seen on documents that validated with
   0 errors. The SDK cannot check what the schema does not state. Two options:
   - a Standards SREP that types animatable properties in the schema (recommended);
   - the SDK's level 3 also evaluating frame 0.
2. **Licence.** Settled 2026-10-12: the SDK is MIT, as the rest of sr-core is. The engine stays under its own
   licence.
3. **Package data.** Settled: the wheel ships `sr_core/scene/schema/` as package data. Hygiene R5 already accepts
   every entry under `sr_core/`.
4. **Where lxml departs from XSD 1.0.** Level 2 and the D5 and D6 controls run on libxml2. Where it departs from
   XSD 1.0, level 1 follows XSD 1.0, and D6 lists each case by exact form. A test fails when libxml2 changes. The
   departures:
   - Before libxml2 2.13, `xs:decimal` values of more than 24 digits are refused, though SREP 75 allows them.
     D5 and D6 skip these, as `test_schema_rules.py` does.
   - `1e` is accepted as an `xs:double`. XSD 1.0 §3.2.5.1 requires digits after the exponent mark.
   - `NaN` passes range facets. NaN is incomparable, so it fails them.
   - Some malformed IP-literal hosts in `xs:anyURI` values are accepted: `[:::1]`, `[1:2]` and `[v.x]`. Level 1
     reads `xs:anyURI` as XSD 1.0 §3.2.17 defines it: the XLink §5.4 escaping, then an RFC 3986 §4.1 URI reference.
   - Dangling `xs:IDREF` values are not reported. Level 1 reports them (SREP 59).
5. **Structural codes.** Settled for the SDK: level 1 uses the `xsd:<kind>` codes of section 6.2. The engine's
   structural codes (S01 to S12) are defined by the engine and are not mapped. Whether every validator should share
   the `xsd:<kind>` codes is a separate question.
6. **Delivery, size L, in three parts, each usable alone:**
   1. The generator, the generated model, reading and writing, levels 0 and 1, and D1 to D8. Accepted when D5 passes
      on every case and fixture in the repository.
   2. Levels 2 and 3, section 7, and the `sr-scene` command.
   3. Outside sr-core: the maintainers' helper library rebuilt on `sr_core.scene`. Its proof is one existing film
      builder, ported, whose scenes are C14N-equal to the scenes it writes today.

## References

- SREP 0 (process), SREP 3 (canonical schema file names), SREP 4 (versioning), SREP 8 (version gate), SREP 22
  (capability manifests), SREP 59 (ID references), SREP 75 (long decimals), SREP 83 and SREP 86 (the 1.3 gates),
  SREP 87 (program-scoped ids), SREP 90.
- W3C, XML Schema Part 2: Datatypes, Second Edition, §3.2.3 decimal (lexical space without exponent) and Appendix F
  (regular expressions): <https://www.w3.org/TR/xmlschema-2/>
- ISO/IEC 19757-3, Schematron.
- W3C, Canonical XML Version 2.0: <https://www.w3.org/TR/xml-c14n2/>; Python's
  `xml.etree.ElementTree.canonicalize` and `TreeBuilder(insert_comments=True)`, both added in Python 3.8:
  <https://docs.python.org/3/library/xml.etree.elementtree.html>
- RFC 2119, key words for requirement levels: <https://www.rfc-editor.org/rfc/rfc2119>
- RFC 3986, URI generic syntax, §4.1 and Appendix A: <https://www.rfc-editor.org/rfc/rfc3986>; W3C, XLink 1.0, §5.4
  (locator attribute escaping): <https://www.w3.org/TR/xlink/>
- xsdata: <https://xsdata.readthedocs.io/>; generateDS: <https://www.davekuhlman.org/generateDS.html>

## History

- 2026-10-12: drafted, at the owner's request, with a proposal for keeping the SDK equal to the schema (section 9).
- 2026-10-12: parts 1 and 2 implemented on the branch `feat/scene-sdk`. The factories became `add_<name>`, simple
  content `.content` (3.11), the level 1 codes were completed (6.2), and open issues 3 to 5 were settled.
- 2026-10-12: for the part 3 acceptance (raw C14N equality with a ported builder): a valid lexical `str` is accepted
  and stored verbatim for every non-string type (3.5), and `layout="indent"` was added (4.1).
- 2026-10-12: a class that covers several element names takes the constructor keyword `xml_name` (3.2), so that
  `<thumbnail>` can be built through the public API.
