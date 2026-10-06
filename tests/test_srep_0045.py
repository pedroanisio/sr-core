"""SREP 45: link follow, timeConstant, stiffness, damping, mass (no Schematron rule; neutral defaults)."""
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0045-link-follow-constant.xml")


def link(attrs):
    return ('<shape id="a" shape="rect" width="5" height="5" x="3"/>'
            f'<shape id="b" shape="rect" width="5" height="5"><link property="x" source="a.x" {attrs}/></shape>')


def test_case_validates():
    # version 1.2 joins the scene/@version list centrally; the attributes are not version-gated, so check as 1.1
    assert verdict(open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


@pytest.mark.parametrize("attrs", [
    "", 'follow="none"', 'follow="exponential"', 'follow="exponential" timeConstant="0.25"',
    'follow="spring"', 'follow="spring" stiffness="200" damping="0" mass="2.5"',
    'delay="0.5" smoothing="0.1" follow="spring"',  # accepted by the schema; an engine reports follow ignored
])
def test_accepted(attrs):
    assert verdict(doc(link(attrs))) == "ok"


@pytest.mark.parametrize("attrs", [
    'follow="banana"', 'follow="Spring"', 'timeConstant="0"', 'timeConstant="-1"', 'timeConstant="fast"',
    'stiffness="0"', 'damping="-1"', 'mass="0"',
])
def test_rejected_by_xsd(attrs):
    assert verdict(doc(link(attrs))) == "xsd"


def test_follow_is_not_a_link_only_attribute_of_other_elements():
    assert verdict(doc('<shape id="b" shape="rect" width="5" height="5" follow="spring"/>')) == "xsd"
