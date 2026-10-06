"""SREP 49: motionPath/@additive (no Schematron rule; neutral default false, accepted in every version)."""
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0049-motion-path-additive.xml")


def node(attrs):
    return f'<shape id="s" shape="rect" width="5" height="5" x="10" y="10"><motionPath path="M 0 0 L 100 0" {attrs}/></shape>'


def test_case_validates():
    # version 1.2 joins scene/@version centrally; the attribute is not version-gated, so check as 1.1
    assert verdict(open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


@pytest.mark.parametrize("attrs", ["", 'additive="false"', 'additive="true"', 'additive="1"', 'additive="0"',
                                   'additive="true" autoOrient="true" orientOffset="90" constantSpeed="false"'])
def test_accepted(attrs):
    assert verdict(doc(node(attrs))) == "ok"


@pytest.mark.parametrize("value", ["yes", "TRUE", "2", ""])
def test_rejected_by_xsd(value):
    assert verdict(doc(node(f'additive="{value}"'))) == "xsd"


def test_additive_is_accepted_in_version_1_0_syntax_terms():
    # motionPath itself needs 1.1 (V3); the attribute adds no gate of its own: with 1.1 it validates
    assert verdict(doc(node('additive="true"'), "1.1")) == "ok"
    assert verdict(doc(node('additive="true"'), "1.0")) == "sch:V3"


def test_the_path_attribute_is_still_required():
    body = '<shape id="s" shape="rect" width="5" height="5"><motionPath additive="true"/></shape>'
    assert verdict(doc(body)) == "xsd"
