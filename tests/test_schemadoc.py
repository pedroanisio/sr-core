"""sr_core.schemadoc: XSD/Schematron model, HTML site, determinism, links, and the committed site being current."""
import json
import posixpath
import re
from html.parser import HTMLParser

import pytest

from sr_core.schemadoc import cli, html, model as m

XSD = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" version="9.9">
  <xs:annotation><xs:documentation>
    Test schema.
      space  pixels
  </xs:documentation></xs:annotation>
  <xs:element name="doc">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="head" type="headType" minOccurs="0"/>
        <xs:group ref="items" maxOccurs="unbounded"/>
      </xs:sequence>
      <xs:attribute name="version" type="xs:string" use="required"/>
    </xs:complexType>
  </xs:element>
  <xs:group name="items">
    <xs:choice>
      <xs:element name="box" type="boxType"/>
      <xs:element name="special" type="specialType"/>
      <xs:element name="note">
        <xs:complexType><xs:attribute name="text" type="xs:string"/></xs:complexType>
      </xs:element>
    </xs:choice>
  </xs:group>
  <xs:attributeGroup name="common">
    <xs:attribute name="id" type="xs:ID" use="required"/>
    <xs:attribute name="opacity" type="unit" default="1"/>
  </xs:attributeGroup>
  <xs:complexType name="headType">
    <xs:annotation><xs:documentation>The `head` of a document.</xs:documentation></xs:annotation>
  </xs:complexType>
  <xs:complexType name="boxType">
    <xs:choice minOccurs="0" maxOccurs="unbounded"><xs:group ref="items"/></xs:choice>
    <xs:attributeGroup ref="common"/>
    <xs:attribute name="shape" default="rect">
      <xs:simpleType><xs:restriction base="xs:string">
        <xs:enumeration value="rect"/><xs:enumeration value="ellipse"/>
      </xs:restriction></xs:simpleType>
    </xs:attribute>
    <xs:attribute name="count"><xs:simpleType><xs:restriction base="xs:positiveInteger">
      <xs:maxInclusive value="10"/></xs:restriction></xs:simpleType></xs:attribute>
  </xs:complexType>
  <xs:complexType name="specialType">
    <xs:complexContent><xs:extension base="boxType">
      <xs:attribute name="glow" type="xs:boolean" default="false"/>
    </xs:extension></xs:complexContent>
  </xs:complexType>
  <xs:simpleType name="unit">
    <xs:restriction base="xs:double"><xs:minInclusive value="0"/><xs:maxInclusive value="1"/></xs:restriction>
  </xs:simpleType>
</xs:schema>
"""

SCH = b"""<?xml version="1.0"?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt">
  <sch:title>test rules</sch:title>
  <sch:pattern id="p1">
    <sch:rule context="/doc[@version='1']">
      <sch:assert id="V1" test="not(.//special)">version 1 has no special.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="p2">
    <sch:rule context="box[@shape='ellipse']">
      <sch:assert id="C1" test="@count">shape "<sch:value-of select="@shape"/>" needs count.</sch:assert>
    </sch:rule>
    <sch:rule context="*[@glow][not(self::box)]">
      <sch:assert id="C2" test="@opacity">glow needs opacity.</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
