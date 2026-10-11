"""SREPs 66 to 75 are accepted: the canonical schema carries their Syntax as the SREPs write it.

Each SREP's ```xml blocks are its normative syntax. For every Schematron assertion they write, schema/scene-render.sch
has an assertion with the same id, test and message (the tests of ITR1 and SRT1 as SREP 85 amends them), in a rule
with the same context and a pattern with the same id, and each pattern the SREPs write has their rules in their order.
For every type they declare, the XSD has that type with the same content, and every attribute they add to an existing
type is declared there as written. The documentation is the SREPs' too, except where ANNOTATIONS lists a difference
and its reason. The reference engine vendored these SREPs with a few local differences (listed in the acceptance
commit); this test keeps sr-core on the SREPs' text.
"""
import os
import re

import pytest

etree = pytest.importorskip("lxml.etree")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XS = "http://www.w3.org/2001/XMLSchema"
SCH = "http://purl.oclc.org/dsdl/schematron"
NS = {"xs": XS, "sch": SCH}
SREPS = range(66, 76)

# where the SREPs add attributes to existing types (their Syntax names the type in a comment)
HOSTS = {
    67: ["effectType"], 68: ["effectType"], 69: ["programNodeType"], 71: ["materialType", "lightType"],
    72: ["projectType", "nodeCoreAttributes"], 73: ["flockType"],
}

# where an assertion of an SREP block sits in another pattern of the schema, and why
PATTERNS = {"MTX1-baseColorMap": ("p-srep71-baseColorMap", "SREP 71's comment: each map attribute in its own pattern")}
MTX1_MAPS = ("baseColorMap", "normalMap", "metallicRoughnessMap", "occlusionMap", "emissiveMap", "displacementMap")

# documentation the schema carries that differs from the SREPs' blocks: (SREP, declaration path) -> reason. The
# SREPs give no text for these (or, for programNodeType, a text SREP 69 made incomplete); the schema has the
# reference engine's (rs-scene-render 82ad2091), which says nothing the Semantics do not. Documentation only.
ANNOTATIONS = {
    (66, "programNodeType"): "SREP 66's text says the module runs once when the document is built, which SREP 69's "
                             "step mode contradicts; the engine's text describes both modes",
    (66, "programAttributes/fuel"): "SREP 66 gives no documentation for fuel",
    (70, "parametricPathType"): "SREP 70 gives none; the text matches Semantics 2",
    (70, "parametricSurfaceType"): "SREP 70 gives none; the text matches Semantics 3",
    (70, "heightfieldType"): "SREP 70 gives none; the text matches Semantics 4",
    (71, "unitTripleType"): "SREP 71 gives none",
    (72, "@supersample"): "SREP 72 gives none; the text matches its Semantics, with the range SREP 89 gives",
    (72, "@supersampleFilter"): "SREP 72 gives none; the text matches its Semantics",
    (72, "@edgeBlend"): "SREP 72 gives none; the text matches its Semantics",
}

XSD = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd")).getroot()


def _amended_by_srep85():
    """SREP 85 (accepted) amends SREP 67's ITR1 and SRT1 to read their numbers by value: its "diff amendment 67"
    block gives each the test the canonical schema carries (the message, rule and pattern are unchanged)."""
    text = open(os.path.join(ROOT, "srep", "srep-0085.md"), encoding="utf-8").read()
    (block,) = re.findall(r"^```diff amendment 67\n(.*?)^```", text, re.S | re.M)
    out = {}
    for line in block.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            a = etree.fromstring(f'<root xmlns:sch="{SCH}">{line[1:]}</root>')[0]
            out[a.get("id")] = a.get("test")
    assert set(out) == {"ITR1", "SRT1"}
    return out


AMENDED_TESTS = _amended_by_srep85()
SCHEMATRON = etree.parse(os.path.join(ROOT, "schema", "scene-render.sch")).getroot()


def blocks(n):
    text = open(os.path.join(ROOT, "srep", f"srep-{n:04d}.md"), encoding="utf-8").read()
    for b in re.findall(r"^```xml\n(.*?)^```", text, re.S | re.M):
        yield etree.fromstring(f'<root xmlns:xs="{XS}" xmlns:sch="{SCH}">{b}</root>')


