"""SREP 87 (amends SREP 66) is Accepted: a program's emitted ids are scoped by the program's id.

The record: SREP 87's header, the index row, SREP 66's History and Open issues, the 1.7.0 entry of the schema
changelog and the version it calls for. SREP 87 changes neither the XSD nor the Schematron. Its class is Added by the
exception SREP 90 records (Open issues 7, decided), and its erratum of 2026-10-11 adds link/@source, the overrides of
an instance or an include and the bone names of skin weights to the positions of rules 3 and 4 (Open issues 6).

The kit: the cases of srep_cases/srep-0087.json are those conformance/tools/srep87_cases.py writes, in expected.json and
cases/ as generated. The reference implementation is on main and passes them; only the cases whose check run.py cannot
express (failed renders, a render comparison) stay pending, with the hand check in the reason kit_pending.py gives.
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


LOG = open(os.path.join(ROOT, "schema", "CHANGELOG.md"), encoding="utf-8").read()
RELEASED = LOG.split("\n## 1.7.0 ", 1)[1].split("\n## ", 1)[0]     # SREP 87 is released in schema 1.7.0
ENTRY = RELEASED.split("### Added", 1)[1].split("### ", 1)[0]


def section(title):
    return SREP.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def test_no_schema_change_and_the_class_added_by_srep_90_calls_for_1_7_0():
    """The schema editor decided the class on 2026-10-11 (Open issues 7): Added, by the exception to SREP 0 that SREP
    90 records. The changelog and Backwards compatibility say so, no longer provisionally, and the release that
    carries it is 1.7.0 (a MINOR, nothing under Breaking)."""
    assert "(SREP 87, amends SREP 66)" in ENTRY
    assert "### Breaking" not in RELEASED                               # nothing under Breaking
    assert "provisional" not in ENTRY and "SREP 90" in ENTRY
    assert section("Backwards compatibility").lstrip().startswith(
        "**Class: Added (SREP 4), by the exception that SREP 90 records (Process).**")
    assert "class Added by the exception that SREP 90 records" in header("Resolution")
    chk = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "check"],
                         check=True, capture_output=True, text=True).stdout.strip()
    assert "schema 1.7.0" in chk, chk
    for f in ("scene-render.xsd", "scene-render.sch"):
        assert "SREP 87" not in open(os.path.join(ROOT, "schema", f), encoding="utf-8").read()


def test_the_class_is_not_derived_from_the_srep_85_decision():
    """SREP 0 (Versioning): a MINOR keeps every 1.N document valid. The SREP 85 decision answered SREP 85 (refusals
    argued as SREP 4's fourth Fixed kind); SREP 87's newly refused documents had a meaning under SREP 66. The record
    must not attribute the class to that decision, and Open issues 7 must offer the version gate, Breaking and an
    exception granted by the editor."""
    for text in (ENTRY, SREP):
        assert "after the schema editor's decision" not in text
        assert "which kept narrow refusals of that kind out of a MAJOR release" not in text
    issue = section("Open issues").split("\n7. ", 1)[1]
    assert "SREP 0" in issue and "version gate" in issue and "Breaking" in issue and "2.0.0" in issue
    assert "**Decided 2026-10-11:** Added by an exception." in issue and "SREP 90" in issue
    assert "version gate" in ENTRY and "SREP 0" in ENTRY


def test_the_two_refused_kinds_and_the_link_kind_the_erratum_keeps_are_recorded():
    """Writing p.g1 and a composed collision are refused (the exception of SREP 90); a link whose source names an
    emitted node, the third kind recorded at acceptance, keeps its element since the erratum (Open issues 6). Each is
    named in the changelog entry, the Abstract, the neutral case and Backwards compatibility."""
    for text in (ENTRY, section("Abstract"), section("Specification").split("### Defaults and the neutral case", 1)[1],
                 section("Backwards compatibility")):
        squashed = " ".join(text.split())
        assert "p.g1" in squashed or "namespaced" in squashed, text[:80]
        assert "compose" in squashed, text[:80]
        assert "link/@source" in squashed, text[:80]
        assert "Two kinds" in squashed or "two kinds" in squashed, text[:80]
        assert "three kinds" not in squashed.lower(), text[:80]
    assert "Two narrow kinds" not in ENTRY


def test_the_erratum_adds_the_positions_the_reference_resolves():
    """Rule 3 lists the node id of link/@source (split on its last `.`, special forms excluded); rule 4 adds the
    overrides of an instance or an include, in the owner's scope, and the bone names of skin weights; PRG17 lists every
    position; Open issues 6 is resolved."""
    spec = " ".join(section("Specification").split())
    rule3 = spec.split("**3. References inside the output resolve locally first.**", 1)[1].split("**4.", 1)[0]
    assert "the node id of `link/@source`" in rule3 and "`param:`, `audio:` or `marker:`" in rule3
    assert "everything before the **last** `.` of the value" in rule3
    rule4 = spec.split("**4. Bare references from outside.**", 1)[1].split("**5. Order.**", 1)[0]
    assert "**The override of an `instance` or an `include`.**" in rule4 and "`owner/Q.R`" in rule4
    assert "**The bone names of skin weights.**" in rule4 and "`skeleton/@weights`" in rule4
    prg17 = next(line for line in SREP.splitlines() if line.startswith("| PRG17 |"))
    for position in ("`link/@source`", "`layout`", "`variant`", "`instance`", "`include`", "`prop`"):
        assert position in prg17, position
    issue6 = section("Open issues").split("\n6. ", 1)[1].split("\n7. ", 1)[0]
    assert "**Resolved 2026-10-11**" in issue6
    assert re.search(r"^- 2026-10-11: erratum, decided by the schema editor", SREP, re.M)


def test_rejected_alternatives_no_longer_say_nothing_breaks():
    rejected = " ".join(section("Rejected alternatives").split())
    assert "the opt-in protects nothing" not in rejected
    assert "version gate" in rejected


def test_engine_impact_records_the_reference_on_main_and_its_kit_run():
    impact = " ".join(section("Engine impact").split())
    assert "implemented on main since 2026-10-11 (6602b81d" in impact and "d1a45c8b" in impact
    assert "link/@source" in impact and "SREP 90" in impact
    assert re.search(r"^- 2026-10-11: stays Accepted \(SREP 0, Lifecycle 5\)", SREP, re.M)


def test_srep_66_records_that_its_collision_case_now_waits_for_srep_87():
    srep66 = open(os.path.join(ROOT, "srep", "srep-0066.md"), encoding="utf-8").read()
    impact = " ".join(srep66.split("\n## Engine impact\n", 1)[1].split("\n## ", 1)[0].split())
    assert "amended by SREP 87" in impact and "p.g1" in impact
    assert "becomes Final only when the reference implementation of SREP 87 is on main" in impact
    assert "6602b81d" in impact
    conformance = srep66.split("\n## Conformance\n", 1)[1].split("\n## ", 1)[0]
    assert "`-id-collision` (amended by SREP 87: `p.g1`)" in conformance


def test_the_released_1_6_0_changelog_entry_is_left_as_released():
    """SREP 0 defines errata for SREPs only; the SREP 85 decision is recorded in SREP 85, not in the 1.6.0 entry."""
    released = LOG.split("## 1.6.0 — 2026-10-11", 1)[1].split("\n## ", 1)[0]
    assert "The class is SREP 85's open issue for the schema editor." in released
    assert "erratum of 2026-10-11" not in released and "Schema is 1.6 not 2.0" not in released
    srep85 = open(os.path.join(ROOT, "srep", "srep-0085.md"), encoding="utf-8").read()
    assert "**Decided 2026-10-11:**" in srep85 and "an erratum" not in srep85.split("## History", 1)[1][-900:]


def test_beat_program_cases_need_the_namespaced_id():
    """The beat hazard cases name the emitted node by its namespaced id beat.g1, so an engine without SREP 87 (where
    the id is g1) cannot pass them, and an engine that read beat.g1 as a generated marker id would not either."""
    for slug in ("beat-program", "beat-program-before"):
        xml = CASES[f"srep-0087-program-ids-{slug}"]["xml"]
        assert 'prop("beat.g1.x")' in xml and 'startMarker="beat.1"' in xml, slug
    assert CASES["srep-0087-program-ids-beat-program"]["expected"]["blue"] == {"cx": 200, "cy": 240, "w": 40, "h": 20}


HAND_CHECKED = {f"srep-0087-program-ids-{s}" for s in (
    "ambiguous", "composed-collision", "duplicate-local", "seed-local", "seed-local-by-hand")}


def test_cases_are_in_the_kit_as_generated_and_pending_only_where_run_py_cannot_check():
    assert set(CASES) == {f"srep-0087-program-ids-{s}" for s in srep87_cases.SLUGS}
    assert HAND_CHECKED <= set(CASES)
    for name, case in CASES.items():
        assert KIT[name] == case["expected"], name
        if name in HAND_CHECKED:
            assert case["expected"]["pending"] == kit_pending.PENDING[name], name
            assert kit_pending.SREP87 in case["expected"]["pending"] and "checked by hand" in case["expected"]["pending"]
        else:
            assert "pending" not in case["expected"] and name not in kit_pending.PENDING, name
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
    assert kit_pending.SREP87 in case["expected"]["pending"] and "PRG14" in case["expected"]["pending"]


def test_generator_is_reproducible(tmp_path):
    """Rerunning the generator writes the committed files."""
    before = open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0087.json"), "rb").read()
    subprocess.run([sys.executable, os.path.join(ROOT, "conformance", "tools", "srep87_cases.py"), "--check"],
                   check=True, capture_output=True)
    assert open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0087.json"), "rb").read() == before
