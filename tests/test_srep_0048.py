"""SREP 48: penner(...) and propAtTime(...) expression built-ins. The SREP changes only the documentation of
`expression`; an expression is an opaque string to the schema, so the tests pin that and the documented names."""
import os
import re

from test_schema_rules import ROOT, XSD, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0048-expr-penner-prop-at-time.xml")


def expr(text):
    return (f'<shape id="s" shape="rect" width="5" height="5"><expression property="x">{text}</expression></shape>')


def test_case_validates():
    # version 1.2 joins scene/@version centrally; the SREP is not version-gated, so check as 1.1
    assert verdict(open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


def test_the_expression_documentation_lists_both_built_ins():
    text = open(os.path.join(ROOT, "schema", "scene-render.xsd")).read()
    m = re.search(r'<xs:complexType name="expressionType">\s*<xs:annotation><xs:documentation>(.*?)</xs:documentation>',
                  text, re.S)
    assert m
    docs = " ".join(m.group(1).split())
    assert 'propAtTime("id.property", t)' in docs
    assert 'penner("curve", u)' in docs
    assert 'prop("id.property")' in docs and "valueAtTime(t)" in docs  # the existing entries stay


def test_calls_are_accepted_as_expression_text():
    assert verdict(doc(expr('100 * penner("quad-in", 0.5)'))) == "ok"
    assert verdict(doc(expr('propAtTime("s.x", time - 1)'))) == "ok"


def test_the_schema_does_not_judge_the_function_names():
    # an unknown curve name is a compile error of the engine (SREP 48 Semantics), a validation-level error in the
    # engine, not in this schema: the expression is an opaque string here.
    assert verdict(doc(expr('penner("quad-inn", 0.5)'))) == "ok"


def test_expression_still_needs_its_property():
    assert verdict(doc('<shape id="s" shape="rect" width="5" height="5"><expression>1</expression></shape>')) == "xsd"
