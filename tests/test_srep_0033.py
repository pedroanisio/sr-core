"""SREP 33: safeAreaForce on every node and on symbol. SA01 and SA02 are report findings, not schema rules."""
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


def scene(body, symbols=""):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            + (f"<symbols>{symbols}</symbols>" if symbols else "") + f"<composition>{body}</composition></scene>")


def test_case_validates():
    assert verdict(case("srep-0033-safe-area-force.xml")) == "ok"


@pytest.mark.parametrize("path", ["//xs:attributeGroup[@name='nodeAttributes']",
                                  "//xs:complexType[@name='symbolType']"])
def test_declared_boolean_default_false_with_the_sentences(path):
    a = XSD_TREE.xpath(path + "/xs:attribute[@name='safeAreaForce']", namespaces=NS)
    assert len(a) == 1 and a[0].get("type") == "xs:boolean" and a[0].get("default") == "false"
    text = " ".join("".join(a[0].itertext()).split())
    assert "true exempts this node and everything it contains (for a symbol: every instance of it, and what it draws)" in text
    assert "validate lists every node that carries it (SA02)" in text


@pytest.mark.parametrize("body", [
    '<shape id="s" shape="rect" width="5" height="5" safeAreaForce="true"/>',
    '<shape id="s" shape="rect" width="5" height="5" safeAreaForce="false"/>',
    '<group id="g" safeAreaForce="true"/>',
    '<group id="g" safeAreaForce="1"/>',
])
def test_accepted_on_nodes(body):
    assert verdict(scene(body)) == "ok"


def test_accepted_on_a_symbol():
    assert verdict(scene('<instance id="i" symbol="sy"/>',
                         '<symbol id="sy" safeAreaForce="true"><shape id="in" shape="rect" width="5" height="5"/></symbol>')) == "ok"


def test_accepted_on_the_instance_of_a_symbol():
    assert verdict(scene('<instance id="i" symbol="sy" safeAreaForce="true"/>',
                         '<symbol id="sy"><shape id="in" shape="rect" width="5" height="5"/></symbol>')) == "ok"


@pytest.mark.parametrize("v", ["yes", "TRUE", ""])
def test_a_value_that_is_not_a_boolean_is_rejected(v):
    assert verdict(scene(f'<shape id="s" shape="rect" width="5" height="5" safeAreaForce="{v}"/>')) == "xsd"


def test_enforce_and_its_default_are_unchanged():
    a = XSD_TREE.xpath("//xs:complexType[@name='safeAreaType']/xs:attribute[@name='enforce']", namespaces=NS)[0]
    assert a.get("default") == "warn"
    assert a.xpath(".//xs:enumeration/@value", namespaces=NS) == ["off", "warn", "error"]
