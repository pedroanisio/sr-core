"""SREP 27: seven annotation edits (documentation only). The case validates; the sentences are in the annotations."""
import os

import pytest

etree = pytest.importorskip("lxml.etree")
from test_schema_rules import ROOT, doc, verdict  # noqa: E402

NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
XSD_TREE = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))


def case(name):
    """A conformance case; the 1.2 version gate is applied centrally later, so the case is validated as 1.1."""
    with open(os.path.join(ROOT, "conformance", "cases", name), "rb") as f:
        return f.read().replace(b'<scene version="1.2">', b'<scene version="1.1">')


def docs_of(xpath):
    return " ".join("".join(d.itertext()) for d in XSD_TREE.xpath(xpath, namespaces=NS))


def test_case_validates():
    assert verdict(case("srep-0027-anchor-local.xml")) == "ok"


# (declaration whose annotation must carry the sentence, sentence); item 4 is withdrawn by SREP 36 (see the SREP)
SENTENCES = [
    ("//xs:simpleType[@name='colorType']/xs:annotation", "The shorthand #RGB and #RGBA is not accepted."),
    ("//xs:complexType[@name='expressionType']/xs:annotation",
     "Computes @property every frame; @property names an attribute the element's own type declares"),
    ("//xs:complexType[@name='expressionType']/xs:annotation",
     "a text layer's text, for one, is not an animatable property"),
    ("//xs:complexType[@name='radialGradientType']//xs:attribute[@name='aspect']/xs:annotation",
     "Multiplier on the gradient's x extent about its centre, applied after the units are mapped."),
    ("//xs:complexType[@name='textAnimatorType']//xs:attribute[@name='presetStart']/xs:annotation",
     "Time on the layer's parent timeline (composition time for a top-level layer)"),
    ("//xs:complexType[@name='cameraType']//xs:attribute[@name='fov']/xs:annotation",
     "Horizontal field of view in degrees, across the frame width"),
    ("//xs:attributeGroup[@name='transformAttributes']/xs:annotation",
     "anchorX and anchorY are in the node's local layout coordinates."),
]


@pytest.mark.parametrize("xpath,sentence", SENTENCES)
def test_annotation_carries_the_sentence(xpath, sentence):
    assert sentence in " ".join(docs_of(xpath).split())


def test_the_shorthand_colour_is_still_rejected_and_the_long_form_accepted():
    shape = '<shape id="r" shape="rect" width="10" height="10" fill="%s"/>'
    assert verdict(doc(shape % "#abc")) == "xsd"
    assert verdict(doc(shape % "#AABBCC")) == "ok"


def test_a_documentation_only_change_adds_no_declaration():
    # the anchor attributes the annotation talks about exist on the group's members, with their defaults
    ids = XSD_TREE.xpath("//xs:attributeGroup[@name='transformAttributes']/xs:attribute/@name", namespaces=NS)
    assert {"x", "y", "rotation", "anchorX", "anchorY"} <= set(ids)