def canon(el, without=()):
    """An element without annotations, comments, insignificant whitespace and the attributes named in `without`,
    as a string."""
    el = etree.fromstring(etree.tostring(el))
    for a in el.xpath("xs:attribute", namespaces=NS):
        if a.get("name") in without:
            el.remove(a)
    for a in el.xpath(".//xs:annotation", namespaces=NS):
        a.getparent().remove(a)
    for c in el.xpath(".//comment()"):
        c.getparent().remove(c)
    for e in el.iter():
        if e.text is not None and not e.text.strip():
            e.text = None
        if e.tail is not None and not e.tail.strip():
            e.tail = None
    etree.cleanup_namespaces(el)
    return etree.tostring(el, method="c14n").decode()


def norm(s):
    return " ".join((s or "").split())


def docs(el):
    """The documentation inside a declaration, by the path of named declarations that holds it."""
    out = {}
    for d in el.iter(f"{{{XS}}}documentation"):
        names, p = [], d.getparent()
        while p is not None:
            if p.get("name"):
                names.append(p.get("name"))
            if p is el:
                break
            p = p.getparent()
        k = "/".join(reversed(names))
        out[k] = norm(out.get(k, "") + " " + "".join(d.itertext()))
    return out


def named(kind, name):
    found = XSD.xpath(f"xs:{kind}[@name=$n]", namespaces=NS, n=name)
    assert len(found) == 1, f"{kind} {name}: {len(found)} declarations"
    return found[0]


CASES = [(n, i) for n in SREPS for i, _ in enumerate(blocks(n))]


@pytest.mark.parametrize("n", SREPS)
def test_every_assertion_of_the_srep_is_in_the_schematron(n):
    for root in blocks(n):
        for a in root.iter(f"{{{SCH}}}assert"):
            have = SCHEMATRON.xpath(".//sch:assert[@id=$i]", namespaces=NS, i=a.get("id"))
            assert len(have) == 1, a.get("id")
            assert norm(have[0].get("test")) == norm(AMENDED_TESTS.get(a.get("id"), a.get("test"))), a.get("id")
            assert norm(have[0].text) == norm(a.text), a.get("id")
            rule = a.getparent()
            if rule.tag == f"{{{SCH}}}rule":          # an amended assertion may be written without its rule
                assert norm(have[0].getparent().get("context")) == norm(rule.get("context")), a.get("id")
                pattern = rule.getparent()
                if pattern.tag == f"{{{SCH}}}pattern":
                    want = PATTERNS.get(a.get("id"), (pattern.get("id"),))[0]
                    assert have[0].getparent().getparent().get("id") == want, (a.get("id"), want)


@pytest.mark.parametrize("n", SREPS)
def test_every_pattern_of_the_srep_has_its_rules_in_order(n):
    moved = set(PATTERNS)
    for root in blocks(n):
        for p in root.iter(f"{{{SCH}}}pattern"):
            have = SCHEMATRON.xpath(".//sch:pattern[@id=$i]", namespaces=NS, i=p.get("id"))
            assert len(have) == 1, p.get("id")
            want = [(norm(r.get("context")), [a.get("id") for a in r.iter(f"{{{SCH}}}assert")])
                    for r in p.iter(f"{{{SCH}}}rule") if not moved & {a.get("id") for a in r.iter(f"{{{SCH}}}assert")}]
            got = [(norm(r.get("context")), [a.get("id") for a in r.iter(f"{{{SCH}}}assert")])
                   for r in have[0].iter(f"{{{SCH}}}rule")]
            assert got == want, p.get("id")


def test_mtx1_has_one_pattern_per_map_attribute():
    """SREP 71 writes MTX1 for baseColorMap and asks the same rule, in its own pattern, for the other five maps."""
    model = SCHEMATRON.xpath(".//sch:assert[@id='MTX1-baseColorMap']", namespaces=NS)[0]
    for attr in MTX1_MAPS:
        p = SCHEMATRON.xpath(".//sch:pattern[@id=$i]", namespaces=NS, i=f"p-srep71-{attr}")
        assert len(p) == 1 and len(p[0]) == 1, attr
        rule = p[0][0]
        assert norm(rule.get("context")) == f"material[starts-with(@{attr}, '#')]"
        a = rule.xpath("sch:assert", namespaces=NS)
        assert len(a) == 1 and a[0].get("id") == f"MTX1-{attr}"
        assert norm(a[0].get("test")) == norm(model.get("test")).replace("baseColorMap", attr)
        assert norm(a[0].text) == norm(model.text)


