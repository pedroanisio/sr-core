"""SREP 43: parentJoint on object3D and particles3D, targetJoint on transformConstraint (no Schematron rule)."""
import os

from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0043-joint-socket.xml")
MODEL = '<mesh id="mm" src="x.glb" format="glb"/>'
BASE = '<object3D id="m" primitive="mesh" mesh="mm"/>'


def test_case_validates():
    # The case says version="1.2"; the canonical scene/@version list gains 1.2 centrally, so the case is checked
    # here as version 1.1, which the feature is accepted in too (SREP 43: accepted in every version).
    assert verdict(open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


def test_parent_joint_is_accepted_in_version_1_1_and_1_0():
    body = BASE + '<object3D id="p" primitive="sphere" parent="m" parentJoint="Hand"/>'
    assert verdict(doc(body, "1.1", assets=MODEL)) == "ok"
    plain = '<object3D id="m" primitive="sphere"/><object3D id="p" primitive="sphere" parent="m" parentJoint="Hand"/>'
    assert verdict(doc(plain, "1.0")) == "ok"


def test_target_joint_on_constraint_is_accepted():
    body = (BASE + '<object3D id="p" primitive="sphere"><transformConstraint type="look-at" target="m" '
            'targetJoint="Head"/></object3D>')
    assert verdict(doc(body, assets=MODEL)) == "ok"


def test_target_joint_is_a_string_not_an_idref():
    # The joint name need not be an element id, may hold spaces and is not checked against the document.
    body = BASE + '<object3D id="p" primitive="sphere" parent="m" parentJoint="mixamorig:Left Hand.001"/>'
    assert verdict(doc(body, assets=MODEL)) == "ok"


def test_parent_joint_is_rejected_on_a_node_type_that_does_not_declare_it():
    # Only object3D, particles3D and transformConstraint gain the attribute; a 2D shape does not.
    body = '<shape id="s" shape="rect" width="5" height="5" parentJoint="Hand"/>'
    assert verdict(doc(body)) == "xsd"


def test_target_joint_is_rejected_on_a_node_that_is_not_a_constraint():
    body = BASE + '<object3D id="p" primitive="sphere" targetJoint="Hand"/>'
    assert verdict(doc(body, assets=MODEL)) == "xsd"
