"""SREP 39: material/@unevenness, @unevennessScale, @unevennessSeed (types and defaults; no Schematron rule)."""
import os

import pytest

from test_schema_rules import ROOT, etree, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0039-unevenness-varies.xml")
XSD_PATH = os.path.join(ROOT, "schema", "scene-render.xsd")
NS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def material(attrs, version="1.1"):
    return (f'<scene version="{version}"><project width="100" height="100" fps="1" duration="1"/>'
            f'<materials><material id="m" {attrs}/></materials><composition/></scene>')


def test_case_validates():
    # version 1.2 is added to the enumeration centrally; the attributes are accepted in every version.
    assert verdict(open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


def test_defaults_are_the_neutral_ones():
    tree = etree.parse(XSD_PATH)
    got = {a: tree.xpath(f"//xs:complexType[@name='materialType']/xs:attribute[@name='{a}']/@default", namespaces=NS)
           for a in ("unevenness", "unevennessScale", "unevennessSeed")}
    assert got == {"unevenness": ["0"], "unevennessScale": ["8"], "unevennessSeed": ["0"]}


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_accepted_in_every_version(version):
    assert verdict(material('unevenness="0.5" unevennessScale="16" unevennessSeed="7"', version)) == "ok"


@pytest.mark.parametrize("attrs", ['unevenness="0"', 'unevenness="1"', 'unevennessScale="0.5"',
                                   'unevennessSeed="0"', 'unevennessSeed="4294967295"',
                                   'unevennessSeed="4294967296"'])
def test_valid_values_are_accepted(attrs):
    assert verdict(material(attrs)) == "ok"      # a seed above 2^32-1 is valid XML Schema; it wraps (Semantics)


@pytest.mark.parametrize("attrs", ['unevenness="1.5"', 'unevenness="-0.1"', 'unevennessScale="0"',
                                   'unevennessScale="-4"', 'unevennessSeed="-1"', 'unevennessSeed="1.5"',
                                   'unevennessSeed="abc"'])
def test_invalid_values_are_rejected_by_the_xsd(attrs):
    assert verdict(material(attrs)) == "xsd"
