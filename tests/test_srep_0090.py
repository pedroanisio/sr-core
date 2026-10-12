"""SREP 90 (Process, Active) records the exception to SREP 0 (Versioning) for the two kinds of 1.6.0 documents that
SREP 87 refuses; and the records of the same day on SREP 72: its PREC1 erratum (blackHole, accretionDisk) and Final.

SREP 90: its header and index row, SREP 0's Versioning and History pointing to it, the closed list of the two kinds
(with the kit cases that cover them), and the third kind of SREP 87 left out because SREP 87's erratum keeps it.

SREP 72: the list of 3D content for PREC1 names blackHole and accretionDisk, with a dated erratum line; the case that
was pending for PREC1 runs; the SREP is Final, as SREP 0 (Lifecycle 5) allows once its whole kit passes on the
reference and schema 1.6.0, which carries it, is released.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
import kit_pending  # noqa: E402


def read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


SREP90 = read("srep", "srep-0090.md")
SREP72 = read("srep", "srep-0072.md")
INDEX = read("srep", "index.md")


def header(text, field):
    m = re.search(rf"^{field}:\s+(.*)$", text, re.M)
    return m.group(1).strip() if m else None


def section(text, title):
    return text.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def test_srep_90_header_and_index():
    assert SREP90.startswith("```\nSREP:            90\n")
    assert header(SREP90, "Type") == "Process" and header(SREP90, "Status") == "Active"
    assert header(SREP90, "Schema-Version") == "n/a"
    assert {"0", "4", "86", "87"} <= set(header(SREP90, "Requires").replace(" ", "").split(","))
    res = header(SREP90, "Resolution")
    assert res.startswith("2026-10-11: accepted by the schema editor") and not re.search("[\"“”']", res)
    title = header(SREP90, "Title")
    assert len(title) < 60
    assert f"| [90](srep-0090.md) | {title} | Process | Active | n/a |" in INDEX


def test_srep_0_versioning_names_the_exception():
    srep0 = read("srep", "srep-0000.md")
    versioning = section(srep0, "Versioning")
    assert "[SREP 90](srep-0090.md)" in versioning and "SREP 87" in versioning
    assert re.search(r"^- 2026-10-11: Versioning names the exception that SREP 90 records", srep0, re.M)


def test_the_exception_is_a_closed_list_of_two_kinds():
    spec = " ".join(section(SREP90, "Specification").split())
    item1 = spec.split("1. **Kinds covered.**", 1)[1].split("2. **", 1)[0]
    assert "exactly these two kinds" in item1
    assert "`<shape id=\"p.g1\">`" in item1 and "`a.b.c`" in item1
    assert "`srep-0066-program-id-collision`" in item1 and "`srep-0087-program-ids-composed-collision`" in item1
    assert "**The third kind recorded at acceptance is not covered.**" in spec and "`link/@source`" in spec
    assert "**Nothing else.**" in spec and "its own Process SREP" in spec


def test_srep_87_and_the_changelog_point_to_srep_90():
    srep87 = read("srep", "srep-0087.md")
    assert "SREP 90" in header(srep87, "Resolution")
    log = read("schema", "CHANGELOG.md").split("\n## 1.7.0 ", 1)[1].split("\n## ", 1)[0]
    assert "by the exception to SREP 0 (Versioning) that SREP 90 (Process) records" in log


def test_srep_72_prec1_names_black_holes_and_accretion_disks():
    spec = " ".join(section(SREP72, "Specification").split())
    assert ("has 3D content (an `object3D`, `particles3D`, `ocean`, `blackHole` or `accretionDisk`), an engine MUST "
            "report the information finding **PREC1**") in spec
    assert re.search(r"^- 2026-10-11: erratum: the list of 3D content .*`blackHole` and\n  `accretionDisk`", SREP72,
                     re.M)


def test_srep_72_is_final_and_its_kit_has_no_pending_case():
    assert header(SREP72, "Status") == "Final"
    assert ("| [72](srep-0072.md) | Add pixel-exact options: precision, content rect, edges, supersampling | Standards "
            "| Final | 1.6 |") in INDEX
    assert re.search(r"^- 2026-10-11: Final \(SREP 0, Lifecycle 5\)", SREP72, re.M)
    impact = " ".join(section(SREP72, "Engine impact").split())
    assert "exact: all 9 kit cases pass" in impact and "6602b81d" in impact
    cases = json.loads(read("conformance", "srep_cases", "srep-0072.json"))
    assert len(cases) == 9
    assert not [n for n, c in cases.items() if "pending" in c["expected"]]
    assert not [n for n in kit_pending.PENDING if n.startswith("srep-0072-")]
    kit = json.loads(read("conformance", "expected.json"))["cases"]
    assert kit["srep-0072-precision-3d-note"]["findings"] == {"valid": True, "codes": ["PREC1"]}
    assert "pending" not in kit["srep-0072-precision-3d-note"]
