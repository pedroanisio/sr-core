"""SREP 9: map tile assets and basemaps. The fragments (tiles, basemap, R27, C46) and the SREP's four cases.

The 1.2 enumeration value of scene/@version and the version gate V5 are applied centrally, so the cases are
checked here with as written (version="1.2")."""
import glob
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0009-*.xml")))
SHA = "0" * 64


def as_1_1(path):
    return open(path, "rb").read()


def tiles_doc(tiles_attrs='src="a.pmtiles"', basemap_attrs='tiles="t"', extra_map=""):
    return doc(assets=f'<tiles id="t" {tiles_attrs}/>'
                      f'<map id="m" width="10" height="10"><basemap {basemap_attrs}/>{extra_map}</map>')


def test_the_four_cases_exist():
    assert [os.path.basename(c) for c in CASES] == ["srep-0009-basemap-raster.xml", "srep-0009-basemap-vector.xml",
                                                    "srep-0009-basemap-warp.xml", "srep-0009-basemap-zoom.xml"]


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    assert verdict(as_1_1(case)) == "ok"


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_has_an_expected_entry(case):
    import json
    cases = json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"]
    assert cases[os.path.basename(case)[:-4]]["rule"] == "SREP 9"


GOOD = {
    "tiles with src and a basemap": tiles_doc(),
    "tiles with a service, cache and pin": tiles_doc(f'url="https://t.example/{{z}}/{{x}}/{{y}}.png" cache="c.pmtiles" cacheSha256="{SHA}"'),
    "tiles with every attribute": tiles_doc(f'src="a.pmtiles" sha256="{SHA}" tileSize="256" minZoom="2" maxZoom="24" attribution="x"'),
    "basemap with every attribute": tiles_doc(basemap_attrs='id="b" tiles="t" mapStyle="protomaps-dark" opacity="0.5" '
                                                            'detail="-1.5" labels="false" attribution="false"'),
    "basemap before a geoLayer": doc(assets='<geo id="g" src="x.geojson"/><tiles id="t" src="a.pmtiles"/>'
                                            '<map id="m" width="10" height="10"><basemap tiles="t"/><geoLayer geo="g"/></map>'),
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_accepted(name):
    assert verdict(GOOD[name]) == "ok"


SCH_BAD = {
    "R27 basemap names no tiles asset": (doc(assets='<map id="m" width="10" height="10"><basemap tiles="m"/></map>'), "R27"),
    "R27 basemap names an image": (doc(assets='<image id="i" src="x.png" width="4" height="4"/>'
                                              '<map id="m" width="10" height="10"><basemap tiles="i"/></map>'), "R27"),
    "C46 tiles with no source": (tiles_doc(''), "C46"),
    "C46 service without cache": (tiles_doc('url="https://t.example/{z}/{x}/{y}.png"'), "C46"),
    "C46 service without pin": (tiles_doc('url="https://t.example/{z}/{x}/{y}.png" cache="c.pmtiles"'), "C46"),
}


@pytest.mark.parametrize("name", sorted(SCH_BAD))
def test_rejected_by_schematron(name):
    xml, rule = SCH_BAD[name]
    v = verdict(xml)
    assert v.startswith("sch:") and rule in v.split(":", 1)[1].split(","), v


XSD_BAD = {
    "basemap without @tiles": tiles_doc(basemap_attrs=""),
    "maxZoom 25": tiles_doc('src="a.pmtiles" maxZoom="25"'),
    "minZoom -1": tiles_doc('src="a.pmtiles" minZoom="-1"'),
    "tileSize 0": tiles_doc('src="a.pmtiles" tileSize="0"'),
    "basemap opacity 2": tiles_doc(basemap_attrs='tiles="t" opacity="2"'),
    "bad sha256": tiles_doc('src="a.pmtiles" sha256="XYZ"'),
    "tiles takes no @license": tiles_doc('src="a.pmtiles" license="MIT"'),
    "basemap takes no @style": tiles_doc(basemap_attrs='tiles="t" style="x"'),
}


@pytest.mark.parametrize("name", sorted(XSD_BAD))
def test_rejected_by_xsd(name):
    assert verdict(XSD_BAD[name]) == "xsd"
