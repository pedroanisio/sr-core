"""SREP 40: volumetric and large-scale cinematic effects (schema 1.3).

The fixtures are documents of the Rust reference's corpus (tests/fixtures/srep-0040/): every valid scene version 1.3
document must validate, and every invalid document must be rejected naming the rule its header expects. The SREP
gives the schema surface as an inventory; the checks here are the executable form of it.
"""
import glob
import os
import re

import pytest

from test_schema_rules import ROOT, verdict

FIX = os.path.join(ROOT, "tests", "fixtures", "srep-0040")
VALID = sorted(glob.glob(os.path.join(FIX, "valid", "*.xml")))
INVALID = sorted(glob.glob(os.path.join(FIX, "invalid", "*.xml")))
SCH_IDS = set(re.findall(r'<sch:assert id="([^"]+)"', open(os.path.join(ROOT, "schema", "scene-render.sch")).read()))


def expected_codes(path):
    m = re.search(rb"<!-- expect: ([^>]*?) -->", open(path, "rb").read())
    return m.group(1).decode().split() if m else []


def test_the_fixtures_are_there():
    assert len(VALID) >= 30 and len(INVALID) >= 60


@pytest.mark.parametrize("path", VALID, ids=os.path.basename)
def test_valid_version_1_3_documents_validate(path):
    assert verdict(open(path, "rb").read()) == "ok"


@pytest.mark.parametrize("path", INVALID, ids=os.path.basename)
def test_invalid_documents_are_rejected_with_the_expected_rule(path):
    want = {c for c in expected_codes(path) if c in SCH_IDS}
    assert want, path
    got = verdict(open(path, "rb").read())
    assert got.startswith("sch:") and want <= set(got[4:].split(",")), (want, got)


def test_every_rule_family_of_the_srep_has_a_rejecting_document():
    families = ("VOL", "PYRO", "PYC", "P3D", "OCN", "CRT", "FRX", "MSQ", "GEO")
    covered = {c for p in INVALID for c in expected_codes(p)}
    ids = {i for i in SCH_IDS if i.startswith(families) or i == "V8"}
    missing = sorted(ids - covered)
    assert missing == [], f"rules without a rejecting fixture: {missing}"


def test_version_1_3_is_accepted_and_the_gate_rejects_1_2_documents_using_volumes():
    assert verdict(b'<scene version="1.3"><project width="10" height="10" fps="1" duration="1"/><composition/></scene>') == "ok"
    doc = (b'<scene version="1.2"><project width="10" height="10" fps="1" duration="1"/><composition>'
           b'<object3D id="o" primitive="sphere"><medium extinction="1"/></object3D></composition></scene>')
    got = verdict(doc)
    assert got.startswith("sch:") and "V8" in got[4:].split(","), got
