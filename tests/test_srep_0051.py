"""SREP 51: shapeModifier/@mode documentation gains wiggle-path smooth. No declaration changes: the attribute stays an NMTOKEN."""
import os

import pytest

from test_schema_rules import ROOT, XSD, doc, etree, verdict

CASES = os.path.join(ROOT, "conformance", "cases")
XS = "{http://www.w3.org/2001/XMLSchema}"


def case(name):
    """A case of this SREP. It declares version="1.2"; the version enumeration and the V5 gate are applied centrally
    (release coordinator), so until then the document is checked as 1.1, which differs only in that attribute."""
    xml = open(os.path.join(CASES, name + ".xml"), "rb").read()
    assert b'<scene version="1.2">' in xml
    return xml.replace(b'<scene version="1.2">', b'<scene version="1.1">')


def wiggle(mode):
    attr = "" if mode is None else f' mode="{mode}"'
    return doc('<shape id="w" shape="path" width="200" height="10" path="M 0 5 L 200 5" stroke="#FF0000FF" '
               f'strokeWidth="3"><shapeModifier type="wiggle-path" size="8" detail="10"{attr}/></shape>')


@pytest.mark.parametrize("name", ["srep-0051-wiggle-smooth", "srep-0051-wiggle-smooth-corner"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


def test_the_smooth_case_sets_the_mode_and_the_corner_case_does_not():
    assert b'mode="smooth"' in case("srep-0051-wiggle-smooth")
    assert b"mode=" not in case("srep-0051-wiggle-smooth-corner").split(b"<shapeModifier")[1].split(b"/>")[0]


@pytest.mark.parametrize("mode", [None, "corner", "smooth", "anything"])
def test_modes_are_accepted(mode):
    # "any other value, or no mode, is corner" (SREP 51 Semantics): the schema does not enumerate it
    assert verdict(wiggle(mode)) == "ok"


def test_a_mode_with_a_space_is_rejected_as_not_an_nmtoken():
    assert verdict(wiggle("smooth corner")) == "xsd"


def test_the_documentation_names_wiggle_path_smooth():
    schema = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
    ct = schema.xpath("//xs:complexType[@name='shapeModifierType']", namespaces={"xs": XS[1:-1]})[0]
    attr = ct.xpath("xs:attribute[@name='mode']", namespaces={"xs": XS[1:-1]})[0]
    assert attr.get("type") == "xs:NMTOKEN" and attr.get("default") is None
    text = " ".join("".join(attr.itertext()).split())
    assert "zig-zag and wiggle-path: corner|smooth" in text
    assert "Catmull-Rom spline" in text and "offset-path join: miter|round|bevel" in text
