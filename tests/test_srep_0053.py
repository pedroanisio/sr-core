"""SREP 53: wiggle(freq, amp, octaves, ampMult, t, hold). The expression body is an opaque string to the XSD and the Schematron
(no fragment, no rule id), so what the schema can check is that a six-argument call is a valid document and that the
documentation of `expression` lists the new arguments. The numeric semantics are checked by the engine against the cases."""
import os
import re

import pytest

from test_schema_rules import ROOT, doc, etree, verdict

CASES = os.path.join(ROOT, "conformance", "cases")
XS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def case(name):
    """A case of this SREP. It declares version="1.2"; the version enumeration and the V5 gate are applied centrally
    (release coordinator), so until then the document is checked as 1.1, which differs only in that attribute."""
    xml = open(os.path.join(CASES, name + ".xml"), "rb").read()
    assert b'<scene version="1.2">' in xml
    return xml.replace(b'<scene version="1.2">', b'<scene version="1.1">')


def with_expression(expr):
    return doc(f'<shape id="r" shape="rect" width="10" height="10"><expression property="x">{expr}</expression></shape>')


@pytest.mark.parametrize("name", ["srep-0053-wiggle-hold", "srep-0053-wiggle-hold-zero"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


def test_the_cases_call_wiggle_with_six_arguments():
    for name in ("srep-0053-wiggle-hold", "srep-0053-wiggle-hold-zero"):
        assert re.search(rb"wiggle\(\s*3,\s*20,\s*1,\s*0\.5,\s*[0-9.]+,\s*[0-9.]+\s*\)", case(name)), name


@pytest.mark.parametrize("expr", ["wiggle(2, 10)", "wiggle(2, 10, 1, 0.5)", "wiggle(2, 10, 1, 0.5, time)",
                                  "wiggle(2, 10, 1, 0.5, time, 1/12)"])
def test_calls_with_and_without_the_hold_validate(expr):
    assert verdict(with_expression(expr)) == "ok"


def test_the_expression_documentation_lists_t_and_hold():
    schema = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
    text = "".join(schema.xpath("//xs:complexType[@name='expressionType']/xs:annotation//text()", namespaces=XS))
    assert "wiggle(freq, amp[, octaves, ampMult, t, hold])" in " ".join(text.split())
