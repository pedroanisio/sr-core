"""SREP 38: object3D/@node, @materialOverride, and Schematron rules MOV1 (pair syntax) and MOV2 (ids name materials)."""
import glob
import os

import pytest

from test_schema_rules import ROOT, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0038-*.xml")))
HEAD = '<materials><material id="blue" baseColor="#0000FF"/><material id="red" baseColor="#FF0000"/></materials>'
ASSETS = '<mesh id="set" src="x.glb"/>'


def mesh(attrs, head=HEAD):
    # the XSD wants <assets> before <materials>, which doc() does not give with a head: build the scene here
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            f'<assets>{ASSETS}</assets>{head}<composition>'
            f'<object3D id="o" primitive="mesh" mesh="set" {attrs}/></composition></scene>')


def rules(v):
    return v.split(":", 1)[1].split(",") if v.startswith("sch:") else []


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    # version 1.2 is added to the enumeration centrally; the attributes are accepted in every version.
    assert verdict(open(case, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


def test_cases_exist():
    assert len(CASES) == 2


def test_node_alone_is_accepted():
    assert verdict(mesh('node="Knight"', head="")) == "ok"


@pytest.mark.parametrize("pairs", ["stone:blue", "stone:blue old:red", "  stone:blue   old:red  ", "a:blue a:red"])
def test_well_formed_overrides_are_accepted(pairs):
    assert verdict(mesh(f'materialOverride="{pairs}"')) == "ok"


@pytest.mark.parametrize("pairs", ["", "   ", "stone", "stone:", ":blue", "stone blue", "stone:blue old"])
def test_malformed_pairs_fail_mov1(pairs):
    assert "MOV1" in rules(verdict(mesh(f'materialOverride="{pairs}"')))


def test_malformed_pair_fails_mov2_as_well():
    assert rules(verdict(mesh('materialOverride="stone"'))) == ["MOV1", "MOV2"]


def test_unknown_document_material_fails_mov2():
    assert verdict(mesh('materialOverride="a:nosuch"')) == "sch:MOV2"
    assert verdict(mesh('materialOverride="a:nosuch"', head="")) == "sch:MOV2"


def test_id_after_the_first_colon_only_is_checked_against_ids():
    # the text after the first colon is the id: "b:c" has id "c", which names no material
    assert verdict(mesh('materialOverride="a:blue:c"')) == "sch:MOV2"


@pytest.mark.parametrize("n", [1, 2, 40, 200])
def test_pair_count_has_no_limit_and_one_wrong_pair_fails_once(n):
    good = " ".join(f"m{i}:blue" for i in range(n))
    assert verdict(mesh(f'materialOverride="{good}"')) == "ok"
    for wrong in (f"m0:nosuch {good}", f"{good} m{n}:nosuch"):
        assert verdict(mesh(f'materialOverride="{wrong}"')) == "sch:MOV2"


def test_one_diagnostic_for_the_object_however_many_pairs_fail():
    assert verdict(mesh('materialOverride="a:x b:y c:z"')) == "sch:MOV2"


def test_material_and_override_may_be_combined():
    assert verdict(mesh('material="blue" materialOverride="a:red"')) == "ok"
