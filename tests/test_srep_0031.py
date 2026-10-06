"""SREP 31: key/@overshoot and key/@period. No Schematron rule; the inert-attribute report is not a schema finding."""
import math
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


def scene(key_attrs):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/><composition>'
            '<shape id="s" shape="rect" width="10" height="10"><animate property="x">'
            f'<key time="0" value="0" {key_attrs}/><key time="1" value="10"/></animate></shape></composition></scene>')


def attr(name):
    a = XSD_TREE.xpath(f"//xs:complexType[@name='keyType']/xs:attribute[@name='{name}']", namespaces=NS)
    assert len(a) == 1
    return a[0]


def test_case_validates():
    assert verdict(case("srep-0031-back-elastic-keys.xml")) == "ok"


def test_declarations():
    assert attr("overshoot").get("type") == "nonNegativeDecimal" and attr("overshoot").get("default") is None
    assert attr("period").get("type") == "positiveDecimal" and attr("period").get("default") is None


@pytest.mark.parametrize("curve,a", [("back-in", 'overshoot="0.5"'), ("back-out", 'overshoot="1.70158"'),
                                     ("back-in-out", 'overshoot="0"'), ("elastic-in", 'period="0.2"'),
                                     ("elastic-out", 'period="0.6"'), ("elastic-in-out", 'period="0.45"')])
def test_accepted_on_the_curves_that_read_them(curve, a):
    assert verdict(scene(f'interpolation="{curve}" {a}')) == "ok"


def test_accepted_where_the_curve_ignores_them_the_report_is_not_a_schema_finding():
    assert verdict(scene('interpolation="linear" overshoot="2" period="0.5"')) == "ok"


@pytest.mark.parametrize("a", ['overshoot="-0.1"', 'period="0"', 'period="-1"', 'overshoot="x"'])
def test_out_of_range_values_are_rejected_by_the_xsd(a):
    assert verdict(scene(f'interpolation="back-out" {a}')) == "xsd"


# The case's expected values come from the SREP's formulas at u = 0.5 (keys at time -1 and 1, frame at time 0).
def back_out(u, c):
    return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2


def elastic_out(u, p):
    w, h = 2 * math.pi * 0.1 / p, 2.5 * p
    return 2 ** (-10 * u) * math.sin((10 * u - h) * w) + 1


def test_derivation_of_the_case_values():
    x = lambda f: 100 + 400 * f  # noqa: E731
    assert x(back_out(0.5, 0)) == pytest.approx(450.0)  # plain cubic: 1 - (1 - u)^3 = 0.875
    assert back_out(0.5, 0) == pytest.approx(1 - 0.5 ** 3)
    assert x(back_out(0.5, 1.70158)) == pytest.approx(535.079, abs=1e-3)
    assert x(elastic_out(0.5, 0.6)) == pytest.approx(493.75)  # sin(7 pi / 6) = -1/2: 1 - 1/64
    assert x(elastic_out(0.5, 0.3)) == pytest.approx(506.25)  # sin(5 pi / 6) = +1/2: 1 + 1/64
    assert back_out(0, 1.70158) == pytest.approx(0, abs=1e-12) and back_out(1, 1.70158) == pytest.approx(1)
