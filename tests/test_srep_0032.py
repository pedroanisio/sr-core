"""SREP 32: layer/@resample (linear, bicubic, mitchell). No Schematron rule."""
import os

import pytest

etree = pytest.importorskip("lxml.etree")
from test_schema_rules import ROOT, verdict  # noqa: E402

NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
XSD_TREE = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))


def case(name):
    """A conformance case; the 1.2 version gate is applied centrally later, so the case is validated as 1.1."""
    with open(os.path.join(ROOT, "conformance", "cases", name), "rb") as f:
        return f.read().replace(b'<scene version="1.2">', b'<scene version="1.1">')


def scene(layer_attrs):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            '<assets><image id="i" src="x.png" width="2" height="2"/></assets>'
            f'<composition><layer id="l" asset="i" {layer_attrs}/></composition></scene>')


def test_case_validates():
    assert verdict(case("srep-0032-resample-filters.xml")) == "ok"


def test_declaration_on_layer_with_default_linear_and_three_values():
    a = XSD_TREE.xpath("//xs:complexType[@name='layerType']/xs:attribute[@name='resample']", namespaces=NS)
    assert len(a) == 1 and a[0].get("default") == "linear"
    vals = a[0].xpath(".//xs:enumeration/@value", namespaces=NS)
    assert vals == ["linear", "bicubic", "mitchell"]


@pytest.mark.parametrize("v", ["linear", "bicubic", "mitchell"])
def test_values_accepted(v):
    assert verdict(scene(f'resample="{v}"')) == "ok"


def test_absent_is_accepted():
    assert verdict(scene("")) == "ok"


@pytest.mark.parametrize("v", ["lanczos", "cubic", "Bicubic", ""])
def test_other_values_are_rejected_by_the_xsd(v):
    assert verdict(scene(f'resample="{v}"')) == "xsd"


def test_annotation_states_the_clamp_and_the_minified_rule():
    doc = XSD_TREE.xpath("//xs:complexType[@name='layerType']/xs:attribute[@name='resample']/xs:annotation",
                             namespaces=NS)[0]
    text = " ".join("".join(doc.itertext()).split())
    assert "with a clamp to the range of the four nearest texels" in text
    assert "trilinear mip filtering whatever @resample says" in text
