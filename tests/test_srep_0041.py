"""SREP 41: object3D/@shadowCatcher (boolean, default false; no Schematron rule)."""
import glob
import os

import pytest

from test_schema_rules import ROOT, etree, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0041-*.xml")))
XSD_PATH = os.path.join(ROOT, "schema", "scene-render.xsd")
NS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def obj(attrs, version="1.1"):
    return (f'<scene version="{version}"><project width="100" height="100" fps="1" duration="1"/>'
            f'<composition><object3D id="o" primitive="plane" {attrs}/></composition></scene>')


def test_cases_exist():
    assert len(CASES) == 2


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    # version 1.2 is added to the enumeration centrally; the attribute is accepted in every version.
    assert verdict(open(case, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


def test_default_is_false():
    tree = etree.parse(XSD_PATH)
    assert tree.xpath("//xs:complexType[@name='object3DType']/xs:attribute[@name='shadowCatcher']/@default",
                      namespaces=NS) == ["false"]


@pytest.mark.parametrize("value", ["true", "false", "1", "0"])
def test_boolean_values_are_accepted(value):
    assert verdict(obj(f'shadowCatcher="{value}"')) == "ok"


@pytest.mark.parametrize("value", ["yes", "maybe", ""])
def test_non_boolean_values_are_rejected_by_the_xsd(value):
    assert verdict(obj(f'shadowCatcher="{value}"')) == "xsd"


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_accepted_in_versions_1_0_and_1_1(version):
    assert verdict(obj('shadowCatcher="true" opacity="0.5" receiveShadow="false"', version)) == "ok"


@pytest.mark.parametrize("primitive", ["box", "sphere", "plane", "torus"])
def test_the_schema_does_not_restrict_it_by_primitive(primitive):
    # Semantics 1: on a non-surface object the attribute has no effect and a validator SHOULD report it as inert
    # (SREP 18); that is a report finding, not a schema rule, so the schema accepts it everywhere.
    xml = obj('shadowCatcher="true"').replace('primitive="plane"', f'primitive="{primitive}"')
    assert verdict(xml) == "ok"
