"""Default-run checks (F12): the README example, the version gates against the Schematron, and a fixed sample of the
conformance corpus for level 1 against level 2 and the C14N round trip.

The corpus-wide versions of the sample tests are ``test_scene_drift_d5.py`` (``SR_SCENE_CORPUS=1``).
"""
from __future__ import annotations

import io as _io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from sr_core.scene import _generated as gen
from sr_core.scene import checks
from sr_core.scene import io as sio

ROOT = Path(__file__).resolve().parents[1]
SCH_FILE = ROOT / "schema" / "scene-render.sch"

README = ROOT / "README.md"


def _readme_example() -> str:
    """The first python block of the README's "The scene SDK" section, as the reader copies it."""
    text = README.read_text(encoding="utf-8")
    section = text.split("## The scene SDK", 1)[1]
    return re.search(r"```python\n(.*?)```", section, re.S).group(1)


README_EXAMPLE = _readme_example()


def test_the_readme_example_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "in.scene.xml").write_bytes(
        b'<!-- kept --><scene version="1.0"><project width="1" height="1" fps="30" duration="1"/>'
        b"<composition/></scene>")
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    exec(compile(README_EXAMPLE, "README.md", "exec"), namespace)  # noqa: S102
    assert namespace["scene"].check() == []  # type: ignore[attr-defined]
    written = (tmp_path / "out.scene.xml").read_bytes()
    assert b'<scene version="1.0">' in written and b'\n  <project width="1280"' in written
    assert checks.check(sio.read(written)) == []
    assert b"<!-- kept -->" in sio.to_bytes(namespace["doc"])  # type: ignore[arg-type]


def test_the_gate_list_equals_the_schematron_asserts_that_mention_version() -> None:
    """D4, independently of ``compile_gates``: plain ElementTree over the .sch."""
    ns = "{http://purl.oclc.org/dsdl/schematron}"
    found: set[str] = set()
    for rule in ET.parse(SCH_FILE).getroot().iter(ns + "rule"):
        for assertion in rule.iter(ns + "assert"):
            if "@version" in rule.get("context", "") or "@version" in assertion.get("test", ""):
                found.add(assertion.get("id") or "")
    assert "" not in found
    assert found == {g.id for g in gen.GATES}
    assert len(found) == gen.COUNTS["gate_asserts"] == 24


# ---------------------------------------------------------------------------------------------- fixed sample

SAMPLE = [
    "a1-anchor-translate", "srep-0016-absent", "srep-0029-halftone-edge", "srep-0036-geo-outline-progress",
    "srep-0044-key-handles-on-key-1", "srep-0054-ik-pole-right-bend-true", "srep-0066-program-seed-even",
    "srep-0070-path-needs-curve", "srep-0076-bh6-other-object", "srep-0084-c15-reverse-1",
    "srep-0087-program-ids-seed-local", "srep-0040-crt1-rejected", "srep-0040-version-gate",
    "srep-0046-morph-version", "srep-0059-empty-idrefs",
]
GATE_IDS = {g.id for g in gen.GATES}
SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}


@pytest.fixture(scope="module")
def lx():
    etree = pytest.importorskip("lxml.etree")
    from lxml import isoschematron

    xsd = etree.XMLSchema(etree.fromstring(checks._bundled_bytes("scene-render.xsd")))
    sch = isoschematron.Schematron(etree.fromstring(checks._bundled_bytes("scene-render.sch")), store_report=True)
    return etree, xsd, sch


def c14n(etree, raw: bytes) -> bytes:
    return etree.tostring(etree.parse(_io.BytesIO(raw)), method="c14n2", with_comments=True)


@pytest.mark.parametrize("name", SAMPLE)
def test_sample_round_trip_is_c14n_equal(lx, name: str) -> None:
    etree = lx[0]
    raw = (ROOT / "conformance" / "cases" / f"{name}.xml").read_bytes()
    assert c14n(etree, sio.to_bytes(sio.read(raw))) == c14n(etree, raw)


@pytest.mark.parametrize("name", SAMPLE)
def test_sample_level_one_agrees_with_level_two(lx, name: str) -> None:
    etree, xsd, sch = lx
    raw = (ROOT / "conformance" / "cases" / f"{name}.xml").read_bytes()
    found = checks.check(sio.read(raw))
    got = {f.code for f in found}
    tree = etree.fromstring(raw)
    xsd_ok = xsd.validate(tree)
    sch_ids = (set() if sch.validate(tree) else
               {f.get("id") or "" for f in sch.validation_report.xpath("//svrl:failed-assert", namespaces=SVRL)})
    assert got & GATE_IDS == sch_ids & GATE_IDS
    bad = (not xsd_ok) or bool(sch_ids & (GATE_IDS | {"R53"}))
    assert bool(got - {"xsd:idref"}) == bad, (sorted(got), sorted(sch_ids))
    if not xsd_ok:
        assert any(c.startswith("xsd:") for c in got)
    # the merged view keeps every level 1 finding and adds only what level 1 does not see
    merged = {f.code for f in checks.check(sio.read(raw), schema=True)}
    assert got <= merged


def test_the_sample_mixes_clean_and_refused_documents(lx) -> None:
    verdicts = {bool(checks.check(sio.read((ROOT / "conformance" / "cases" / f"{n}.xml").read_bytes())))
                for n in SAMPLE}
    assert verdicts == {True, False}


def test_expected_json_lists_the_sample() -> None:
    cases = json.loads((ROOT / "conformance" / "expected.json").read_text())["cases"]
    assert all(n in cases for n in SAMPLE)


def test_the_readme_example_is_read_from_the_readme_not_copied() -> None:
    """Drift-risk map finding 6: the test used to execute its own copy, so the README could change unnoticed."""
    assert "from sr_core.scene import Scene, read" in README_EXAMPLE and "add_project(" in README_EXAMPLE
    assert "README_EXAMPLE = " + "'" * 3 not in Path(__file__).read_text(encoding="utf-8")


def test_the_readme_names_exactly_the_layouts_to_bytes_accepts() -> None:
    from sr_core.scene.io import LAYOUTS
    text = README.read_text(encoding="utf-8").split("## The scene SDK", 1)[1].split("## Versions", 1)[0]
    bullet = re.search(r"`to_bytes\(layout=\.\.\.\)` takes (.*?)\n- ", text, re.S).group(1)
    assert set(re.findall(r'`"(\w+)"`', bullet)) == set(LAYOUTS)


def test_a_readme_example_that_no_longer_runs_is_noticed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    broken = README_EXAMPLE.replace("add_project(", "add_projekt(")
    with pytest.raises(AttributeError):
        exec(compile(broken, "README.md", "exec"), {})  # noqa: S102
