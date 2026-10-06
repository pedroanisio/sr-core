"""SREP 34: amendment of SREP 18 (inert rules I9 to I13, MASK-MISS). Report findings only: no schema rule is added.
The one schema change is the documentation of group/@collapse."""
import os

import pytest

etree = pytest.importorskip("lxml.etree")
from test_schema_rules import ROOT, verdict  # noqa: E402

NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
XSD_TREE = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
SCH_TEXT = open(os.path.join(ROOT, "schema", "scene-render.sch"), encoding="utf-8").read()


def case(name):
    """A conformance case; the 1.2 version gate is applied centrally later, so the case is validated as 1.1."""
    with open(os.path.join(ROOT, "conformance", "cases", name), "rb") as f:
        return f.read().replace(b'<scene version="1.2">', b'<scene version="1.1">')


def scene(body, effects=""):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            f"<composition>{body}</composition>" + (f"<effects>{effects}</effects>" if effects else "") + "</scene>")


def test_case_validates():
    assert verdict(case("srep-0034-inert-and-mask-miss.xml")) == "ok"


def test_collapse_documentation_says_it_has_no_effect():
    a = XSD_TREE.xpath("//xs:complexType[@name='groupType']/xs:attribute[@name='collapse']", namespaces=NS)
    assert len(a) == 1 and a[0].get("default") == "false" and a[0].get("type") == "xs:boolean"
    text = " ".join("".join(a[0].itertext()).split())
    assert "no effect" in text
    assert "an isolated group (clip, mask, matte, effects or blend) draws its children in its own offscreen" in text
    assert "instead of being flattened" not in text


def test_no_schematron_rule_names_the_report_codes():
    # SREP 34 is a report amendment: nothing here is a validity rule
    for code in ("INERT", "MASK-MISS", "I9", "I10", "I11", "I12", "I13"):
        assert f'id="{code}' not in SCH_TEXT


@pytest.mark.parametrize("body,effects", [
    ('<group id="g" collapse="true"/>', ""),
    ('<shape id="s" shape="rect" width="5" height="5" effects="e"/>', '<effect id="e" type="selective-color" channel="red"/>'),
    ('<shape id="s" shape="rect" width="5" height="5" effects="e"/>', '<effect id="e" type="vignette" intensity="0.5"/>'),
    ('<shape id="s" shape="rect" width="5" height="5" opacity="0"/>',
     '<effect id="e" type="displacement-map" source="s"/>'),
    ('<shape id="s" shape="rect" width="5" height="5"><animate property="x"><key time="0" value="0" '
     'interpolation="ease-out" overshoot="1.5"/><key time="1" value="9"/></animate></shape>', ""),
    ('<shape id="s" shape="rect" width="30" height="40"><mask type="rect" x="900" y="900" width="10" height="10"/></shape>', ""),
])
def test_inert_conditions_are_valid_documents_the_validator_only_reports(body, effects):
    # the findings I9 to I13 and MASK-MISS are report entries, not rejections: the schema accepts every one
    assert verdict(scene(body, effects)) == "ok"
