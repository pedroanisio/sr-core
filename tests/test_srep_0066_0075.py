"""SREPs 66 to 75 are accepted: the canonical schema carries their Syntax as the SREPs write it.

Each SREP's ```xml blocks are its normative syntax. For every Schematron assertion they write, schema/scene-render.sch
has an assertion with the same id, test and message. For every type they declare, the XSD has that type with the same
content (annotations aside), and every attribute they add to an existing type is declared there as written. The
reference engine vendored these SREPs with a few local differences (listed in the acceptance commit); this test keeps
sr-core on the SREPs' text.
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

XSD = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd")).getroot()
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
            assert norm(have[0].get("test")) == norm(a.get("test")), a.get("id")
            assert norm(have[0].text) == norm(a.text), a.get("id")
            rule = a.getparent()
            if rule.tag == f"{{{SCH}}}rule":          # an amended assertion may be written without its rule
                assert norm(have[0].getparent().get("context")) == norm(rule.get("context")), a.get("id")


@pytest.mark.parametrize("n", SREPS)
def test_every_type_of_the_srep_is_declared_as_written(n):
    for root in blocks(n):
        for kind in ("complexType", "simpleType", "attributeGroup"):
            for t in root.findall(f"{{{XS}}}{kind}"):
                later = {a.get("name") for m, names in HOSTS.items() if m > n and t.get("name") in names
                         for r in blocks(m) for a in r.findall(f"{{{XS}}}attribute")}
                assert canon(named(kind, t.get("name")), later) == canon(t), t.get("name")


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
