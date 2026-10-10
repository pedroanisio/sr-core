"""SREPs 76 to 81, the reference engine's schema extensions taken upstream: the diff blocks of the SREPs, applied in
order to the 1.5.0 files, rebuild the engine's vendored XSD and Schematron byte for byte (the hashes recorded by
conformance/tools/engine_gap.py); after each SREP the schema compiles; the kit cases taken from the engine's corpus get
the verdicts the corpus gives; and every existing kit case keeps the verdict it has under 1.5.0.
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
GAP = json.load(open(gap.DEFAULT_OUT))
SREPS = range(76, 82)
CASE_FILES = {n: os.path.join(ROOT, "conformance", "srep_cases", f"srep-{n:04d}.json") for n in range(76, 81)}

if gap.baseline() is None:
    pytest.skip("the schema 1.5.0 files are not available (no git tag, and schema/ has moved on)",
                allow_module_level=True)


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


PROPOSED = validators(gap.proposed_schema())
BASE = validators(gap.baseline())
UPTO = {n: validators(gap.proposed_schema(n)) for n in range(76, 81)}


def test_the_inventory_is_complete_and_classified():
    assert not GAP["unclassified"] and not GAP["removed"] and not GAP["stage_problems"]
    assert not GAP["rule_id_collisions"] and not GAP["excluded"]
    assert {e["srep"] for e in GAP["items"]} == set(SREPS)
    assert all(e["introduced"] for e in GAP["items"]), "every item has the engine commit that introduced it"
    n = sum(c[f][s] for c in GAP["counts"].values() for f in ("xsd", "sch") for s in ("added", "changed"))
    assert n == len(GAP["items"])


def test_every_srep_has_its_diff_block_and_lists_its_items():
    for f in GAP["features"]:
        text = open(os.path.join(ROOT, "srep", f"srep-{f['srep']:04d}.md"), encoding="utf-8").read()
        assert re.search(r"^```diff\n", text, re.M), f"SREP {f['srep']} has no diff block"
        assert re.search(r"^Status:\s+Draft", text, re.M)


def test_the_diff_blocks_rebuild_the_engine_files_byte_for_byte():
    assert gap.verify() == []


@pytest.mark.parametrize("upto", SREPS)
def test_the_schema_compiles_after_each_srep(upto):
    validators(gap.proposed_schema(upto))


CASES = {name: (n, c) for n, path in CASE_FILES.items() for name, c in json.load(open(path)).items()}


@pytest.mark.parametrize("name", sorted(CASES))
def test_kit_case_verdict(name):
    n, case = CASES[name]
    want = case["expected"]["findings"]
    rules = sorted(c for c in want.get("codes", []) if not c.startswith(("W", "A")))
    # each SREP's cases hold with the SREPs up to it, and with all of them
    for v in (UPTO[n], PROPOSED):
        got = verdict(v, case["xml"])
        assert got == ("ok" if want["valid"] else "sch:" + ",".join(rules)), (name, got)


@pytest.mark.parametrize("case", sorted(p for p in glob.glob(os.path.join(ROOT, "conformance", "cases", "*.xml"))
                                        if not re.search(r"srep-00(7[6-9]|8[01])-", p)), ids=os.path.basename)
def test_existing_cases_keep_their_verdict(case):
    xml = open(case, "rb").read()
    assert verdict(PROPOSED, xml) == verdict(BASE, xml)
