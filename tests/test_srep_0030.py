"""SREP 30: generator/@lineWidth (grid only) and rule R47."""
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


def scene(kind, extra=""):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            f'<assets><generator id="g" kind="{kind}" width="10" height="10" {extra}/></assets>'
            "<composition/></scene>")


def test_case_validates():
    assert verdict(case("srep-0030-grid-line-width.xml")) == "ok"


def test_attribute_is_declared_on_the_generator_asset_type_without_default():
    a = XSD_TREE.xpath("//xs:complexType[@name='generatorAssetType']/xs:attribute[@name='lineWidth']", namespaces=NS)
    assert len(a) == 1 and a[0].get("type") == "nonNegativeDecimal" and a[0].get("default") is None


def test_line_width_on_a_grid_is_accepted():
    for w in ("0", "1", "3", "0.5"):
        assert verdict(scene("grid", f'lineWidth="{w}"')) == "ok"


def test_absent_line_width_is_accepted_on_every_kind():
    for kind in ("grid", "noise", "fractal-noise", "checkerboard", "stripes"):
        assert verdict(scene(kind)) == "ok"


@pytest.mark.parametrize("kind", ["fractal-noise", "noise", "checkerboard", "stripes", "solid", "cells"])
def test_r47_line_width_on_another_kind_is_rejected(kind):
    assert verdict(scene(kind, 'lineWidth="2"')) == "sch:R47"


def test_negative_line_width_is_rejected_by_the_xsd():
    assert verdict(scene("grid", 'lineWidth="-1"')) == "xsd"
