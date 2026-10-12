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

assert gap.baseline() is not None, (
    "the schema 1.5.0 files are neither the git tag nor conformance/tools/baseline-1.5.0/ "
    "with the inventory's hashes")


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
        assert re.search(r"^Status:\s+(Accepted|Final)", text, re.M)


# the canonical schema's wording of lines the SREPs' blocks carry, where it changed on acceptance
EDITED = {'      <!-- draft SREP 76, open issue 4: geodesics is an xs:boolean, true in its forms "true" and "1", whitespace collapsed -->':
          '      <!-- SREP 76, open issue 4: geodesics is an xs:boolean, true in its forms "true" and "1", whitespace collapsed -->'}


def _drafts_block(n):
    """SREP n's "diff drafts" block (it rewrites lines of these SREPs) as a map from each line it removes to the line it
    adds."""
    text = open(os.path.join(ROOT, "srep", f"srep-{n:04d}.md"), encoding="utf-8").read()
    (block,) = re.findall(r"^```diff drafts\n(.*?)^```", text, re.S | re.M)
    lines = block.split("\n")
    old = [x[1:] for x in lines if x.startswith("-") and not x.startswith("---")]
    new = [x[1:] for x in lines if x.startswith("+") and not x.startswith("+++")]
    assert len(old) == len(new) == 3
    return dict(zip(old, new))


# SREP 84 (accepted) rewrites SREP 78's PYRO9 to PYRO11 to read follow and followMargin by value; SREP 85 (accepted)
# then rewrites PYRO11 as SREP 84 left it, SREP 78's PYC6 and SREP 80's FRX11 to read their numbers by value. Each
# line SREP 78 or 80 added maps to the line the canonical schema carries after both.
_SREP84, _SREP85 = _drafts_block(84), _drafts_block(85)
EDITED.update({k: _SREP85.get(v, v) for k, v in _SREP84.items()})
EDITED.update({k: v for k, v in _SREP85.items() if k not in _SREP84.values()})


def test_the_canonical_schema_carries_every_line_the_sreps_add():
    """SREPs 76 to 81 are accepted: every line their diff and amendment blocks add to the 1.5.0 files is in schema/
    (SREP 83 and SREPs 66 to 75 change other lines; tests/test_srep_0083.py and the kit cases cover those)."""
    base = {p: set(b.decode().split("\n")) for p, b in gap.baseline().items()}
    for p, b in gap.proposed_schema().items():
        have = set(open(os.path.join(ROOT, p), encoding="utf-8").read().split("\n"))
        gone = {EDITED.get(line, line) for line in b.decode().split("\n") if line not in base[p]} - have
        assert not gone, (p, sorted(gone)[:5])


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


# kit cases of later drafts that need these drafts' syntax ("requires", e.g. SREP 84's pyro cases)
REQUIRES = {n for n, c in json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"].items()
            if c.get("requires")}


@pytest.mark.parametrize("case", sorted(p for p in glob.glob(os.path.join(ROOT, "conformance", "cases", "*.xml"))
                                        if not re.search(r"srep-00(7[6-9]|8[013])-", p)
                                        and os.path.basename(p)[:-4] not in REQUIRES), ids=os.path.basename)
def test_existing_cases_keep_their_verdict(case):
    # (SREP 83's cases, a draft stacked on these, use their syntax at versions the gates refuse; its own test checks them;
    # so do the cases of later drafts that require these)
    xml = open(case, "rb").read()
    assert verdict(PROPOSED, xml) == verdict(BASE, xml)


