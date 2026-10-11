"""SREP 89 (amends SREP 72): the supersample clamp is [0, max(1, M)], M the largest sample of non-zero weight.

The XSD documents `project/@supersample` with the text SREP 89's Specification gives, and changes nothing else. The kit
cases of SREP 89 are valid, pending with their reason, and discriminate: their expected values (the filter with SREP
89's clamp) differ from what SREP 72's clamp gives by more than the kit's tolerance at n > 1, and equal the value at
n = 1. The neutral case holds: for SREP 72's own supersample cases (values in [0, 1]) the amended clamp gives the
values the kit already expects.
"""
import json
import os
import re
import sys

import pytest

etree = pytest.importorskip("lxml.etree")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
import kit_pending  # noqa: E402
import srep72_cases  # noqa: E402
import srep89_cases  # noqa: E402

XS = "http://www.w3.org/2001/XMLSchema"
NS = {"xs": XS}
SREP = open(os.path.join(ROOT, "srep", "srep-0089.md"), encoding="utf-8").read()
CASES = json.load(open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0089.json"), encoding="utf-8"))
KIT = json.load(open(os.path.join(ROOT, "conformance", "expected.json"), encoding="utf-8"))["cases"]
COLOUR_TOL = 3  # conformance/run.py: 8-bit code values


def norm(s):
    return " ".join((s or "").split())


def supersample_doc():
    xsd = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd")).getroot()
    (a,) = xsd.xpath("xs:complexType[@name='projectType']//xs:attribute[@name='supersample']", namespaces=NS)
    return norm("".join(a.xpath("xs:annotation/xs:documentation", namespaces=NS)[0].itertext()))


def test_xsd_documentation_is_the_text_srep_89_gives():
    m = re.search(r'text "clamped to \[0, 1\]" becomes\s+"(.*?)"', SREP, re.S)
    assert m, "SREP 89's Specification states the new text"
    new = norm(m.group(1))
    doc = supersample_doc()
    assert doc.endswith("and " + new), doc
    assert "clamped to [0, 1]" not in doc


def test_header_and_index():
    assert re.search(r"^Status:\s+Accepted$", SREP, re.M)
    assert re.search(r"^Requires:\s+72$", SREP, re.M)
    index = open(os.path.join(ROOT, "srep", "index.md"), encoding="utf-8").read()
    assert "| [89](srep-0089.md) | Amend SREP 72: the supersample clamp keeps values above 1 | Semantics | Accepted | 1.6 |" in index
    srep72 = open(os.path.join(ROOT, "srep", "srep-0072.md"), encoding="utf-8").read()
    assert re.search(r"^- 2026-10-10: SREP 89, .*amends Semantics 4, \"Edges and range\"", srep72, re.M)


def test_cases_are_in_the_kit_as_generated_and_pending():
    assert set(CASES) == {f"srep-0089-supersample-hdr-{s}" for s, _, _ in srep89_cases.RUNS}
    for name, case in CASES.items():
        assert KIT[name] == case["expected"], name
        assert case["expected"]["pending"] == kit_pending.PENDING[name], name
        assert "d7f12a2f" in case["expected"]["pending"]
        with open(os.path.join(ROOT, "conformance", "cases", name + ".xml"), encoding="utf-8") as f:
            assert f.read() == case["xml"], name


@pytest.mark.parametrize("slug,n,kernel", srep89_cases.RUNS)
def test_case_documents_state_what_srep_89_describes(slug, n, kernel):
    t = etree.fromstring(CASES[f"srep-0089-supersample-hdr-{slug}"]["xml"].encode())
    project = t.find("project")
    assert project.get("supersample", "1") == str(n)
    assert project.get("supersampleFilter", "box") == kernel
    cm = t.find("colorManagement")
    assert cm.get("toneMapping") == "none" and float(cm.get("exposure")) == srep89_cases.FINISH_STOPS
    (effect,) = t.findall("effects/effect")
    assert effect.get("type") == "exposure" and float(effect.get("exposure")) == srep89_cases.EFFECT_STOPS
    # the shape covers the frame: a flat working value of 4.0 everywhere
    s = t.find("composition/shape")
    assert (s.get("x"), s.get("y"), s.get("width"), s.get("height")) == ("0", "0", project.get("width"),
                                                                        project.get("height"))
    assert 2 ** srep89_cases.EFFECT_STOPS == 4


@pytest.mark.parametrize("slug,n,kernel", srep89_cases.RUNS)
def test_expected_values_equal_n1_and_discriminate(slug, n, kernel):
    at_n1 = srep89_cases.enc(4.0 * 2 ** srep89_cases.FINISH_STOPS)
    old = srep89_cases.enc(1.0 * 2 ** srep89_cases.FINISH_STOPS)
    for reg in CASES[f"srep-0089-supersample-hdr-{slug}"]["expected"]["regions"]:
        assert all(abs(v - at_n1) <= 0.05 for v in reg["rgb"]), reg
        if n > 1:
            # SREP 72's clamp gives the region 1.0 before finishing: a conforming engine of SREP 72 fails the case
            assert srep89_cases.region(n, kernel, reg["box"], srep89=False) == round(old, 1)
            assert all(abs(v - old) > COLOUR_TOL for v in reg["rgb"])


def test_amended_clamp():
    # a flat 4.0: the mean is 4.0, which the amended clamp keeps and SREP 72's cut to 1
    for kernel in ("box", "lanczos3"):
        for n in (2, 3, 4):
            for i in (0, 1, 5, 638, 639):
                assert srep89_cases.down(n, lambda k: 4.0, i, kernel, 640) == pytest.approx(4.0, abs=1e-12)
                assert srep89_cases.down(n, lambda k: 4.0, i, kernel, 640, srep89=False) == 1.0
    # Lanczos overshoot above the samples is still removed: a step from 0 to 4 never exceeds 4 nor falls below 0
    step = lambda k: 4.0 if k >= 200 else 0.0  # noqa: E731
    vals = [srep89_cases.down(2, step, i, "lanczos3", 640) for i in range(90, 110)]
    assert max(vals) == 4.0 and min(vals) == 0.0
    assert any(v == 4.0 for v in vals[11:]) and any(v == 0.0 for v in vals[:9])


@pytest.mark.parametrize("kernel", ("box", "lanczos3"))
def test_neutral_case_srep_72_cases_are_unchanged(kernel):
    """SREP 89, Neutral case: samples within [0, 1] give SREP 72's values; the kit's srep-0072-supersample cases
    (a step from 0 to 1 at x = 100, n = 2) keep their expected values."""
    want = KIT[f"srep-0072-supersample-{kernel}"]["regions"]
    step = lambda k: 1.0 if (k + 0.5) / 2 >= 100 else 0.0  # noqa: E731
    for reg in want:
        i = reg["box"][0]
        got = round(srep72_cases.enc(srep89_cases.down(2, step, i, kernel, 640)), 1)
        assert got == reg["rgb"][0], (i, got, reg["rgb"][0])
