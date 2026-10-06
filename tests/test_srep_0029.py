"""SREP 29: halftone and selective-color meanings (documentation of effectType); no schema rule is added."""
import os

import pytest

etree = pytest.importorskip("lxml.etree")
from test_schema_rules import ROOT, verdict  # noqa: E402

NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
XSD_TREE = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
EFFECT = XSD_TREE.xpath("//xs:complexType[@name='effectType']", namespaces=NS)[0]


def case(name):
    """A conformance case; the 1.2 version gate is applied centrally later, so the case is validated as 1.1."""
    with open(os.path.join(ROOT, "conformance", "cases", name), "rb") as f:
        return f.read().replace(b'<scene version="1.2">', b'<scene version="1.1">')


def scene(effect):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            '<composition><shape id="s" shape="rect" width="10" height="10" effects="e"/></composition>'
            f"<effects>{effect}</effects></scene>")


def test_case_validates():
    assert verdict(case("srep-0029-effect-meanings.xml")) == "ok"


def effect_doc():
    return " ".join("".join(EFFECT.xpath("xs:annotation/xs:documentation", namespaces=NS)[0].itertext()).split())


@pytest.mark.parametrize("sentence", [
    "selective-color: @hue (degrees) or @color (its hue) centres a window of width @tolerance; inside it @saturation scales and @brightness adds; @amount mixes the result with the original. @channel is not read.",
    "halftone: @size is the cell, @angle the screen's angle (default 0), @color the ink (default black) and @paint the ground between the dots (default white).",
])
def test_effect_type_documents_the_two_effects(sentence):
    assert sentence in effect_doc()


def test_halftone_angle_default_is_the_declared_zero():
    # the SREP's order of argument: the declared default decides, so a halftone without @angle is at 0 degrees
    attr = EFFECT.xpath("xs:attribute[@name='angle']", namespaces=NS)[0]
    assert attr.get("default") == "0"


def test_halftone_takes_ink_ground_angle_and_amount():
    assert verdict(scene('<effect id="e" type="halftone" size="8" angle="0" color="#FF0000FF" paint="#0000FFFF" amount="0.5"/>')) == "ok"


def test_halftone_transparent_ground_is_expressible():
    assert verdict(scene('<effect id="e" type="halftone" paint="#00000000"/>')) == "ok"


def test_selective_color_takes_hue_or_colour_and_tolerance():
    assert verdict(scene('<effect id="e" type="selective-color" hue="120" tolerance="0.3" saturation="0" brightness="0.1"/>')) == "ok"
    assert verdict(scene('<effect id="e" type="selective-color" color="#FF0000FF" amount="0.5"/>')) == "ok"


def test_shorthand_ink_is_rejected():
    assert verdict(scene('<effect id="e" type="halftone" color="#f00"/>')) == "xsd"