# SREP 76's amendment: BH5 to BH8 keep to the camera's scope, the viewport3D (SREP 74) it is in, else the document.
# The documents are the engine's corpus at feat/srep-74-viewport3d 2f79b14c (tests/corpus/invalid/<name>.scene.xml);
# viewport3D is not in this branch's XSD (SREP 74 is a draft on srep/drafts-2026-10), so only the Schematron is
# run, and V15 (SREP 74's version gate, which the engine's manifest also lists) is not part of it.
VP_HEAD = ('<scene version="1.3"><project width="64" height="64" fps="24" duration="2"/><composition>'
           '<shape id="sky" shape="rect" x="0" y="0" width="64" height="64" fill="#000000"/>'
           '<camera id="eye" x="0" y="0" z="-60" geodesics="true"/><viewport3D id="v" width="16" height="16">')
VP_TAIL = ('</viewport3D><blackHole id="hole" mass="1" x="0" y="0" z="0"/>'
           '<accretionDisk id="disk" blackHole="hole" outerRadius="20" temperatureScale="6000"/></composition></scene>')
VIEWPORT_CASES = {  # name: (inside the viewport, rules with the amendment, rules of the measured 4bf7a9e text)
    "bh6-viewport-objects-isolated": ('<object3D id="ball" primitive="sphere" radius="1"/><particles3D id="dust" rate="1"/>',
                                      [], ["BH6"]),
    "bh5-viewport-camera-sees-no-hole": ('<camera id="eye2" x="0" y="0" z="-80" geodesics="true"/>',
                                         ["BH5"], ["BH8"]),
    "bh6-viewport-camera-sees-its-objects": ('<camera id="eye2" x="0" y="0" z="-80" geodesics="true"/>'
                                             '<object3D id="ball" primitive="sphere" radius="1"/>',
                                             ["BH5", "BH6"], ["BH6", "BH8"]),
    "bh8-per-viewport": ('<camera id="eye2" x="0" y="0" z="-80" geodesics="true"/>'
                         '<camera id="eye3" x="0" y="0" z="-90" geodesics="true"/>', ["BH5", "BH8"], ["BH8"]),
}
MEASURED = gap.proposed_schema(amendments=False)


def schematron_rules(files, xml):
    sch = isoschematron.Schematron(etree.fromstring(files["schema/scene-render.sch"]), store_report=True)
    sch.validate(etree.fromstring(xml.encode()))
    return sorted(set(sch.validation_report.xpath("//svrl:failed-assert/@id", namespaces=SVRL)))


def test_the_amendment_is_separate_from_the_measured_patch():
    assert gap.srep_amendments([76]), "SREP 76 has its amendment block"
    proposed = gap.proposed_schema()["schema/scene-render.sch"].decode()
    measured = MEASURED["schema/scene-render.sch"].decode()
    assert 'name="scope" value="generate-id(ancestor::viewport3D[1])"' in proposed
    assert "viewport3D" not in measured
    # the measured text is what verify() compares with the engine's 4bf7a9e files
    assert gap.sha256(MEASURED["schema/scene-render.sch"]) == GAP["files"]["schema/scene-render.sch"]["engine_sha256"]


@pytest.mark.parametrize("name", sorted(VIEWPORT_CASES))
def test_black_hole_rules_keep_to_the_camera_scope(name):
    inside, amended, measured = VIEWPORT_CASES[name]
    xml = VP_HEAD + inside + VP_TAIL
    assert schematron_rules(gap.proposed_schema(), xml) == amended
    assert schematron_rules(MEASURED, xml) == measured


# The amendments of SREPs 76 and 80: BH1 and VOX1 refuse only the versions before 1.3 (the engine's text at
# prep/srep-76-81-followups c2a66950). The kit cases srep-0076-*-version-* and srep-0080-*-version-* check the verdicts;
# this checks that the measured text, which verify() compares with the engine's 4bf7a9e files, keeps the exact gate.
def test_the_version_amendments_are_separate_from_the_measured_patches():
    assert len(gap.srep_amendments([76])) >= 2 and gap.srep_amendments([80])
    proposed = gap.proposed_schema()["schema/scene-render.sch"].decode()
    measured = MEASURED["schema/scene-render.sch"].decode()
    for rule in ("""<sch:assert id="BH1" test="not(/scene/@version='1.0' or /scene/@version='1.1' or /scene/@version='1.2')">""",
                 """<sch:rule context="/scene[@version='1.0' or @version='1.1' or @version='1.2']">
      <sch:assert id="VOX1" """):
        assert rule in proposed and rule not in measured
    assert """<sch:assert id="BH1" test="/scene/@version='1.3'">""" in measured
    assert """<sch:rule context="/scene[@version!='1.3']">
      <sch:assert id="VOX1" """ in measured


