"""D5 (SREP 0, section 9): the SDK's checks do not drift from the schema's.

For every XML under ``conformance/cases`` and ``tests/fixtures``:

(a) the round trip with ``layout="preserve"`` is C14N 2.0 equal with comments, prolog and epilog included;
(b) level 1 agrees with lxml (the bundled XSD plus Schematron) on the checks level 1 performs;
(c) relabelled at every ``VERSIONS`` value, ``min_version()`` is the lowest version at which lxml raises none of the
    gate asserts.

Runs by default (about 5 s) and is skipped only when lxml is missing or ``SR_SCENE_CORPUS=0``;
``SR_SCENE_CORPUS_STRIDE=N`` takes every Nth file.

What (b) compares, and what it leaves out, explicitly:

* Compared: the set of gate ids that fire; and "level 1 is clean" against "lxml finds no XSD error, no gate assert and
  no R53". When lxml reports an XSD error, level 1 must have at least one ``xsd:*`` finding.
* Left out, ``xsd:idref``: the XSD 1.0 ID/IDREF table check is not made by libxml2 (SREP 59), so lxml has no
  counterpart for a dangling IDREF token. Duplicate ids are made by libxml2 (as a datatype error on ``xs:ID``) and
  are compared. A level 1 ``xsd:idref`` finding is instead checked against the case's expectation in
  ``conformance/expected.json`` (it must expect S10), and is allowed only where one is given.
* Left out, the Schematron asserts that are neither gates nor R53 (R54 and every other rule): level 1 does not
  perform them; level 2 does.
* The XSD declares no ``xs:key``, ``xs:unique`` or ``xs:keyref``, so no XSD identity-constraint error class exists
  beyond ID/IDREF.
* The skips of ``test_schema_rules.py``: cases of an SREP that is still a draft or in review, and (libxml2 before
  2.13) documents with an ``xs:decimal`` of more than 24 digits.
"""
from __future__ import annotations

import io as _io
import json
import os
import re
from pathlib import Path

import pytest

from sr_core.scene import _generated as gen
from sr_core.scene import checks
from sr_core.scene import io as sio

pytestmark = pytest.mark.corpus

if os.environ.get("SR_SCENE_CORPUS") == "0":
    pytest.skip("corpus tests switched off with SR_SCENE_CORPUS=0", allow_module_level=True)
etree = pytest.importorskip("lxml.etree")
from lxml import isoschematron  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STRIDE = max(1, int(os.environ.get("SR_SCENE_CORPUS_STRIDE", "1")))
FILES = sorted([*(ROOT / "conformance" / "cases").glob("*.xml"), *(ROOT / "tests" / "fixtures").rglob("*.xml")])[::STRIDE]
GATE_IDS = {g.id for g in gen.GATES}
LEVEL1_SCH_IDS = GATE_IDS | {"R53"}
SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}

XSD = etree.XMLSchema(etree.fromstring(checks._bundled_bytes("scene-render.xsd")))
SCH = isoschematron.Schematron(etree.fromstring(checks._bundled_bytes("scene-render.sch")), store_report=True)
SHORT_DECIMALS = etree.LIBXML_VERSION < (2, 13, 0)
LONG_DECIMAL = re.compile(r'="[+-]?(\d*)\.(\d+)"')
EXPECTED = json.loads((ROOT / "conformance" / "expected.json").read_text())["cases"]


def skip_reason(path: Path, raw: bytes) -> str | None:
    m = re.match(r"srep-(\d{4})-", path.name)
    if m:
        if m.group(1) == "0000":
            return "draft SREP, not yet numbered"
        srep = ROOT / "srep" / f"srep-{m.group(1)}.md"
        status = re.search(r"^Status:\s*(\S+)", srep.read_text(), re.M) if srep.exists() else None
        if status and status.group(1) in ("Draft", "Review"):
            return f"SREP {int(m.group(1))} is {status.group(1)}"
    if SHORT_DECIMALS:
        longest = max((len((a + b).lstrip("0")) for a, b in LONG_DECIMAL.findall(raw.decode("utf-8"))), default=0)
        if longest > 24:
            return "an xs:decimal of more than 24 digits, which this libxml2 refuses"
    return None


def sch_ids(raw: bytes) -> set[str]:
    tree = etree.fromstring(raw)
    if SCH.validate(tree):
        return set()
    return {f.get("id") or "" for f in SCH.validation_report.xpath("//svrl:failed-assert", namespaces=SVRL)}


def load(path: Path) -> bytes:
    raw = path.read_bytes()
    reason = skip_reason(path, raw)
    if reason:
        pytest.skip(reason)
    return raw


def c14n(raw: bytes) -> bytes:
    return etree.tostring(etree.parse(_io.BytesIO(raw)), method="c14n2", with_comments=True)


def ids(path: Path) -> str:
    return str(path.relative_to(ROOT))


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_a_round_trip_is_c14n_equal(path: Path) -> None:
    raw = load(path)
    assert c14n(sio.to_bytes(sio.read(raw))) == c14n(raw)


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_b_level1_agrees_with_lxml(path: Path) -> None:
    raw = load(path)
    scene = sio.read(raw)
    found = checks.check(scene)
    got = {f.code for f in found}
    tree = etree.fromstring(raw)
    xsd_ok = XSD.validate(tree)
    xsd_errors = [e.message for e in XSD.error_log]
    lx = sch_ids(raw)

    assert got & GATE_IDS == lx & GATE_IDS, (sorted(got & GATE_IDS), sorted(lx & GATE_IDS))

    level1_other = got - {"xsd:idref"}
    lxml_bad = (not xsd_ok) or bool(lx & LEVEL1_SCH_IDS)
    assert bool(level1_other) == lxml_bad, (sorted(got), xsd_errors[:3], sorted(lx & LEVEL1_SCH_IDS),
                                            [str(f) for f in found][:3])
    if not xsd_ok:
        assert any(c.startswith("xsd:") for c in level1_other), (sorted(got), xsd_errors[:3])

    if "xsd:idref" in got:
        want = EXPECTED.get(path.stem, {}).get("findings") or {}
        assert "S10" in want.get("codes", []), (
            "level 1 reports a dangling IDREF that the case does not expect", [str(f) for f in found][:3])


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_c_min_version_is_the_lowest_version_lxml_accepts(path: Path) -> None:
    raw = load(path)
    scene = sio.read(raw)
    original = scene._attrs.get("version")
    lowest: str | None = None
    try:
        for version in gen.VERSIONS:
            scene._attrs["version"] = version
            if not (sch_ids(sio.to_bytes(scene)) & GATE_IDS):
                lowest = version
                break
    finally:
        if original is None:
            scene._attrs.pop("version", None)
        else:
            scene._attrs["version"] = original
    if lowest is None:
        with pytest.raises(Exception):
            checks.min_version(scene)
    else:
        assert checks.min_version(scene) == lowest