"""


@pytest.fixture(scope="module")
def s():
    return m.read(XSD, SCH, "t.xsd", "t.sch")


def test_model(s):
    assert s.root == "doc" and s.version == "9.9"
    assert set(s.complex) == {m.ROOT_TYPE, "headType", "boxType", "specialType", "group:items/note"}
    assert [p.name for p in s.children(m.ROOT_TYPE)] == ["head", "box", "special", "note"]
    box = {a.name: a for a in s.all_attributes("boxType")}
    assert box["id"].origin == "common" and box["id"].use == "required"
    assert [v for v, _ in box["shape"].inline.enums] == ["rect", "ellipse"]
    special = {a.name: a for a in s.all_attributes("specialType")}
    assert special["opacity"].inherited == "boxType" and special["glow"].inherited is None
    assert s.rules[1].asserts[0].message == 'shape "{@shape}" needs count.'


def test_rule_targets(s):
    assert m.rule_types(s, "/doc[@version='1']") == [m.ROOT_TYPE]
    assert m.rule_types(s, "box[@shape='ellipse']") == ["boxType"]
    assert m.rule_types(s, "*[@glow][not(self::box)]") == ["specialType"]      # by attribute; not() ignored
    assert m.rule_types(s, "*[self::box or self::special]") == ["boxType", "specialType"]
    assert m.rule_types(s, "count(x) > 1") == []


def test_unsupported_constructs_fail_loudly():
    with pytest.raises(m.SchemaError):
        m.read(XSD.replace(b'<xs:group ref="items" maxOccurs', b'<xs:group ref="nope" maxOccurs'))
    with pytest.raises(m.SchemaError):
        m.read(XSD.replace(b'<xs:element name="head" type="headType" minOccurs="0"/>',
                           b'<xs:element ref="head"/>'))


def test_html_content(s):
    files = html.build(s)
    box = files["type/boxType.html"]
    assert 'id="a-shape"' in box and "<code>rect</code>" in box and "≤ 10" in box
    assert "groups.html#common" in box and "Extended by" in box
    assert "C1" in box and "V1" not in box                                   # only the rules that apply
    special = files["type/specialType.html"]
    assert "inherited from" in special and "C2" in special
    assert "[0, 1]" in files["simple-types.html"]
    assert "<pre>" in files["index.html"]                                    # aligned header documentation kept
    index = json.loads(files["search-index.js"][len("window.SR_INDEX="):-2])
    assert ["@glow", "type/specialType.html#a-glow", "specialType"] in index


def links_ok(files: dict[str, str]) -> list[str]:
    ids: dict[str, set] = {}
    hrefs: list[tuple[str, str]] = []

    class P(HTMLParser):
        def __init__(self, path):
            super().__init__()
            self.path = path

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if "id" in a:
                assert a["id"] not in ids.setdefault(self.path, set()), f"duplicate id {a['id']} in {self.path}"
                ids[self.path].add(a["id"])
            for k in ("href", "src"):
                if k in a and not a[k].startswith(("http:", "https:")):
                    hrefs.append((self.path, a[k]))

    for path, text in files.items():
        if path.endswith(".html"):
            P(path).feed(text)
    bad = []
    for path, h in hrefs:
        target, _, frag = h.partition("#")
        t = posixpath.normpath(posixpath.join(posixpath.dirname(path), target)) if target else path
        if t not in files:
            bad.append(f"{path}: {h}")
        elif frag and frag not in ids.get(t, set()):
            bad.append(f"{path}: {h} (no anchor)")
    return bad


def test_links_synthetic(s):
    files = html.build(s)
    files.update({"t.xsd": "", "t.sch": ""})
    assert links_ok(files) == []


# ------------------------------------------------------------- canonical schema
CANON = cli.canonical_schema()
needs_canon = pytest.mark.skipif(CANON[0] is None, reason="no canonical schema in this checkout")


@needs_canon
def test_canonical_site_is_deterministic_and_linked():
    a = cli.render(*CANON)
    b = cli.render(*CANON)
    assert a == b
    files = {k: v.decode("utf-8") for k, v in a.items()}
    assert links_ok(files) == []
    s = m.read(open(CANON[0], "rb").read(), open(CANON[1], "rb").read())
    assert all(f"type/{html.slug(k)}.html" in files for k in s.complex)
    text = "".join(files.values())
    assert all(a.id in text for r in s.rules for a in r.asserts if a.id)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", files["index.html"])   # no timestamps


@needs_canon
def test_committed_site_is_current():
    """docs/schema is generated; after changing schema/ run `python3 -m sr_core.schemadoc`."""
    assert cli.main(["--check"]) == 0


def test_cli_write_check_and_refuse(tmp_path):
    x, sc = tmp_path / "t.xsd", tmp_path / "t.sch"
    x.write_bytes(XSD)
    sc.write_bytes(SCH)
    out = tmp_path / "site"
    assert cli.main(["--xsd", str(x), "-o", str(out)]) == 0
    assert (out / "t.sch").read_bytes() == SCH                     # the .sch beside the XSD is picked up
    assert cli.main(["--xsd", str(x), "-o", str(out), "--check"]) == 0
    (out / "type" / "stale.html").write_text("old")
    assert cli.main(["--xsd", str(x), "-o", str(out), "--check"]) == 1
    assert cli.main(["--xsd", str(x), "-o", str(out)]) == 0
    assert not (out / "type" / "stale.html").exists()
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("mine")
    assert cli.main(["--xsd", str(x), "-o", str(other)]) == 2
    assert (other / "keep.txt").read_text() == "mine"
