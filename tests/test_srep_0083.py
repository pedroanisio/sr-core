"""SREP 83 (draft): the version gates of SREP 40 (V8, MSQ1, P3D1, OCN1, CRT1, FRX1, GEO1) refuse only the versions
before 1.3. The SREP's diff block, applied to the 1.5.0 Schematron (and, by content, to the files with the drafts of
SREPs 76 to 81), gives its kit cases their verdicts; no document of version 1.0 to 1.3 changes verdict; a 1.3 document
declared 1.4 or 1.5 keeps the verdict it had as 1.3.
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

SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
SREP = os.path.join(ROOT, "srep", "srep-0083.md")
GATES = ("V8", "MSQ1", "P3D1", "OCN1", "CRT1", "FRX1", "GEO1")

if gap.baseline() is None:
    pytest.skip("the schema 1.5.0 files are not available (no git tag, and schema/ has moved on)",
                allow_module_level=True)


def diff_block():
    blocks = re.findall(r"^```diff\n(.*?)^```", open(SREP, encoding="utf-8").read(), re.S | re.M)
    assert len(blocks) == 1, "SREP 83 has one diff block"
    return blocks[0]


def with_srep83(files, exact):
    files = {p: b.decode().split("\n") for p, b in files.items()}
    (gap.apply_patch if exact else gap.apply_amendment)(files, diff_block())
    return {p: "\n".join(v).encode() for p, v in files.items()}


def validators(files):
    xsd = etree.XMLSchema(etree.fromstring(files["schema/scene-render.xsd"]))
    sch = isoschematron.Schematron(etree.fromstring(files["schema/scene-render.sch"]), store_report=True)
    return xsd, sch


def verdict(validator, xml):
    xsd, sch = validator
    t = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode())
    if not xsd.validate(t):
        return "xsd"
    if not sch.validate(t):
        return "sch:" + ",".join(sorted(set(sch.validation_report.xpath("//svrl:failed-assert/@id", namespaces=SVRL))))
    return "ok"


BASE = validators(gap.baseline())
BASE83 = validators(with_srep83(gap.baseline(), exact=True))          # the 1.5.0 files and SREP 83
DRAFTS = validators(gap.proposed_schema())                              # with SREPs 76 to 81 and their amendments
DRAFTS83 = validators(with_srep83(gap.proposed_schema(), exact=False))
CASES = json.load(open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0083.json")))
OTHER = sorted(p for p in glob.glob(os.path.join(ROOT, "conformance", "cases", "*.xml"))
               if not os.path.basename(p).startswith("srep-0083-"))


def test_the_diff_changes_the_seven_gates_and_nothing_else():
    old = gap.baseline()["schema/scene-render.sch"].decode().split("\n")
    new = with_srep83(gap.baseline(), exact=True)["schema/scene-render.sch"].decode().split("\n")
    assert len(old) == len(new)
    changed = [(a, b) for a, b in zip(old, new) if a != b]
    ids = {m for a, b in changed for m in re.findall(r'<sch:assert id="([^"]+)"', b)}
    assert ids == set(GATES)
    earlier = "not(/scene/@version='1.0' or /scene/@version='1.1' or /scene/@version='1.2')"
    for a, b in changed:
        # each line changes only its version test (equality with 1.3 becomes "not one of 1.0 to 1.2") and its message
        assert "'1.3'" not in b and "'1.4'" not in b
        back = (b.replace(earlier, "/scene/@version='1.3'")
                .replace("/scene[@version='1.0' or @version='1.1' or @version='1.2']", "/scene[@version!='1.3']")
                .replace('version="1.3" or later.', 'version="1.3".'))
        assert back == a, (a, b)


@pytest.mark.parametrize("name", sorted(CASES))
def test_kit_case_verdict(name):
    case = CASES[name]["expected"]
    want = "ok" if case["findings"]["valid"] else "sch:" + ",".join(sorted(case["findings"]["codes"]))
    gate = case["rule"].split()[2:]
    if not case.get("requires"):
        # SREP 40's syntax only: the 1.5.0 files with SREP 83, and with the drafts of SREPs 76 to 81 as well
        assert verdict(BASE83, CASES[name]["xml"]) == want, name
        # without SREP 83 a later version is refused by the gate, and the others get the same verdict
        before = verdict(BASE, CASES[name]["xml"])
        later = re.search(r'<scene version="1\.[4-9]"', CASES[name]["xml"])
        assert before == ("sch:" + ",".join(gate) if later else want), (name, before)
    else:
        before = verdict(DRAFTS, CASES[name]["xml"])
        assert before.startswith("sch:") and set(gate) <= set(before[4:].split(",")), (name, before)
    assert verdict(DRAFTS83, CASES[name]["xml"]) == want, name


@pytest.mark.parametrize("case", OTHER, ids=os.path.basename)
def test_no_other_kit_case_changes_verdict(case):
    xml = open(case, "rb").read()
    assert verdict(BASE83, xml) == verdict(BASE, xml)
    if not re.search(r"srep-00(7[6-9]|8[01])-", case):
        return
    assert verdict(DRAFTS83, xml) == verdict(DRAFTS, xml)


def at_version(xml, version):
    out, n = re.subn(rb'<scene version="[^"]*"', b'<scene version="' + version.encode() + b'"', xml)
    return out if n == 1 else None


@pytest.mark.parametrize("case", [c for c in OTHER if re.search(rb'<scene version="1\.3"', open(c, "rb").read())],
                         ids=os.path.basename)
def test_a_1_3_document_keeps_its_verdict_in_every_version(case):
    """Every kit case of version 1.3: SREP 83 does not change its verdict, its verdict as 1.0, 1.1 or 1.2 (which the
    gates refuse) is unchanged, and as 1.4 or 1.5 it gets the verdict it has as 1.3."""
    xml = open(case, "rb").read()
    drafts = re.search(r"srep-00(7[6-9]|8[01])-", case)
    base, new = (DRAFTS, DRAFTS83) if drafts else (BASE, BASE83)
    as13 = verdict(new, xml)
    assert as13 == verdict(base, xml)
    for version in ("1.0", "1.1", "1.2"):
        assert verdict(new, at_version(xml, version)) == verdict(base, at_version(xml, version)), version
    for version in ("1.4", "1.5"):
        assert verdict(new, at_version(xml, version)) == as13, version
