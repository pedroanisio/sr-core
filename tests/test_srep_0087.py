"""SREP 87 (amends SREP 66) is Accepted: a program's emitted ids are scoped by the program's id.

The record: SREP 87's header, the index row, SREP 66's History and Open issues, the Unreleased entry of the schema
changelog and the version it calls for. SREP 87 changes neither the XSD nor the Schematron.

The kit: the cases of srep_cases/srep-0087.json are those conformance/tools/srep87_cases.py writes, in expected.json and
cases/ as generated, each pending with the reason kit_pending.py gives (the reference implementation is not on main).
Their expected values follow from the SREP's rules and the modules' constant output, recomputed here from the
fragments: the namespaced ids are NCNames (Semantics 2), none has the form of a generated marker id (Hazards), and the
amended SREP 66 collision case writes the namespaced id `p.g1` (Backwards compatibility).
"""
import json
import os
import re
import subprocess
import sys

import pytest

etree = pytest.importorskip("lxml.etree")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
import kit_pending  # noqa: E402
import srep87_cases  # noqa: E402

SREP = open(os.path.join(ROOT, "srep", "srep-0087.md"), encoding="utf-8").read()
CASES = json.load(open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0087.json"), encoding="utf-8"))
CASES66 = json.load(open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0066.json"), encoding="utf-8"))
KIT = json.load(open(os.path.join(ROOT, "conformance", "expected.json"), encoding="utf-8"))["cases"]
NCNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*\Z")       # the ASCII subset of XML Namespaces 1.0 [4], enough here
GENERATED = re.compile(r"(?:beat|bar)\.[0-9]{1,19}\Z")    # SREP 57's G(x)


def header(field):
    m = re.search(rf"^{field}:\s+(.*)$", SREP, re.M)
    return m.group(1).strip() if m else None


def test_header():
    assert SREP.startswith("```\nSREP:            87\n"), "no front matter before the header (hygiene R4)"
    assert header("Status") == "Accepted"
    assert header("Type") == "Semantics"
    assert header("Schema-Version") == "1.7"
    assert header("Requires") == "57, 59, 66"
    assert "rs-perf" in header("Author")
    res = header("Resolution")
    assert res.startswith("2026-10-11: accepted by the schema editor") and not re.search("[\"“”']", res)
    assert "targets schema 1.7.0" in res


def test_index_and_srep_66_record_the_amendment():
    index = open(os.path.join(ROOT, "srep", "index.md"), encoding="utf-8").read()
    assert ("| [87](srep-0087.md) | Amend SREP 66: scope emitted ids by their program | Semantics | Accepted | 1.7 |"
            in index)
    rows = [int(n) for n in re.findall(r"^\| \[(\d+)\]", index, re.M)]
    assert rows == sorted(rows)
    srep66 = open(os.path.join(ROOT, "srep", "srep-0066.md"), encoding="utf-8").read()
    assert re.search(r"^- 2026-10-11: SREP 87, accepted .*amends Semantics 5", srep66, re.M)
    assert re.search(r"^- \*\*Id scoping\.\*\* .*\*\*Resolved 2026-10-11\*\* by SREP 87", srep66, re.M | re.S)


def test_no_schema_change_and_the_class_calls_for_1_7_0():
    log = open(os.path.join(ROOT, "schema", "CHANGELOG.md"), encoding="utf-8").read()
    unreleased = log.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    added = unreleased.split("### Added", 1)[1].split("### ", 1)[0]
    assert "(SREP 87, amends SREP 66)" in added
    assert "### Breaking\n\n### Added" in unreleased                  # nothing recorded as Breaking
    nxt = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "next", "schema"],
                         check=True, capture_output=True, text=True).stdout.strip()
    assert nxt.endswith("1.7.0"), nxt
    for f in ("scene-render.xsd", "scene-render.sch"):
        assert "SREP 87" not in open(os.path.join(ROOT, "schema", f), encoding="utf-8").read()


def test_cases_are_in_the_kit_as_generated_and_pending():
    assert set(CASES) == {f"srep-0087-program-ids-{s}" for s in srep87_cases.SLUGS}
    for name, case in CASES.items():
        assert KIT[name] == case["expected"], name
        assert case["expected"]["pending"] == kit_pending.PENDING[name], name
        assert case["expected"]["pending"].startswith(kit_pending.SREP87), name
        with open(os.path.join(ROOT, "conformance", "cases", name + ".xml"), encoding="utf-8") as f:
            assert f.read() == case["xml"], name


