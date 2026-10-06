"""SREP 10: draped map ground and globes on object3D. The fragments (primitives map and globe, six attributes,
C47, R28, R29) and the SREP's two cases.

The 1.2 enumeration value of scene/@version and the version gate V5 are applied centrally, so the cases are
checked here with version="1.1" substituted for version="1.2"; nothing else in them is changed."""
import glob
import json
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0010-*.xml")))
ASSETS = ('<tiles id="t" src="a.pmtiles"/><tiles id="dem" src="dem.pmtiles"/>'
          '<map id="m" width="64" height="64" projection="web-mercator"><basemap tiles="t"/></map>'
          '<image id="i" src="x.png" width="4" height="4"/>')


def as_1_1(path):
    return open(path, "rb").read().replace(b'version="1.2"', b'version="1.1"', 1)


def obj(attrs):
    return doc(f'<object3D id="o" {attrs}/>', assets=ASSETS)


def test_the_two_cases_exist():
    assert [os.path.basename(c) for c in CASES] == ["srep-0010-globe-orientation.xml", "srep-0010-map-ground.xml"]


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    assert verdict(as_1_1(case)) == "ok"


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_has_an_expected_entry(case):
    cases = json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"]
    assert cases[os.path.basename(case)[:-4]]["rule"] == "SREP 10"


GOOD = {
    "map ground": obj('primitive="map" map="m"'),
    "map ground with terrain": obj('primitive="map" map="m" terrain="dem" terrainEncoding="mapbox" exaggeration="2.5" '
                                   'buildings="true" textureSize="4096" resolution="128"'),
    "globe": obj('primitive="globe" map="m" radius="60" segments="128" textureSize="64"'),
    "globe with exaggeration 0": obj('primitive="globe" map="m" exaggeration="0" textureSize="8192"'),
    "new attributes on another primitive": obj('primitive="box" textureSize="2048" buildings="false" exaggeration="1"'),
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_accepted(name):
    assert verdict(GOOD[name]) == "ok"


SCH_BAD = {
    "C47 map without @map": (obj('primitive="map"'), "C47"),
    "C47 globe without @map": (obj('primitive="globe"'), "C47"),
    "R28 @map names an image": (obj('primitive="map" map="i"'), "R28"),
    "R28 @map names a tiles asset": (obj('primitive="globe" map="t"'), "R28"),
    "R29 @terrain names a map": (obj('primitive="map" map="m" terrain="m"'), "R29"),
    "R29 @terrain names an image": (obj('primitive="map" map="m" terrain="i"'), "R29"),
    "R29 @terrain names nothing": (obj('primitive="map" map="m" terrain="nope"'), "R29"),
    "R28 on another primitive": (obj('primitive="box" map="i"'), "R28"),
}


@pytest.mark.parametrize("name", sorted(SCH_BAD))
def test_rejected_by_schematron(name):
    xml, rule = SCH_BAD[name]
    v = verdict(xml)
    assert v.startswith("sch:") and rule in v.split(":", 1)[1].split(","), v


XSD_BAD = {
    "terrainEncoding unknown": obj('primitive="map" map="m" terrainEncoding="terrain-rgb"'),
    "textureSize 63": obj('primitive="map" map="m" textureSize="63"'),
    "textureSize 8193": obj('primitive="map" map="m" textureSize="8193"'),
    "exaggeration negative": obj('primitive="map" map="m" exaggeration="-1"'),
    "buildings not boolean": obj('primitive="map" map="m" buildings="maybe"'),
    "primitive unknown": obj('primitive="terrain" map="m"'),
}


@pytest.mark.parametrize("name", sorted(XSD_BAD))
def test_rejected_by_xsd(name):
    assert verdict(XSD_BAD[name]) == "xsd"
