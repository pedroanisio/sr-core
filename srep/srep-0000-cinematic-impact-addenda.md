---
disclaimer:
  notice: >-
    No information within this document should be taken for granted.
    Any statement or premise not backed by a real logical definition
    or verifiable reference may be invalid, erroneous, or a hallucination.
  generated_by: "Claude Sonnet 5.5 via Claude Code (worker brave-heart), from the engine's schema file and srep-0000-cinematic-impact.md"
  date: "2026-10-06"
---

```
SREP:            0
Title:           Addenda to the cinematic-impact draft: two schema declarations it does not state
Author:          scene-render maintainers (drafted by brave-heart)
Status:          Draft
Type:            Informational
Created:         2026-10-06
Schema-Version:  1.3
Requires:        srep-0000-cinematic-impact
```

# Addenda to `srep-0000-cinematic-impact` — two declarations the schema file has and the draft does not state

`srep-0000-cinematic-impact.md` is the owner's text and is not edited here. The schema sync report (2026-10-06) found that
two named declarations of the engine's schema file are not in that draft, although the behaviour they carry is. This note
gives the exact declarations so that, when the draft is accepted, the schema fragments it carries are complete. The
editor may fold this note into the draft, or keep it as a note it refers to.

## 1. `volumeSequencePatternType` and `volumeSourceType`

**What the draft says** (Volume assets and sequences): `src` uses "the existing `%d`, `%0Nd` or consecutive `#` placeholder, with
at most 64 padding digits", is "a union of `xs:anyURI` and a filename-pattern string, because raw `%d` and repeated `#`
are not valid URI spellings", and "both labels and a valid placeholder are required" for a sequence.

**What the schema file declares** (and the draft does not):

```xml
<!-- A printf placeholder such as %d is not itself a percent-encoded URI. -->
<xs:simpleType name="volumeSequencePatternType">
  <xs:restriction base="xs:string"><xs:pattern value=".*(%[0-9]*d|#+).*"/></xs:restriction>
</xs:simpleType>
<xs:simpleType name="volumeSourceType"><xs:union memberTypes="xs:anyURI volumeSequencePatternType"/></xs:simpleType>
<!-- volumeAssetType/@src uses it: <xs:attribute name="src" type="volumeSourceType" use="required"/> -->
```

**What to add to the draft's schema inventory:** the two simple types above, as the type of `volume/@src`. The pattern
is a syntactic filter only: it accepts any string with one `%d`-style placeholder (`%d`, `%05d`, … without the 64-digit limit) or a
run of `#`. The remaining requirements of the draft (at most 64 padding digits, a valid placeholder, both frame labels, the
1,000,000-frame limit) are enforced by rules VOL1 to VOL9 and not by the pattern; the draft should say that the pattern
does not enforce them, so that a second engine does not take the pattern as the whole check.

## 2. The `pyroCrater` attribute group

**What the draft says** (`pyroSourceType` and `pyroImpulseType`): each type's table lists `crater`, `heatFraction`,
`dustFraction`, `specificHeat` and `maxTemperature`, with the semantics of the smoke from an impact (PYC1 to PYC4).

**What the schema file declares** (and the draft does not): the five attributes are one attribute group shared by both types,
with its own documentation:

```xml
<xs:attributeGroup name="pyroCrater">
  <xs:annotation><xs:documentation>A source or impulse that the impact of a crater causes. `crater` names a crater that grows
  from an impact (`crater@source`); … (the text of the draft's "Smoke from an impact" paragraph, condensed)
  </xs:documentation></xs:annotation>
  <xs:attribute name="crater" type="xs:IDREF"/>
  <xs:attribute name="heatFraction"><xs:simpleType><xs:restriction base="nonNegativeDecimal"><xs:maxInclusive value="1"/></xs:restriction></xs:simpleType></xs:attribute>
  <xs:attribute name="dustFraction"><xs:simpleType><xs:restriction base="positiveDecimal"><xs:maxInclusive value="1"/></xs:restriction></xs:simpleType></xs:attribute>
  <xs:attribute name="specificHeat" type="positiveDecimal"/>
  <xs:attribute name="maxTemperature"><xs:simpleType><xs:restriction base="positiveDecimal"><xs:maxInclusive value="50000"/></xs:restriction></xs:simpleType></xs:attribute>
</xs:attributeGroup>
<!-- pyroSourceType and pyroImpulseType each contain: <xs:attributeGroup ref="pyroCrater"/> -->
```

**What to add:** the group declaration and the two references, in place of the two copies of the attribute table (the
attributes, types and the defaults stated by the draft are unchanged: the defaults 0.1, 0.01, 1000 and 5000 are engine
defaults of the semantics, not schema defaults, as the draft says). The documentation text of the group is the
engine's; the draft's paragraph is the source of the same statements and the two should agree word for word when the
schema is merged.

## 3. Not covered by this note

`captionTrack@lineBreaks` has its own draft (`srep-0000-caption-line-breaks.md`).
