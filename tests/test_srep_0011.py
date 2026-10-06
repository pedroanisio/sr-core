"""SREP 11: rigid bodies on object3D. The fragments (rigidBody3DType, ball and axis attributes on constraints,
z and forceZ on force fields, gravityZ on physics, C48) and the SREP's four cases.

The 1.2 enumeration value of scene/@version and the version gate V5 are applied centrally, so the cases are
checked here with as written (version="1.2")."""
import glob
import json
import os

import pytest

from test_schema_rules import ROOT, doc as _doc, verdict


def doc(*args, **kw):
    """A scene document that declares version 1.2, the version these features need (V5)."""
    kw.setdefault("version", "1.2")
    return _doc(*args, **kw)


CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0011-*.xml")))


def as_1_1(path):
    return open(path, "rb").read()


def body(attrs="", primitive="sphere", physics="<physics/>"):
    x = doc(f'<object3D id="o" primitive="{primitive}"><rigidBody {attrs}/></object3D>')
    return x.replace("</composition></scene>", "</composition>" + physics + "</scene>")


def with_physics(inner, attrs=""):
    x = doc('<object3D id="a" primitive="sphere"><rigidBody/></object3D><object3D id="b" primitive="box"><rigidBody type="static"/></object3D>')
    return x.replace("</composition></scene>", f"</composition><physics {attrs}>{inner}</physics></scene>")


def test_the_four_cases_exist():
    assert [os.path.basename(c) for c in CASES] == ["srep-0011-rigid3d-damped.xml", "srep-0011-rigid3d-fall.xml",
                                                    "srep-0011-rigid3d-rest.xml", "srep-0011-rigid3d-velocity.xml"]


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    assert verdict(as_1_1(case)) == "ok"


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_has_an_expected_entry(case):
    cases = json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"]
    assert cases[os.path.basename(case)[:-4]]["rule"] == "SREP 11"


def test_the_fall_case_expectation_follows_the_srep_formula():
    """SREP 11 Conformance: N = 40 substeps of h = 0.1 / 4 s, d = g h^2 N (N + 1) / 2 metres at 20 px per metre."""
    g, h, n, ppm = 9.80665, 0.1 / 4, 40, 20
    d = g * h * h * n * (n + 1) / 2
    assert round(d, 4) == 5.0259
    cases = json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"]
    assert cases["srep-0011-rigid3d-fall"]["red"]["cy"] == pytest.approx(100 + d * ppm, abs=0.01)


GOOD = {
    "default body": body(),
    "every attribute": body('type="kinematic" shape="decomposition" mass="2" friction="1" restitution="0.5" '
                            'linearDamping="1" angularDamping="0" velocityX="1" velocityY="-2" velocityZ="3" '
                            'angularVelocityX="10" angularVelocityY="20" angularVelocityZ="30" collisionGroup="2" '
                            'collidesWith="1 2" sensor="true" fixedRotation="true" bullet="true" activateAt="-1.5"',
                            primitive="box"),
    "capsule shape": body('shape="capsule"', "capsule"),
    "static trimesh": body('shape="trimesh" type="static"', "torus"),
    "kinematic trimesh": body('shape="trimesh" type="kinematic"', "torus"),
    "dynamic convex hull": body('shape="convex-hull"', "torus"),
    "ball constraint": with_physics('<constraint id="c" type="ball" a="a" b="b" x="1" y="2" z="3"/>'),
    "hinge about an axis": with_physics('<constraint id="c" type="hinge" a="a" b="b" axisX="0" axisY="1" axisZ="0"/>'),
    "slider and motor axes": with_physics('<constraint id="c" type="slider" a="a" b="b" axisX="1"/>'
                                          '<constraint id="d" type="motor" a="a" b="b" axisZ="1" motorSpeed="2"/>'),
    "force field with depth": with_physics('<forceField id="f" type="radial" x="1" y="2" z="3" forceZ="4" strength="5"/>'),
    "gravity along z": with_physics("", 'gravityZ="-9.8"'),
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_accepted(name):
    assert verdict(GOOD[name]) == "ok"


SCH_BAD = {
    "C48 trimesh, default type (dynamic)": (body('shape="trimesh"', "torus"), "C48"),
    "C48 trimesh, dynamic": (body('shape="trimesh" type="dynamic"', "torus"), "C48"),
}


@pytest.mark.parametrize("name", sorted(SCH_BAD))
def test_rejected_by_schematron(name):
    xml, rule = SCH_BAD[name]
    v = verdict(xml)
    assert v.startswith("sch:") and rule in v.split(":", 1)[1].split(","), v


def test_c48_does_not_apply_to_the_2d_rigid_body():
    x = doc('<vector id="v" shape="rect"><rigidBody shape="trimesh"/></vector>')
    assert "C48" not in verdict(x)


XSD_BAD = {
    "shape unknown": body('shape="polygon"'),
    "type unknown": body('type="ghost"'),
    "mass 0": body('mass="0"'),
    "friction 2": body('friction="2"'),
    "linearDamping 1.5": body('linearDamping="1.5"'),
    "negative collisionGroup": body('collisionGroup="-1"'),
    "sensor not boolean": body('sensor="perhaps"'),
    "the 2D attribute angularVelocity": body('angularVelocity="3"'),
    "the 2D attribute path": body('path="M0 0"'),
    "constraint type unknown": with_physics('<constraint id="c" type="cone" a="a" b="b"/>'),
    "constraint axisX not a number": with_physics('<constraint id="c" type="hinge" a="a" b="b" axisX="up"/>'),
    "force field z not a number": with_physics('<forceField id="f" type="radial" z="deep"/>'),
    "gravityZ not a number": with_physics("", 'gravityZ="down"'),
}


@pytest.mark.parametrize("name", sorted(XSD_BAD))
def test_rejected_by_xsd(name):
    assert verdict(XSD_BAD[name]) == "xsd"