@pytest.mark.parametrize("version,refused", [("1.0", True), ("1.1", True), ("1.2", True), ("1.3", False),
                                             ("1.4", False), ("1.5", False)])
def test_bh1_and_vox1_refuse_only_the_versions_before_1_3(version, refused):
    hole = CASES["srep-0076-valid-black-hole"][1]["xml"].replace('<scene version="1.3">', f'<scene version="{version}">')
    cells = CASES["srep-0080-valid-voxels"][1]["xml"].replace('<scene version="1.3">', f'<scene version="{version}">')
    assert verdict(PROPOSED, hole) == ("sch:BH1" if refused else "ok")
    assert verdict(PROPOSED, cells) == ("sch:VOX1" if refused else "ok")
    # the measured text refuses every version but 1.3
    assert schematron_rules(MEASURED, hole) == ([] if version == "1.3" else ["BH1"])


# The boolean amendments of SREPs 76 and 77: BH5 to BH8 and CRT11, CRT12 read "1" (and padded forms) as true, as the
# engine's model does (prep/srep-76-81-followups 298bddd6, f91dbfcc); the measured text tests only the literal 'true'.
@pytest.mark.parametrize("form,on", [("true", True), ("1", True), (" true ", True), ("false", False), ("0", False)])
def test_geodesics_and_mantle_are_read_in_every_boolean_form(form, on):
    proposed = gap.proposed_schema()
    camera = '<camera id="eye" x="0" y="0" z="-60" geodesics="true"/>'
    no_hole = VP_HEAD.split("<viewport3D")[0].replace('geodesics="true"', f'geodesics="{form}"') + "</composition></scene>"
    assert camera.replace("true", form) in no_hole
    assert schematron_rules(proposed, no_hole) == (["BH5"] if on else [])
    assert schematron_rules(MEASURED, no_hole) == (["BH5"] if form == "true" else [])
    crater = CASES["srep-0077-crt12-repose-with-mantle"][1]["xml"].replace('mantle="true"', f'mantle="{form}"')
    assert schematron_rules(proposed, crater) == (["CRT12"] if on else [])


# SREP 76's fourth amendment (open issue 1): the black-hole warnings are W11 and W12, not SREP 57's W03 and W04 (the
# engine's XSD documentation at prep/srep-76-81-followups c2a66950); the measured text, which verify() compares with
# the engine's 4bf7a9e files, keeps W03 and W04.
def test_the_black_hole_warnings_are_w11_and_w12():
    assert len(gap.srep_amendments([76])) >= 4
    proposed = gap.proposed_schema()["schema/scene-render.xsd"].decode()
    measured = MEASURED["schema/scene-render.xsd"].decode()
    for text, undrawn, denoise in ((proposed, "W11", "W12"), (measured, "W03", "W04")):
        assert f"without it nothing is drawn ({undrawn})." in text
        assert f"used ({denoise}, W05)." in text and f"it is not rendered ({undrawn})." in text
    assert not re.search(r"\(W0[34][,)]", proposed)
    codes = {name: case["expected"]["findings"].get("codes", []) for name, (n, case) in CASES.items() if n == 76}
    assert codes["srep-0076-valid-w11-no-lens"] == ["W11"] and codes["srep-0076-valid-w12-denoise"] == ["W12"]
    assert not any(c in ("W03", "W04") for cs in codes.values() for c in cs)
