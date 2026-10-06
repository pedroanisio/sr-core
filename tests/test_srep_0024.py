"""SREP 24: force-field scope. useForceFields (xs:boolean, default true) on particleEmitter, flock and fluid;
forceFields keeps rule R34. No Schematron rule is added.

The case declares version="1.2"; the 1.2 value of scene/@version is applied centrally, so it is validated here
with the version attribute set to 1.1 (the attribute is accepted in every version).
"""
import os

import pytest
from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0024-force-field-scope.xml")
PHYSICS = '<physics><forceField id="w" type="wind"/></physics>'
ELEMENTS = {
    "particleEmitter": '<particleEmitter id="e" {a}/>',
    "flock": '<flock id="e" width="10" height="10" {a}/>',
    "fluid": '<fluid id="e" width="10" height="10" {a}/>',
}


def make(kind, attrs, physics=PHYSICS):
    return doc(ELEMENTS[kind].format(a=attrs)).replace("</composition></scene>", "</composition>" + physics + "</scene>")


def test_case_validates():
    assert verdict(open(CASE).read().replace('version="1.2"', 'version="1.1"').encode()) == "ok"


@pytest.mark.parametrize("kind", sorted(ELEMENTS))
@pytest.mark.parametrize("attrs", ['useForceFields="false"', 'useForceFields="true"', 'useForceFields="0"',
                                   'useForceFields="false" forceFields="w"', 'forceFields="w"', ''])
def test_accepted(kind, attrs):
    assert verdict(make(kind, attrs)) == "ok"


@pytest.mark.parametrize("kind", sorted(ELEMENTS))
def test_non_boolean_is_rejected_by_xsd(kind):
    assert verdict(make(kind, 'useForceFields="never"')) == "xsd"


@pytest.mark.parametrize("kind", sorted(ELEMENTS))
def test_r34_still_applies_to_the_list(kind):
    assert verdict(make(kind, 'forceFields="nope"')) == "sch:R34"
    # useForceFields="false" does not excuse a list that names no force field: the rule is on the list
    assert verdict(make(kind, 'useForceFields="false" forceFields="nope"')) == "sch:R34"
