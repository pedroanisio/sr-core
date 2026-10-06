"""SREP 55: nodeAttributes/@shutterAngle (xs:double, 0 to 720, no default). No Schematron rule; rejection is by the XSD."""
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
    return xml


def node(attr, kind="shape"):
    if kind == "shape":
        return doc(f'<shape id="s" shape="rect" width="10" height="10"{attr}/>')
    return doc(f'<group id="g"{attr}><shape id="s" shape="rect" width="10" height="10"/></group>')


@pytest.mark.parametrize("name", ["srep-0055-node-shutter", "srep-0055-node-shutter-inherit"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


def test_the_cases_set_the_angle_on_nodes():
    assert b'shutterAngle="360"' in case("srep-0055-node-shutter") and b'shutterAngle="0"' in case("srep-0055-node-shutter")
    inherit = case("srep-0055-node-shutter-inherit")
    assert b'<group id="grp" shutterAngle="360">' in inherit and b'id="own"' in inherit


@pytest.mark.parametrize("kind", ["shape", "group"])
@pytest.mark.parametrize("value", ["0", "180", "360", "720", "0.5", "1e2"])
def test_angles_inside_the_project_range_are_accepted(kind, value):
    assert verdict(node(f' shutterAngle="{value}"', kind)) == "ok"


@pytest.mark.parametrize("value", ["-1", "-0.001", "720.001", "1000", "wide", ""])
def test_angles_outside_zero_to_720_are_rejected(value):
    assert verdict(node(f' shutterAngle="{value}"')) == "xsd"


def test_there_is_no_default_and_the_range_matches_the_project_attribute():
    schema = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
    node_attr = schema.xpath("//xs:attributeGroup[@name='nodeAttributes']/xs:attribute[@name='shutterAngle']", namespaces=XS)[0]
    proj_attr = schema.xpath("//xs:complexType[@name='projectType']/xs:attribute[@name='shutterAngle']", namespaces=XS)[0]
    assert node_attr.get("default") is None and proj_attr.get("default") == "180"
    rng = lambda a: [(e.tag.split("}")[1], e.get("value")) for e in a.xpath(".//xs:restriction/*", namespaces=XS)]
    assert rng(node_attr) == rng(proj_attr) == [("minInclusive", "0"), ("maxInclusive", "720")]
