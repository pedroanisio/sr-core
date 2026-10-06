"""SREP 36: geoLayer progress draws polygon outlines on. Documentation-only change in the schema; no rule is added."""
import glob
import os

import pytest

from test_schema_rules import ROOT, doc, etree, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0036-*.xml")))
XSD_PATH = os.path.join(ROOT, "schema", "scene-render.xsd")
NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
ASSETS = '<geo id="g" src="x.geojson"/>'


def geo(layer_attrs):
    return doc(assets=ASSETS + f'<map id="m" width="10" height="10"><geoLayer geo="g" {layer_attrs}/></map>')


def test_the_table_cases_exist():
    # the two cases of the SREP's Conformance table, plus the progress 0 / 0.4 / 1 and fill-at-0 / 1 cases built on them
    names = {os.path.basename(c)[:-4] for c in CASES}
    assert {"srep-0036-geo-outline-progress", "srep-0036-geo-fill-whole"} <= names


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    # version 1.2 is added to the enumeration centrally; the document is otherwise valid under 1.1.
    xml = open(case, "rb").read().replace(b'version="1.2"', b'version="1.1"')
    assert verdict(xml) == "ok"


def test_documentation_of_geolayertype_is_the_srep_sentence():
    tree = etree.parse(XSD_PATH)
    text = " ".join("".join(tree.xpath("//xs:complexType[@name='geoLayerType']/xs:annotation/xs:documentation",
                                       namespaces=NS)[0].itertext()).split())
    assert ("polygons filled and stroked, lines and outlines stroked (drawn on by @progress: each line or ring from its "
            "first vertex; the fill stays whole), points as dots.") in text
    assert "lines stroked (drawn on by @progress)" not in text


@pytest.mark.parametrize("value", ["0", "0.5", "1"])
def test_progress_in_unit_interval_is_accepted(value):
    assert verdict(geo(f'progress="{value}" fill="#FF0000"')) == "ok"


@pytest.mark.parametrize("value", ["1.5", "-0.1", "half"])
def test_progress_outside_unit_interval_is_rejected(value):
    assert verdict(geo(f'progress="{value}"')) == "xsd"


def test_progress_default_is_one():
    tree = etree.parse(XSD_PATH)
    assert tree.xpath("//xs:complexType[@name='geoLayerType']/xs:attribute[@name='progress']/@default",
                      namespaces=NS) == ["1"]
