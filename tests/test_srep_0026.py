"""SREP 26: <points> in a repeat. Pointlist/points types, amended C17, V10, C74-C80 (patterns p75 and p76;
the SREP text called them p68 and p69, renumbered by the coordinator).

scene/@version does not yet accept "1.2" in the canonical XSD (the enumeration is extended centrally), so the
accept/reject tests below use a copy of the XSD whose enumeration gains 1.2 (XSD12). V10 is tested with a 1.1
document, which the unchanged enumeration accepts. The cases declare version="1.2" and are validated both ways.
"""
import glob
import os

import pytest
from lxml import etree
from test_schema_rules import ROOT, SCH, XSD

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0026-*.xml")))
_src = open(os.path.join(ROOT, "schema", "scene-render.xsd")).read()
_enum = '<xs:enumeration value="1.0"/><xs:enumeration value="1.1"/>'
assert _src.count(_enum) == 1
XSD12 = etree.XMLSchema(etree.fromstring(_src.replace(_enum, _enum + '<xs:enumeration value="1.2"/>').encode()))
SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}


def verdict12(xml, version="1.2"):
    xml = xml.replace('version="1.2"', f'version="{version}"')
    t = etree.fromstring(xml.encode() if isinstance(xml, str) else xml)
    if not XSD12.validate(t):
        return "xsd"
    if not SCH.validate(t):
        ids = SCH.validation_report.xpath("//svrl:failed-assert/@id", namespaces=SVRL)
        return "sch:" + ",".join(sorted(set(ids)))
    return "ok"


def rep(points, attrs="", version="1.2", inner='<shape id="s" shape="rect" width="10" height="10"/>'):
    return (f'<scene version="{version}"><project width="100" height="100" fps="1" duration="1"/>'
            f'<parameters><param id="d" type="list" default="a,b"/></parameters><composition><repeat id="r"{attrs}>{points}{inner}</repeat></composition></scene>')


GRID = '<points type="grid" columns="3" rows="2"/>'


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_cases_validate(case):
    assert len(CASES) == 6
    xml = open(case, "rb").read().decode()
    assert verdict12(xml) == "ok"
    # the XSD part is version independent; only V10 refuses points in a 1.1 document
    assert verdict12(xml, "1.1") == "sch:V10"


@pytest.mark.parametrize("points", [
    GRID,
    '<points id="p" type="grid" columns="2" rows="2" spacingX="20" spacingY="30" seed="7"/>',
    '<points type="along-path" path="M0,0 L10,0" count="3" orient="true"/>',
    '<points type="scatter" count="5" width="100" height="50" seed="7"/>',
    '<points type="scatter" count="5" path="M0,0 H100 V100 H0 Z" fillRule="evenodd"/>',
    '<points type="vertices" path="M0,0 L10,0 L5,5 Z"/>',
    '<points type="list" at="0,0 10,10 -5.5,1e1"/>',
    '<points type="grid"><animate property="spacingX"><key time="0" value="50"/><key time="1" value="150"/></animate></points>',
])
def test_accepted(points):
    assert verdict12(rep(points)) == "ok"


def test_repeat_without_points_is_unchanged():
    assert verdict12(rep("", ' count="3"')) == "ok"
    assert verdict12(rep("", ' over="d"')) == "ok"
    assert verdict12(rep("", "")) == "sch:C17"
    assert verdict12(rep("", ' count="3" over="d"')) == "sch:C17"


def test_c17_points_count_over_are_exclusive():
    assert verdict12(rep(GRID)) == "ok"
    assert verdict12(rep(GRID, ' count="3"')) == "sch:C17"
    assert verdict12(rep(GRID, ' over="d"')) == "sch:C17"
    assert verdict12(rep(GRID, ' count="3" over="d"')) == "sch:C17"


def test_v10_points_need_version_1_2():
    assert verdict12(rep(GRID), "1.1") == "sch:V10"
    assert "V10" in verdict12(rep(GRID), "1.0")
    assert verdict12(rep(GRID), "1.2") == "ok"
    # no points: no V10
    assert "V10" not in verdict12(rep("", ' count="2"'), "1.1")


def test_c74_at_most_one_points_child():
    assert verdict12(rep(GRID + GRID)) == "sch:C74"


@pytest.mark.parametrize("attrs,expected", [
    ("", "ok"), (' from="0" step="1"', "ok"), (' from="1"', "sch:C80"), (' step="2"', "sch:C80"),
    (' from="2" step="3"', "sch:C80"),
])
def test_c80_neutral_from_and_step(attrs, expected):
    assert verdict12(rep(GRID, attrs)) == expected


@pytest.mark.parametrize("rule,points", [
    ("C75", '<points type="along-path" count="3"/>'),
    ("C75", '<points type="along-path" path="M0,0 L1,1"/>'),
    ("C76", '<points type="scatter" width="10" height="10"/>'),
    ("C76", '<points type="scatter" count="3"/>'),
    ("C76", '<points type="scatter" count="3" width="10"/>'),
    ("C76", '<points type="scatter" count="3" path="M0,0 H9 V9 Z" width="10" height="10"/>'),
    ("C77", '<points type="vertices"/>'),
    ("C78", '<points type="list"/>'),
    ("C79", '<points type="grid"><animate property="columns"><key time="0" value="1"/><key time="1" value="3"/></animate></points>'),
])
def test_points_checks(rule, points):
    assert verdict12(rep(points)) == f"sch:{rule}"


def test_xsd_rejections():
    for points in ['<points/>', '<points type="spiral"/>', '<points type="grid" columns="0"/>',
                   '<points type="list" at="1;2"/>', '<points type="grid" orient="maybe"/>',
                   '<points type="scatter" count="-1" width="1" height="1"/>',
                   '<points type="scatter" count="1" width="-1" height="1"/>']:
        assert verdict12(rep(points)) == "xsd", points
