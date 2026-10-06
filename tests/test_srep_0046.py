"""SREP 46: object3D/morph (morphType). Its V5 version-gate term is applied centrally and is not tested here."""
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0046-morph-by-name.xml")
MODEL = '<mesh id="mm" src="x.glb" format="glb"/>'


def obj(inner, attrs=""):
    return f'<object3D id="m" primitive="mesh" mesh="mm" {attrs}>{inner}</object3D>'


def test_case_validates():
    # version 1.2 joins scene/@version centrally, and V5 (not yet in this schema) will require it
    assert verdict(open(CASE, "rb").read()) == "ok"


@pytest.mark.parametrize("inner,attrs", [
    ('<morph name="smile"/>', ""),
    ('<morph name="smile" weight="0.5"/>', ""),
    ('<morph name="smile" weight="-0.25"/><morph name="blink" weight="1.5"/>', ""),
    ('<morph name="smile"><animate property="weight"><key time="0" value="0"/><key time="1" value="1"/></animate></morph>', ""),
    ('<morph name="smile"><expression property="weight">time</expression></morph>', ""),
    ('<morph name="smile" weight="0"/>', 'morphWeights="1 1"'),
])
def test_accepted(inner, attrs):
    assert verdict(doc(obj(inner, attrs), assets=MODEL)) == "ok"


@pytest.mark.parametrize("inner", [
    '<morph weight="1"/>',                       # name is required
    '<morph name="smile" weight="heavy"/>',      # weight is a number
    '<morph name="smile"><blob/></morph>',       # only animation elements as children
    '<morph name="smile" strength="1"/>',        # unknown attribute
])
def test_rejected_by_xsd(inner):
    assert verdict(doc(obj(inner), assets=MODEL)) == "xsd"


def test_morph_is_a_child_of_object3d_only():
    body = '<shape id="s" shape="rect" width="5" height="5"><morph name="smile"/></shape>'
    assert verdict(doc(body)) == "xsd"