def test_modules_return_their_fragments():
    for slug, frag in srep87_cases.FRAGMENTS.items():
        data = open(os.path.join(ROOT, "conformance", "srep_cases", "assets", f"srep87-{slug}.wasm"), "rb").read()
        assert frag.encode() in data, slug
        etree.fromstring(f"<f>{frag}</f>".encode())                 # a well-formed fragment


def emitted(case_xml):
    """{program id: [local ids]} of a case document, from the fragments its modules return (srep66-rect: g1)."""
    t = etree.fromstring(case_xml.encode())
    out = {}
    for p in t.iter("program"):
        slug = re.search(r"srep(?:66|87)-([\w-]+)\.wasm", p.get("src")).group(1)
        frag = srep87_cases.RECT if slug == "rect" else srep87_cases.FRAGMENTS[slug]
        out[p.get("id")] = [e.get("id") for e in etree.fromstring(f"<f>{frag}</f>".encode()).iter() if e.get("id")]
    return out


@pytest.mark.parametrize("name", sorted(CASES))
def test_namespaced_ids_are_ncnames_and_never_generated_marker_ids(name):
    for p, local in emitted(CASES[name]["xml"]).items():
        for e in local:
            assert NCNAME.match(f"{p}.{e}") and not GENERATED.match(f"{p}.{e}"), (p, e)


def written_ids(case_xml):
    return [e.get("id") for e in etree.fromstring(case_xml.encode()).iter() if e.get("id")]


@pytest.mark.parametrize("name", sorted(CASES))
def test_verdicts_follow_semantics_1_and_2(name):
    """A case that expects PRG14 has a repeated local id or a namespaced id equal to another id; every other case
    has neither, and at least one case would collide under SREP 66 (an emitted id repeated across programs)."""
    ids = emitted(CASES[name]["xml"])
    namespaced = [f"{p}.{e}" for p, local in ids.items() for e in local]
    clash = (any(len(set(local)) < len(local) for local in ids.values())
             or len(set(namespaced)) < len(namespaced) or set(namespaced) & set(written_ids(CASES[name]["xml"])))
    want = CASES[name]["expected"].get("failure", {}).get("code")
    assert bool(clash) == (want == "PRG14"), (name, ids)


def test_some_cases_are_refused_by_srep_66_alone():
    def collides_under_66(xml):
        flat = [e for local in emitted(xml).values() for e in local]
        return len(set(flat)) < len(flat) or set(flat) & set(written_ids(xml))
    valid = [n for n, c in CASES.items() if "failure" not in c["expected"]]
    assert {n for n in valid if collides_under_66(CASES[n]["xml"])} >= {
        "srep-0087-program-ids-reuse", "srep-0087-program-ids-local-ref", "srep-0087-program-ids-local-wins",
        "srep-0087-program-ids-output-sha256"}


def test_matted_fragment_draws_the_left_half():
    """local-ref and local-wins: the rect s (40 x 20, centre 200, 120) matted by m (20 x 20, its right edge at x 200)
    leaves a red 20 x 20 square centred at (190, 120) per program, and m itself is hidden (DEFINITIONS D15)."""
    f = etree.fromstring(f"<f>{srep87_cases.FRAGMENTS['matted']}</f>".encode())
    m, s = f.findall("shape")
    assert s.get("matte") == "m" and m.get("id") == "m"
    left = lambda e: float(e.get("x")) - float(e.get("anchorX"))  # noqa: E731
    lo, hi = max(left(m), left(s)), min(left(m) + float(m.get("width")), left(s) + float(s.get("width")))
    assert ((lo + hi) / 2, hi - lo) == (190.0, 20.0)
    for name, cx, w in (("local-ref", 310, 260), ("local-wins", 190, 20)):
        exp = CASES[f"srep-0087-program-ids-{name}"]["expected"]
        assert (exp["red"]["cx"], exp["red"]["w"]) == (cx, w) and "green" in exp["absent"], name


def test_amended_srep_66_collision_case():
    case = CASES66["srep-0066-program-id-collision"]
    t = etree.fromstring(case["xml"].encode())
    assert [s.get("id") for s in t.iter("shape")] == ["p.g1"]
    assert [p.get("id") for p in t.iter("program")] == ["p"]
    assert case["expected"]["failure"] == {"code": "PRG14"}
    assert case["expected"]["pending"] == kit_pending.PENDING["srep-0066-program-id-collision"]
    assert case["expected"]["pending"].startswith(kit_pending.SREP87)


def test_generator_is_reproducible(tmp_path):
    """Rerunning the generator writes the committed files."""
    before = open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0087.json"), "rb").read()
    subprocess.run([sys.executable, os.path.join(ROOT, "conformance", "tools", "srep87_cases.py"), "--check"],
                   check=True, capture_output=True)
    assert open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0087.json"), "rb").read() == before
