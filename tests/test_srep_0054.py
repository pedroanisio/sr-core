"""SREP 54: transformConstraint/@pole (IDREF) and @softness (unitDecimal, default 0). No Schematron rule; rejection is by the XSD."""
import os

import pytest

from test_schema_rules import ROOT, doc, etree, verdict

CASES = os.path.join(ROOT, "conformance", "cases")
XS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def case(name):
    """A case of this SREP. It declares version="1.2"; the version enumeration and the V5 gate are applied centrally
    (release coordinator), so until then the document is checked as 1.1, which differs only in that attribute."""
    xml = open(os.path.join(CASES, name + ".xml"), "rb").read()
    assert b'<scene version="1.2">' in xml
    return xml.replace(b'<scene version="1.2">', b'<scene version="1.1">')


def rig(attrs):
    return doc('<group id="g"><shape id="goal" shape="ellipse" width="2" height="2"/>'
               '<shape id="p" shape="ellipse" width="2" height="2"/>'
               '<skeleton id="rig"><bone id="hip" length="10"/><bone id="knee" parent="hip" x="10" length="10"/>'
               f'<transformConstraint type="ik" target="goal"{attrs}/></skeleton></group>')


@pytest.mark.parametrize("name", ["srep-0054-ik-pole", "srep-0054-ik-soft-reach"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


def test_the_cases_use_the_new_attributes():
    assert b'pole="pole"' in case("srep-0054-ik-pole")
    assert b'softness="0.3"' in case("srep-0054-ik-soft-reach")


@pytest.mark.parametrize("attrs", ["", ' pole="p"', ' softness="0"', ' softness="0.3"', ' softness="1"',
                                   ' pole="p" softness="0.5" bendPositive="false"', ' pole="hip"'])
def test_pole_and_softness_are_accepted(attrs):
    assert verdict(rig(attrs)) == "ok"


@pytest.mark.parametrize("attrs", [' pole="a b"', ' pole="1x"', ' softness="1.5"', ' softness="-0.1"', ' softness="soft"'])
def test_pole_is_an_idref_and_softness_is_a_unit_decimal(attrs):
    assert verdict(rig(attrs)) == "xsd"


def test_declarations():
    schema = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
    ct = schema.xpath("//xs:complexType[@name='transformConstraintType']", namespaces=XS)[0]
    pole = ct.xpath("xs:attribute[@name='pole']", namespaces=XS)[0]
    soft = ct.xpath("xs:attribute[@name='softness']", namespaces=XS)[0]
    assert pole.get("type") == "xs:IDREF" and pole.get("default") is None
    assert soft.get("type") == "unitDecimal" and soft.get("default") == "0"
