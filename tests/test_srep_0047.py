"""SREP 47: object3D/joint (jointType). Its V5 version-gate term is applied centrally and is not tested here."""
import os

import pytest

from test_schema_rules import ROOT, doc as _doc, verdict


def doc(*args, **kw):
    """A scene document that declares version 1.2, the version these features need (V5)."""
    kw.setdefault("version", "1.2")
    return _doc(*args, **kw)


CASE = os.path.join(ROOT, "conformance", "cases", "srep-0047-joint-rotation.xml")
MODEL = '<mesh id="mm" src="x.glb" format="glb"/>'


def obj(inner):
    return ('<object3D id="t" primitive="sphere"/>'
            f'<object3D id="m" primitive="mesh" mesh="mm">{inner}</object3D>')


def test_case_validates():
    # version 1.2 joins scene/@version centrally, and V5 (not yet in this schema) will require it
    assert verdict(open(CASE, "rb").read()) == "ok"


@pytest.mark.parametrize("inner", [
    '<joint name="Hand"/>',
    '<joint name="Hand" rotationX="10" rotationY="-20.5" rotation="90"/>',
    '<joint name="Head" lookAt="t"/>',
    '<joint name="Head" lookAt="t" lookAxis="minus-z" influence="0" maxAngle="0"/>',
    '<joint name="Head" lookAt="t" influence="1" maxAngle="180"/>',
    '<joint name="Arm"><animate property="rotation"><key time="0" value="0"/><key time="1" value="90"/></animate></joint>',
    '<joint name="Eye L" rotation="5"/><joint name="Eye L" rotation="5"/>',  # several of one name compose
])
def test_accepted(inner):
    assert verdict(doc(obj(inner), assets=MODEL)) == "ok"


@pytest.mark.parametrize("axis", ["x", "minus-x", "y", "minus-y", "z", "minus-z"])
def test_every_look_axis_value_is_accepted(axis):
    assert verdict(doc(obj(f'<joint name="J" lookAt="t" lookAxis="{axis}"/>'), assets=MODEL)) == "ok"


@pytest.mark.parametrize("inner", [
    '<joint rotation="10"/>',                                # name is required
    '<joint name="J" lookAxis="w"/>',                        # not in the enumeration
    '<joint name="J" lookAxis="-z"/>',                       # the spelling is minus-z
    '<joint name="J" influence="1.5"/>',                     # unitDecimal is 0..1
    '<joint name="J" influence="-0.1"/>',
    '<joint name="J" maxAngle="-5"/>',                       # nonNegativeDecimal
    '<joint name="J" rotation="left"/>',
    '<joint name="J" translation="1"/>',                     # translation offsets are an open issue, not in 1.2
])
def test_rejected_by_xsd(inner):
    assert verdict(doc(obj(inner), assets=MODEL)) == "xsd"


def test_joint_is_a_child_of_object3d_only():
    body = '<shape id="s" shape="rect" width="5" height="5"><joint name="J"/></shape>'
    assert verdict(doc(body)) == "xsd"