@pytest.mark.parametrize("n", SREPS)
def test_every_type_of_the_srep_is_declared_as_written(n):
    for root in blocks(n):
        for kind in ("complexType", "simpleType", "attributeGroup"):
            for t in root.findall(f"{{{XS}}}{kind}"):
                later = {a.get("name") for m, names in HOSTS.items() if m > n and t.get("name") in names
                         for r in blocks(m) for a in r.findall(f"{{{XS}}}attribute")}
                assert canon(named(kind, t.get("name")), later) == canon(t), t.get("name")


def annotation_differences():
    found = {}
    for n in SREPS:
        for root in blocks(n):
            for kind in ("complexType", "simpleType", "attributeGroup"):
                for t in root.findall(f"{{{XS}}}{kind}"):
                    later = {a.get("name") for m, names in HOSTS.items() if m > n and t.get("name") in names
                             for r in blocks(m) for a in r.findall(f"{{{XS}}}attribute")}
                    have = {k: v for k, v in docs(named(kind, t.get("name"))).items()
                            if k == t.get("name") or k.split("/")[-1] not in later}
                    want = docs(t)
                    found.update({(n, k): (want.get(k), have.get(k)) for k in set(have) | set(want)
                                  if have.get(k) != want.get(k)})
            hosts = [h for name in HOSTS.get(n, []) for h in XSD.xpath(
                "xs:complexType[@name=$h] | xs:attributeGroup[@name=$h]", namespaces=NS, h=name)]
            for a in root.findall(f"{{{XS}}}attribute") if hosts else ():
                have = docs([d for h in hosts for d in h.xpath("xs:attribute[@name=$a]", namespaces=NS,
                                                              a=a.get("name"))][0])
                want = docs(a)
                found.update({(n, "@" + k): (want.get(k), have.get(k)) for k in set(have) | set(want)
                              if have.get(k) != want.get(k)})
    return found


def test_the_documentation_is_the_srep_text_except_where_listed():
    found = annotation_differences()
    assert set(found) == set(ANNOTATIONS), {k: found.get(k) for k in set(found) ^ set(ANNOTATIONS)}
    # where an SREP gives no text, the schema adds one; it never drops an SREP's text
    assert all(have for want, have in found.values())


@pytest.mark.parametrize("n", sorted(HOSTS))
def test_every_attribute_the_srep_adds_is_declared_as_written(n):
    hosts = [h for name in HOSTS[n] for h in XSD.xpath("xs:complexType[@name=$h] | xs:attributeGroup[@name=$h]",
                                                       namespaces=NS, h=name)]
    assert len(hosts) == len(HOSTS[n])
    added = [a for root in blocks(n) for a in root.findall(f"{{{XS}}}attribute")]
    assert added, f"SREP {n} adds no attribute"
    for a in added:
        have = [d for h in hosts for d in h.xpath("xs:attribute[@name=$a]", namespaces=NS, a=a.get("name"))]
        assert len(have) == 1, (n, a.get("name"), len(have))
        assert canon(have[0]) == canon(a), (n, a.get("name"))


@pytest.mark.parametrize("n", SREPS)
def test_every_element_the_srep_adds_is_declared(n):
    for root in blocks(n):
        for e in root.findall(f"{{{XS}}}element"):
            have = XSD.xpath(".//xs:element[@name=$e][@type=$t]", namespaces=NS, e=e.get("name"), t=e.get("type"))
            assert have, (n, e.get("name"), e.get("type"))


def test_document_version_1_6_is_accepted():
    versions = XSD.xpath("xs:element[@name='scene']//xs:attribute[@name='version']//xs:enumeration/@value",
                         namespaces=NS)
    assert "1.6" in versions
