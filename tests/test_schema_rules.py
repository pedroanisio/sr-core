"""The canonical XSD and Schematron: documents they must reject, and valid documents they must keep accepting."""
import glob
import os
import re

import pytest

etree = pytest.importorskip("lxml.etree")
from lxml import isoschematron  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XSD = etree.XMLSchema(etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd")))
SCH = isoschematron.Schematron(etree.parse(os.path.join(ROOT, "schema", "scene-render.sch")), store_report=True)


def doc(body="", version="1.1", assets="", head=""):
    return (f'<scene version="{version}"><project width="100" height="100" fps="1" duration="1"/>{head}'
            f'{("<assets>" + assets + "</assets>") if assets else ""}<composition>{body}</composition></scene>')


def verdict(xml):
    t = etree.fromstring(xml)
    if not XSD.validate(t):
        return "xsd"
    if not SCH.validate(t):
        ids = SCH.validation_report.xpath("//svrl:failed-assert/@id",
                                          namespaces={"svrl": "http://purl.oclc.org/dsdl/svrl"})
        return "sch:" + ",".join(sorted(set(ids)))
    return "ok"


BAD = {
    "1.0 with flock": (doc('<flock id="f" width="10" height="10"/>', "1.0"), "V6"),
    "1.0 with geo asset": (doc(version="1.0", assets='<geo id="g" src="x.geojson"/>'), "V6"),
    "1.0 with clay": (doc('<object3D id="o" primitive="clay"><blob/></object3D>', "1.0"), "V6"),
    "1.0 with torus": (doc('<object3D id="o" primitive="torus"/>', "1.0"), "V7"),
    "slime colorLow=url(#nope)": (doc('<slime id="s" width="10" height="10" colorLow="url(#nope)"/>'), "R30-colorLow"),
    "material baseColor=var(--nope)": (doc(head='<materials><material id="m" baseColor="var(--nope)"/></materials>'),
                                       "R31-baseColor"),
    "flock sprite shape, no sprite": (doc('<flock id="f" width="10" height="10" shape="sprite"/>'), "C50"),
    "flock sprite -> audio": (doc('<flock id="f" width="10" height="10" shape="sprite" sprite="a"/>',
                                  assets='<audio id="a" src="x.wav"/>'), "R32"),
    "flock parent = itself": (doc('<flock id="f" width="10" height="10" parent="f"/>'), "R10"),
    "erosion heightmap -> audio": (doc('<erosion id="e" width="10" height="10" heightmap="a"/>',
                                       assets='<audio id="a" src="x.wav"/>'), "R33"),
    "flock forceFields -> nothing": (doc('<flock id="f" width="10" height="10" forceFields="nope"/>'), "R34"),
    "clay without blobs": (doc('<object3D id="o" primitive="clay"/>'), "C51"),
    "fluidSource start > end": (doc('<fluid id="f" width="10" height="10"><fluidSource start="5" end="1"/></fluid>'),
                                "C52"),
}
XSD_BAD = {
    "pin lat 200": '<pin lon="0" lat="200"/>',
    "route points words": '<route points="hello world"/>',
    "palette banana": '<geoLayer geo="g" palette="banana"/>',
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_rejected_by_schematron(name):
    xml, rule = BAD[name]
    v = verdict(xml)
    assert v.startswith("sch:") and rule in v.split(":", 1)[1].split(","), v


@pytest.mark.parametrize("name", sorted(XSD_BAD))
def test_rejected_by_xsd(name):
    xml = doc(assets=f'<geo id="g" src="x.geojson"/><map id="m" width="10" height="10">{XSD_BAD[name]}</map>')
    assert verdict(xml) == "xsd"


def test_domain_must_increase():
    bad = doc(assets='<geo id="g" src="x.geojson"/><map id="m" width="10" height="10">'
                     '<geoLayer geo="g" fillBy="v" domain="5 1 3"/></map>')
    assert "C53" in verdict(bad)
    good = bad.replace('domain="5 1 3"', 'domain="1 3 5"')
    assert verdict(good) == "ok"


GOOD = [
    doc('<flock id="f" width="10" height="10" shape="sprite" sprite="i" forceFields="w"/>',
        assets='<image id="i" src="x.png" width="4" height="4"/>'),
    doc('<object3D id="o" primitive="clay"><blob/></object3D>'),
    doc(assets='<geo id="g" src="x.geojson"/><map id="m" width="10" height="10"><pin lon="-179.5" lat="89.9"/>'
               '<route points="0,0 10.5,-20 1e1,5"/><geoLayer geo="g" palette="#F7FBFF var(--t) #08306B"/></map>'),
]


def test_valid_documents_still_pass():
    physics = '<physics><forceField id="w" type="wind"/></physics>'
    for x in GOOD:
        x = x.replace("</composition></scene>", "</composition>" + physics + "</scene>") if 'forceFields' in x else x
        assert verdict(x) in ("ok",), (verdict(x), x)


def pending_srep(case: str) -> str | None:
    """Why a case is not yet expected to validate, or None. Cases of an SREP that is still a draft
    (srep-0000-*, not yet numbered) or in Draft or Review use syntax the canonical schema gains only on acceptance."""
    import re
    m = re.match(r"srep-(\d{4})-", os.path.basename(case))
    if not m:
        return None
    if m.group(1) == "0000":
        return "draft SREP, not yet numbered"
    path = os.path.join(ROOT, "srep", f"srep-{m.group(1)}.md")
    status = re.search(r"^Status:\s*(\S+)", open(path).read(), re.M) if os.path.exists(path) else None
    if status and status.group(1) in ("Draft", "Review"):
        return f"SREP {int(m.group(1))} is {status.group(1)}"
    return None


SCH_RULE_IDS = set(re.findall(r'<sch:assert id="([^"]+)"', open(os.path.join(ROOT, "schema", "scene-render.sch")).read()))


def findings_of(case):
    """The "findings" entry of a case in expected.json, or None."""
    import json
    spec = json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"]
    return spec.get(os.path.basename(case)[:-4], {}).get("findings")


@pytest.mark.parametrize("case", sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "*.xml"))),
                         ids=os.path.basename)
def test_conformance_cases_are_valid(case):
    reason = pending_srep(case)
    if reason:
        pytest.skip(f"{reason}: validated once the SREP is accepted")
    want = findings_of(case)
    if want is not None and want.get("valid") is False:
        # a case that is invalid on purpose: the schema must reject it with the rules the case lists
        got = verdict(open(case, "rb").read())
        rules = {c for c in want.get("codes", []) if c in SCH_RULE_IDS}
        assert got.startswith("sch:") and rules <= set(got[4:].split(",")), (got, rules)
        return
    assert verdict(open(case, "rb").read()) == "ok"


def test_pending_srep_rule(tmp_path):
    assert pending_srep("cases/a1-anchor-translate.xml") is None
    assert pending_srep("cases/srep-0000-basemaps.xml") == "draft SREP, not yet numbered"
    assert pending_srep("cases/srep-0008-anything.xml") is None          # SREP 8 is Final
