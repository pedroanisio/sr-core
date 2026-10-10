"""SREP 84 (draft): boolean and integer attributes are tested by value, not by spelling. The SREP's diff block, applied
to the 1.5.0 Schematron (exactly) and, by content, to the files with the drafts of SREPs 76 to 81 and SREP 83, and
its drafts block (SREP 78's PYRO9 to PYRO11), applied by content to the latter, give its kit cases their verdicts;
the diff changes only the rules the SREP lists; no other kit case changes verdict.
"""
import glob
import json
import os
import re
import sys

import pytest

etree = pytest.importorskip("lxml.etree")
from lxml import isoschematron  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
import engine_gap as gap  # noqa: E402
import srep84_cases  # noqa: E402

SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
SREP83 = os.path.join(ROOT, "srep", "srep-0083.md")
SREP84 = os.path.join(ROOT, "srep", "srep-0084.md")
ACCEPTED = ("C15", "C43", "R15", "R48-from", "R48-to", "VOL5", "C80", "GEO2")
DRAFTED = ("PYRO9", "PYRO10", "PYRO11")

if gap.baseline() is None:
    pytest.skip("the schema 1.5.0 files are not available (no git tag, and schema/ has moved on)",
                allow_module_level=True)


def blocks(path, fence):
    return re.findall(rf"^```{fence}\n(.*?)^```", open(path, encoding="utf-8").read(), re.S | re.M)


def apply(files, block, exact):
    files = {p: b.decode().split("\n") for p, b in files.items()}
    (gap.apply_patch if exact else gap.apply_amendment)(files, block)
    return {p: "\n".join(v).encode() for p, v in files.items()}


def validators(files):
    xsd = etree.XMLSchema(etree.fromstring(files["schema/scene-render.xsd"]))
    sch = isoschematron.Schematron(etree.fromstring(files["schema/scene-render.sch"]), store_report=True)
    return xsd, sch


def failed(validator, xml):
    """The verdict ("xsd", "ok" or "sch:<ids>") and the set of failed Schematron assertions."""
    xsd, sch = validator
    t = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode())
    if not xsd.validate(t):
        return "xsd", set()
    if not sch.validate(t):
        ids = set(sch.validation_report.xpath("//svrl:failed-assert/@id", namespaces=SVRL))
        return "sch:" + ",".join(sorted(ids)), ids
    return "ok", set()


def verdict(validator, xml):
    return failed(validator, xml)[0]


(MAIN,) = blocks(SREP84, "diff")
(DRAFT,) = blocks(SREP84, "diff drafts")
(V83,) = blocks(SREP83, "diff")
BASE_FILES = gap.baseline()
DRAFT_FILES = apply(gap.proposed_schema(), V83, exact=False)           # SREPs 76 to 81 (amended) and 83
BASE = validators(BASE_FILES)
BASE84 = validators(apply(BASE_FILES, MAIN, exact=True))
DRAFTS = validators(DRAFT_FILES)
DRAFTS84 = validators(apply(apply(DRAFT_FILES, MAIN, exact=False), DRAFT, exact=False))
CASES = json.load(open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0084.json")))
OTHER = sorted(p for p in glob.glob(os.path.join(ROOT, "conformance", "cases", "*.xml"))
               if not os.path.basename(p).startswith("srep-0084-"))


def changed_ids(old, new):
    old, new = old.decode().split("\n"), new.decode().split("\n")
    assert len(old) == len(new), "the diff replaces lines one for one"
    ids = [re.findall(r'<sch:assert id="([^"]+)"', b) for a, b in zip(old, new) if a != b]
    assert all(len(i) == 1 for i in ids), "each changed line is one assertion"
    return {i[0] for i in ids}


def test_the_diffs_change_the_listed_rules_and_nothing_else():
    assert changed_ids(BASE_FILES["schema/scene-render.sch"],
                       apply(BASE_FILES, MAIN, exact=True)["schema/scene-render.sch"]) == set(ACCEPTED)
    drafts = DRAFT_FILES["schema/scene-render.sch"]
    assert changed_ids(drafts, apply(apply(DRAFT_FILES, MAIN, exact=False), DRAFT, exact=False)
                       ["schema/scene-render.sch"]) == set(ACCEPTED + DRAFTED)
    assert "scene-render.xsd" not in MAIN + DRAFT, "the XSD does not change"


def test_no_rule_compares_a_boolean_or_an_integer_by_its_spelling():
    """What the SREP lists is all there is: after it, no assertion of the 1.5.0 files or of the drafts tests a
    boolean attribute against 'true', 'false', '1' or '0' without normalize-space, and C15 tests no '0'."""
    literal = re.compile(r"@(\w+)\s*!?=\s*'(true|false|1|0)'")
    after = apply(apply(DRAFT_FILES, MAIN, exact=False), DRAFT, exact=False)["schema/scene-render.sch"].decode()
    left = {m.group(0) for m in literal.finditer(after)}
    assert not left, left
    before = DRAFT_FILES["schema/scene-render.sch"].decode()
    ids = {re.search(r'id="([^"]+)"', line).group(1) for line in before.split("\n") if literal.search(line)}
    # BH5 to BH8 (SREP 76) and CRT11, CRT12 (SREP 77) already read every form, by those drafts' own amendments
    assert ids == {"C15", "C43", "R15", "R48-from", "R48-to", "VOL5", "PYRO9", "PYRO10"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_kit_case_verdict(name):
    case = CASES[name]["expected"]
    want = case["findings"]
    before = DRAFTS if case.get("requires") else BASE
    after = (DRAFTS84,) if case.get("requires") else (BASE84, DRAFTS84)
    for v in after:
        got, ids = failed(v, CASES[name]["xml"])
        if "absent" in want:
            # the document names a file the kit does not ship; the rule is absent and the schemas accept it
            assert got == "ok" and not ids & set(want["absent"]), (name, got)
        else:
            assert got == ("ok" if want["valid"] else "sch:" + ",".join(sorted(want["codes"]))), (name, got)
    assert verdict(before, CASES[name]["xml"]) == srep84_cases.BEFORE[name], name


def test_the_cases_cover_every_changed_rule_with_a_changed_verdict():
    """Each rule has at least one case whose verdict SREP 84 changes (it was bypassed or misfired before)."""
    changed = set()
    for name, c in CASES.items():
        want = c["expected"]["findings"]
        now = "ok" if "absent" in want or want["valid"] else "sch:" + ",".join(sorted(want["codes"]))
        if now != srep84_cases.BEFORE[name]:
            changed.add(c["expected"]["rule"].split()[2])
    assert changed == set(ACCEPTED + DRAFTED)


@pytest.mark.parametrize("case", OTHER, ids=os.path.basename)
def test_no_other_kit_case_changes_verdict(case):
    xml = open(case, "rb").read()
    assert verdict(BASE84, xml) == verdict(BASE, xml)
    assert verdict(DRAFTS84, xml) == verdict(DRAFTS, xml)
